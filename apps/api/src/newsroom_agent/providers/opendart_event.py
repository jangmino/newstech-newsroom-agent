"""Bounded event financial/disclosure tools using the credential-safe DART transport."""

import asyncio
import io
import re
import zipfile
from contextlib import nullcontext
from decimal import Decimal
from html.parser import HTMLParser

from newsroom_agent.event_catalog import period_list
from newsroom_agent.event_models import EventConditions, EventData, TraceStep
from newsroom_agent.providers.opendart_financials import OpenDartError
from newsroom_agent.providers.opendart_research import ACCOUNT_IDS, OpenDartResearchClient
from newsroom_agent.research_models import Company, ResearchFact

ACCOUNTS = {**ACCOUNT_IDS, "당기순이익": {"ifrs-full_ProfitLoss", "ifrs_ProfitLoss"}}
REPORTS = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
# Only documented endpoints and fields; other report types remain explicitly title-only.
DETAILS = {
    "소송등의제기": (
        "lwstLg.json",
        {"icnm": "사건명", "rq_cn": "청구내용", "cpct": "관할법원", "ft_ctp": "향후대책"},
    ),
    "유형자산양수결정": (
        "tgastInhDecsn.json",
        {"ast_nm": "자산명", "inhdtl_inhprc": "양수금액(원)", "inh_pp": "양수목적"},
    ),
    "타법인주식및출자증권양수결정": (
        "otcprStkInvscrInhDecsn.json",
        {"iscmp_cmpnm": "발행회사", "inhdtl_inhprc": "양수금액(원)", "inh_pp": "양수목적"},
    ),
}


def normalize_finance(
    payload,
    company: Company,
    year: int,
    report: str,
    basis: str,
    amount: str,
    metrics: list[str],
    at: str,
) -> list[ResearchFact]:
    rows = payload.get("list")
    if not isinstance(rows, list):
        raise OpenDartError("invalid_response")
    field = (
        "thstrm_add_amount"
        if amount == "누적" and report not in ("11011", "11013")
        else "thstrm_amount"
    )
    facts = []
    for metric in metrics:
        matches = [
            r
            for r in rows
            if isinstance(r, dict)
            and r.get("account_id") in ACCOUNTS[metric]
            and r.get("sj_div") in ("IS", "CIS")
        ]
        if not matches:
            raise OpenDartError("missing_account")
        preferred = [r for r in matches if r["sj_div"] == "IS"] or matches
        if len(preferred) != 1:
            raise OpenDartError("ambiguous_account")
        row = preferred[0]
        # IS/CIS duplicates are allowed only if identity, values and receipt agree.
        checks = ["rcept_no", "corp_code", "bsns_year", "reprt_code", "currency", field]
        if any(any(r.get(k) != row.get(k) for k in checks) for r in matches):
            raise OpenDartError("ambiguous_account")
        if (
            row.get("corp_code") != company.code
            or row.get("bsns_year") != str(year)
            or row.get("reprt_code") != report
            or row.get("currency") != "KRW"
            or row.get("account_detail") not in ("-", "")
            or not re.fullmatch(r"\d{14}", row.get("rcept_no", ""))
        ):
            raise OpenDartError("invalid_response")
        value = row.get(field, "")
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"-?\d+", value)
            or (metric == "매출액" and Decimal(value) < 0)
        ):
            raise OpenDartError("invalid_amount")
        facts.append(
            ResearchFact(
                id="pending",
                entity=company.name,
                metric=metric,
                period=str(year),
                value=value,
                unit="원",
                kind="observation",
                retrieved_at=at,
                source_urls=[f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}"],
                details={
                    "corp_code": company.code,
                    "bsns_year": str(year),
                    "reprt_code": report,
                    "fs_div": basis,
                    "amount_basis": amount,
                    "amount_field": field,
                    "account_id": row["account_id"],
                    "account_name": row.get("account_nm", ""),
                    "statement": row["sj_div"],
                    "receipt": row["rcept_no"],
                    "prior_reported_value": str(
                        row.get("frmtrm_amount", row.get("frmtrm_q_amount", ""))
                    ),
                    "prior_cumulative_value": str(row.get("frmtrm_add_amount", "")),
                    "vintage": "조회 당시 각 보고서 당기 값; 후속 보고서 재작성 값과 구별",
                },
            )
        )
    return facts


def categories(title: str) -> set[str]:
    result = set()
    if any(v in title for v in ("투자", "유형자산", "영업양수", "타법인주식")):
        result.add("투자")
    if any(
        v in title
        for v in (
            "주식",
            "지분",
            "소유상황",
            "대량보유",
            "유상증자",
            "무상증자",
            "회사합병",
            "회사분할",
        )
    ):
        result.add("지분")
    if any(v in title for v in ("소송", "판결", "가처분")):
        result.add("소송")
    return result


class PlainDocument(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def document_excerpt(body: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            entries = archive.infolist()
            if not 1 <= len(entries) <= 20 or sum(e.file_size for e in entries) > 8_000_000:
                raise ValueError()
            parts = []
            for entry in entries:
                if not entry.filename.lower().endswith((".xml", ".html")) or entry.flag_bits & 1:
                    continue
                raw = archive.read(entry)
                if b"<!ENTITY" in raw.upper():
                    raise ValueError()
                parser = PlainDocument()
                parser.feed(raw.decode("utf-8"))
                parts.extend(parser.parts)
        text = " | ".join(parts)
        if not text:
            raise ValueError()
        return text[:12000]
    except Exception:
        raise OpenDartError("invalid_response") from None


class EventDartClient(OpenDartResearchClient):
    async def document(self, client, receipt: str) -> str:
        with self._limiter.slot() if self._limiter else nullcontext():
            async with asyncio.timeout(self._timeout):
                async with client.stream(
                    "GET",
                    f"{self.base_url}/document.xml",
                    params={"crtfc_key": self._api_key, "rcept_no": receipt},
                ) as response:
                    if response.status_code != 200:
                        raise OpenDartError("unavailable")
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        body.extend(chunk)
                        if len(body) > 4_000_000:
                            raise OpenDartError("invalid_response")
        return document_excerpt(bytes(body))

    async def event_financials(self, company: Company, c: EventConditions) -> EventData:
        facts, trace = [], []
        payloads = {}
        basis = "CFS" if c.statement_basis == "연결" else "OFS"
        async with self._session() as client:

            async def report_data(year, report):
                key = (year, report)
                if key not in payloads:
                    params = {
                        "corp_code": company.code,
                        "bsns_year": str(year),
                        "reprt_code": report,
                        "fs_div": basis,
                    }
                    payloads[key] = await self._request_json(
                        client, "fnlttSinglAcntAll.json", params
                    )
                    trace.append(
                        TraceStep(
                            tool="OpenDART 재무제표",
                            status="complete",
                            at=self._clock().isoformat(),
                            parameters=params,
                        )
                    )
                return payloads[key]

            for period in period_list(c):
                year = int(period[:4])
                quarter = int(period[-1]) if c.frequency == "분기" else 4
                report = REPORTS[quarter]
                payload = await report_data(year, report)
                rows = normalize_finance(
                    payload,
                    company,
                    year,
                    report,
                    basis,
                    c.amount_basis,
                    c.metrics,
                    self._clock().isoformat(),
                )
                if c.frequency == "분기" and quarter == 4 and c.amount_basis == "당기":
                    q3 = normalize_finance(
                        await report_data(year, REPORTS[3]),
                        company,
                        year,
                        REPORTS[3],
                        basis,
                        "누적",
                        c.metrics,
                        self._clock().isoformat(),
                    )
                    for row, previous in zip(rows, q3, strict=True):
                        if row.details["account_id"] != previous.details["account_id"]:
                            raise OpenDartError("ambiguous_account")
                        row.value = str(Decimal(row.value) - Decimal(previous.value))
                        row.formula = "같은 사업연도 연간 당기값 − 3분기 누적값"
                        row.source_urls += previous.source_urls
                        row.details.update(
                            q3_receipt=previous.details["receipt"],
                            q3_cumulative=previous.value,
                            derivation_warning=(
                                "서로 다른 보고서의 차감값입니다. 정정·재작성 "
                                "여부를 원문에서 확인해야 합니다."
                            ),
                        )
                for row in rows:
                    row.period = period
                facts.extend(rows)
        return EventData(
            facts=facts,
            trace=trace,
            caveats=[
                (
                    "각 기간 보고서의 당기 값입니다. 후속 보고서의 "
                    "비교값 재작성·정정으로 값이 달라질 수 있습니다."
                ),
                "당기순이익은 지배기업 소유주 귀속 이익과 다릅니다. 계정 ID를 확인해 주세요.",
                "금액은 원입니다. 공시 본문의 백만원 단위와 환산해 대조해 주세요.",
                *(
                    [
                        (
                            "4분기 당기는 연간−3분기 누적 차감입니다. 보고서 간 "
                            "회계정책·재작성 여부를 확인하기 전 확정 실적으로 인용하지 마세요."
                        )
                    ]
                    if c.frequency == "분기"
                    and any(p.endswith("Q4") for p in period_list(c))
                    and c.amount_basis == "당기"
                    else []
                ),
            ],
        )

    async def event_disclosures(self, companies: list[Company], c: EventConditions) -> EventData:
        facts, trace, caveats = [], [], []
        partial = False
        async with self._session() as client:
            for company in companies:
                params = {
                    "corp_code": company.code,
                    "bgn_de": c.start.replace("-", ""),
                    "end_de": c.end.replace("-", ""),
                    "last_reprt_at": "N",
                    "page_count": "100",
                }
                listings = []
                for page in range(1, 4):
                    try:
                        payload = await self._request_json(
                            client, "list.json", {**params, "page_no": str(page)}
                        )
                    except OpenDartError as exc:
                        if exc.code != "no_data":
                            raise
                        payload = {"list": [], "total_page": 0}
                    rows = payload.get("list")
                    if not isinstance(rows, list) or type(payload.get("total_page")) is not int:
                        raise OpenDartError("invalid_response")
                    listings.extend(rows)
                    trace.append(
                        TraceStep(
                            tool="OpenDART 공시 목록",
                            status="complete" if rows else "empty",
                            at=self._clock().isoformat(),
                            parameters={**params, "page_no": str(page)},
                        )
                    )
                    if payload["total_page"] <= page:
                        break
                    if page == 3:
                        partial = True
                        caveats.append(
                            f"{company.name}: 목록이 3페이지를 넘어 "
                            f"일부만 확인했습니다. 접수 기간을 줄여 주세요."
                        )
                selected = []
                seen = set()
                for row in listings:
                    if (
                        not isinstance(row, dict)
                        or row.get("corp_code") != company.code
                        or not re.fullmatch(r"\d{14}", row.get("rcept_no", ""))
                        or not isinstance(row.get("report_nm"), str)
                    ):
                        raise OpenDartError("invalid_response")
                    if not params["bgn_de"] <= row.get("rcept_dt", "") <= params["end_de"]:
                        raise OpenDartError("invalid_response")
                    if row["rcept_no"] not in seen and categories(row["report_nm"]) & set(
                        c.metrics
                    ):
                        selected.append(row)
                        seen.add(row["rcept_no"])
                detailed = {}
                for title, (endpoint, fields) in DETAILS.items():
                    if not any(title in re.sub(r"\s+|ㆍ", "", r["report_nm"]) for r in selected):
                        continue
                    try:
                        p = await self._request_json(
                            client,
                            endpoint,
                            {
                                k: v
                                for k, v in params.items()
                                if k in ("corp_code", "bgn_de", "end_de")
                            },
                        )
                        for detail in p.get("list", []):
                            if detail.get("corp_code") != company.code:
                                raise OpenDartError("invalid_response")
                            detailed[detail["rcept_no"]] = {
                                label: str(detail.get(key, ""))[:2000]
                                for key, label in fields.items()
                            }
                        trace.append(
                            TraceStep(
                                tool=endpoint,
                                status="complete",
                                at=self._clock().isoformat(),
                                parameters={"corp_code": company.code},
                            )
                        )
                    except OpenDartError as exc:
                        partial = True
                        trace.append(
                            TraceStep(
                                tool=endpoint,
                                status="failed",
                                at=self._clock().isoformat(),
                                note=exc.code,
                            )
                        )
                for index, row in enumerate(selected):
                    receipt = row["rcept_no"]
                    content = detailed.get(receipt)
                    if not content and index < 6:
                        try:
                            excerpt = await self.document(client, receipt)
                            content = {
                                "공식 본문 발췌": excerpt,
                                (
                                    "발췌 범위"
                                ): "공식 원문 앞부분 최대 12,000자; 전체 문서가 아닙니다.",
                            }
                            trace.append(
                                TraceStep(
                                    tool="OpenDART 원문",
                                    status="complete",
                                    at=self._clock().isoformat(),
                                    parameters={"rcept_no": receipt},
                                )
                            )
                        except OpenDartError as exc:
                            trace.append(
                                TraceStep(
                                    tool="OpenDART 원문",
                                    status="failed",
                                    at=self._clock().isoformat(),
                                    parameters={"rcept_no": receipt},
                                    note=exc.code,
                                )
                            )
                    status = (
                        "철회 표시"
                        if "철" in row.get("rm", "") or "철회" in row["report_nm"]
                        else "정정 확인 필요"
                        if "정" in row.get("rm", "") or "정정" in row["report_nm"]
                        else "목록 확인"
                    )
                    facts.append(
                        ResearchFact(
                            id="pending",
                            entity=company.name,
                            metric="·".join(sorted(categories(row["report_nm"]) & set(c.metrics))),
                            period=row["rcept_dt"],
                            value=row["report_nm"].strip(),
                            unit="공시",
                            kind="observation",
                            retrieved_at=self._clock().isoformat(),
                            source_urls=[f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}"],
                            formula="공식 공시 목록·접수번호 기준 중복 제거",
                            details={
                                "receipt": receipt,
                                "status": status,
                                "coverage": "공식 상세 항목 확인"
                                if content
                                else "목록만 확인 · 본문 미확인",
                                **(content or {}),
                            },
                        )
                    )
                if not selected:
                    caveats.append(
                        f"{company.name}: 조회한 접수 기간의 분류 규칙에 해당하는 "
                        f"공시 0건. 관련 사건이나 공시가 전혀 없다는 뜻은 아닙니다."
                    )
        if any(f.details["coverage"].startswith("목록만") for f in facts):
            partial = True
            caveats.append(
                "상세 API가 제공하지 않는 공시는 목록만 표시했습니다. "
                "제목으로 본문 내용·금액·영향을 추론하지 않습니다."
            )
        facts.sort(
            key=lambda f: (
                (f.metric, f.period) if c.comparison == "종류별" else (f.period, f.entity)
            ),
            reverse=True,
        )
        caveats += [
            (
                "정정/철회 건은 삭제하거나 원공시와 임의로 합치지 "
                "않습니다. 같은 제목도 별개 사건일 수 있습니다."
            ),
            (
                "기간은 접수일 기준입니다. 이전 공시의 정정 "
                "및 기간 밖 원공시는 원문에서 확인해 주세요."
            ),
            (
                "투자·지분·소송은 명시된 제목 분류 규칙입니다. 모든 "
                "관련 공시의 완전한 검색이나 뉴스 가치 순위가 아닙니다."
            ),
        ]
        return EventData(
            facts=facts,
            trace=trace,
            caveats=caveats,
            coverage="partial" if partial else "complete" if facts else "empty",
        )

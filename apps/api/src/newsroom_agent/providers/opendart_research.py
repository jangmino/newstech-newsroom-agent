"""Company discovery and bounded annual financial tools for Part 2."""

import asyncio
import io
import re
import zipfile
from contextlib import nullcontext
from datetime import datetime
from xml.etree import ElementTree

from newsroom_agent.providers.opendart import OpenDartClient
from newsroom_agent.providers.opendart_financials import OpenDartError
from newsroom_agent.research_models import Company, ResearchFact

ACCOUNT_IDS = {
    "매출액": {"ifrs-full_Revenue", "ifrs_Revenue"},
    "영업이익": {"dart_OperatingIncomeLoss"},
}


def read_companies(body: bytes) -> tuple[Company, ...]:
    """Read a bounded ZIP in memory; never extract files or resolve XML entities."""
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            entries = archive.infolist()
            if (
                len(entries) != 1
                or entries[0].filename.upper() != "CORPCODE.XML"
                or entries[0].file_size > 80_000_000
                or entries[0].flag_bits & 1
            ):
                raise ValueError()
            xml = archive.read(entries[0])
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ValueError()
        companies = []
        seen = set()
        for count, (_, element) in enumerate(
            ElementTree.iterparse(io.BytesIO(xml), events=("end",))
        ):
            if count > 1_500_000:
                raise ValueError()
            if element.tag != "list":
                continue
            stock = (element.findtext("stock_code") or "").strip()
            if re.fullmatch(r"[0-9]{6}", stock):
                company = Company(
                    name=element.findtext("corp_name"),
                    code=element.findtext("corp_code"),
                    stock_code=stock,
                )
                if company.code in seen:
                    raise ValueError()
                companies.append(company)
                seen.add(company.code)
            element.clear()
        if not companies:
            raise ValueError()
        return tuple(companies)
    except Exception:
        raise OpenDartError("invalid_response") from None


def find_companies(companies: tuple[Company, ...], query: str) -> list[Company]:
    def normalized(value: str) -> str:
        return re.sub(r"\s+|주식회사|\(주\)", "", value).casefold()

    needle = normalized(query)
    if not needle:
        return []
    exact = [c for c in companies if needle in {normalized(c.name), c.stock_code}]
    if exact:
        return exact
    return sorted(
        (c for c in companies if needle in normalized(c.name)), key=lambda c: (c.name, c.code)
    )[:8]


def normalize_financials(
    payload: dict,
    company: Company,
    year: int,
    metrics: list[str],
    retrieved_at: datetime,
) -> list[ResearchFact]:
    rows = payload.get("list")
    if not isinstance(rows, list) or not rows or len(rows) > 2000:
        raise OpenDartError("invalid_response")
    for row in rows:
        if (
            not isinstance(row, dict)
            or any(
                row.get(k) != v
                for k, v in {
                    "corp_code": company.code,
                    "bsns_year": str(year),
                    "reprt_code": "11011",
                }.items()
            )
            or row.get("fs_div", "CFS") != "CFS"
        ):
            raise OpenDartError("invalid_response")
    facts = []
    for metric in metrics:
        if metric not in ACCOUNT_IDS:
            raise OpenDartError("invalid_request")
        selected = [
            r
            for r in rows
            if r.get("sj_div") in {"IS", "CIS"} and r.get("account_id") in ACCOUNT_IDS[metric]
        ]
        if len(selected) != 1:
            raise OpenDartError("missing_account" if not selected else "ambiguous_account")
        row = selected[0]
        if row.get("currency") != "KRW":
            raise OpenDartError("unsupported_currency")
        raw = row.get("thstrm_amount")
        if raw is None or raw in ("", "-"):
            raise OpenDartError("missing_value")
        if (
            not isinstance(raw, str)
            or len(raw) > 64
            or not re.fullmatch(r"-?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", raw.strip())
        ):
            raise OpenDartError("invalid_amount")
        digits = raw.strip().replace(",", "")
        if len(digits.lstrip("-")) > 30 or (metric == "매출액" and int(digits) < 0):
            raise OpenDartError("invalid_amount")
        receipt = row.get("rcept_no")
        if (
            not isinstance(receipt, str)
            or not re.fullmatch(r"[0-9]{14}", receipt)
            or not isinstance(row.get("account_nm"), str)
            or not row["account_nm"].strip()
            or len(row["account_nm"]) > 100
            or row.get("account_detail") not in (None, "", "-")
        ):
            raise OpenDartError("invalid_response")
        facts.append(
            ResearchFact(
                id="pending",
                entity=company.name,
                metric=metric,
                period=str(year),
                value=str(int(digits)),
                unit="원",
                kind="observation",
                source_urls=[f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}"],
                retrieved_at=retrieved_at.isoformat(),
                details={
                    "corp_code": company.code,
                    "stock_code": company.stock_code,
                    "account_id": row["account_id"],
                    "account_name": row["account_nm"],
                    "raw_amount": raw,
                    "receipt_no": receipt,
                    "statement_basis": "CFS",
                    "report_code": "11011",
                    "currency": "KRW",
                },
            )
        )
    return facts


class OpenDartResearchClient(OpenDartClient):
    async def companies(self) -> tuple[Company, ...]:
        async with self._session() as client:
            with self._limiter.slot() if self._limiter else nullcontext():
                async with asyncio.timeout(self._timeout):
                    async with client.stream(
                        "GET", f"{self.base_url}/corpCode.xml", params={"crtfc_key": self._api_key}
                    ) as response:
                        if response.status_code != 200:
                            raise OpenDartError(
                                "rate_limited" if response.status_code == 429 else "unavailable"
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65_536):
                            body.extend(chunk)
                            if len(body) > 16_000_000:
                                raise OpenDartError("invalid_response")
            return read_companies(bytes(body))

    async def annual_years(self, company: Company) -> list[int]:
        async with self._session() as client:
            try:
                payload = await self._request_json(
                    client,
                    "list.json",
                    {
                        "corp_code": company.code,
                        "bgn_de": "20150101",
                        "end_de": self._clock().strftime("%Y%m%d"),
                        "last_reprt_at": "Y",
                        "pblntf_detail_ty": "A001",
                        "page_count": "100",
                        "page_no": "1",
                    },
                )
            except OpenDartError as exc:
                if exc.code == "no_data":
                    return []
                raise
        rows = payload.get("list")
        if not isinstance(rows, list) or len(rows) > 100 or str(payload.get("total_page")) != "1":
            raise OpenDartError("invalid_response")
        years = set()
        for row in rows:
            if not isinstance(row, dict) or row.get("corp_code") != company.code:
                raise OpenDartError("invalid_response")
            name = row.get("report_nm")
            if not isinstance(name, str):
                raise OpenDartError("invalid_response")
            match = re.search(r"사업보고서\s*\((\d{4})\.12\)", name)
            if (
                match
                and 2015 <= int(match[1]) < self._clock().year
                and "철" not in row.get("rm", "")
            ):
                years.add(int(match[1]))
        return sorted(years)

    async def financials(
        self,
        company: Company,
        years: list[int],
        metrics: list[str],
    ) -> list[ResearchFact]:
        if (
            not 2 <= len(years) <= 5
            or years != sorted(set(years))
            or any(type(y) is not int or not 2015 <= y < self._clock().year for y in years)
            or not metrics
            or len(metrics) != len(set(metrics))
            or any(m not in ACCOUNT_IDS for m in metrics)
        ):
            raise OpenDartError("invalid_request")
        facts = []
        async with self._session() as client:
            for year in years:
                payload = await self._request_json(
                    client,
                    "fnlttSinglAcntAll.json",
                    {
                        "corp_code": company.code,
                        "bsns_year": str(year),
                        "reprt_code": "11011",
                        "fs_div": "CFS",
                    },
                )
                facts.extend(normalize_financials(payload, company, year, metrics, self._clock()))
        return facts

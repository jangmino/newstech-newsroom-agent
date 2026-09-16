"""Narrow, deterministic OpenDART revenue contract; no network or settings access."""

import re
from dataclasses import dataclass
from datetime import datetime

SAMSUNG_CORP_CODE = "00126380"
ANNUAL_REPORT_CODE = "11011"
REVENUE_ACCOUNT_IDS = ("ifrs-full_Revenue", "ifrs_Revenue")

ERROR_MESSAGES = {
    "disabled": "OpenDART 실제 조회가 꺼져 있습니다.",
    "configuration": "OpenDART 연결 설정을 확인해 주세요.",
    "invalid_request": "삼성전자 연간 연결 매출액의 시작·종료 연도를 확인해 주세요.",
    "authentication": "OpenDART 인증키 또는 접근 권한을 확인해 주세요.",
    "rate_limited": "OpenDART 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.",
    "no_data": "해당 연도의 사업보고서 자료가 없습니다. 조회 연도를 확인해 주세요.",
    "missing_account": "사업보고서에서 지원하는 매출액 계정을 찾지 못했습니다.",
    "ambiguous_account": "매출액 계정이 여러 개입니다. 공시 원문에서 비교할 계정을 확인해 주세요.",
    "missing_value": "매출액 값이 없어 비교할 수 없습니다. 공시 원문을 확인해 주세요.",
    "invalid_amount": "매출액을 원 단위의 유효한 금액으로 해석할 수 없습니다.",
    "unsupported_currency": "매출액의 통화가 원화(KRW)가 아니거나 확인되지 않습니다.",
    "invalid_response": "OpenDART 응답이 조회 조건과 맞지 않거나 형식이 올바르지 않습니다.",
    "timeout": "OpenDART 응답 시간이 초과됐습니다. 잠시 후 다시 시도해 주세요.",
    "unavailable": "OpenDART 자료를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.",
}


class OpenDartError(Exception):
    """Only fixed application messages, never provider bodies or credential-bearing URLs."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(ERROR_MESSAGES[code])


@dataclass(frozen=True, kw_only=True)
class AnnualRevenue:
    year: int
    amount: str
    raw_amount: str
    account_id: str
    account_name: str
    statement_type: str
    receipt_no: str
    retrieved_at: datetime
    corp_code: str = SAMSUNG_CORP_CODE
    report_code: str = ANNUAL_REPORT_CODE
    statement_basis: str = "CFS"
    currency: str = "KRW"
    unit: str = "원"

    @property
    def source_url(self) -> str:
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={self.receipt_no}"

    @property
    def query_parameters(self) -> dict[str, str]:
        return {
            "corp_code": self.corp_code, "bsns_year": str(self.year),
            "reprt_code": self.report_code, "fs_div": self.statement_basis,
        }


@dataclass(frozen=True)
class RevenuePair:
    start: AnnualRevenue
    end: AnnualRevenue
    caveats: tuple[str, ...] = (
        "각 사업연도 보고서의 당기값입니다. 최신 보고서의 재작성 비교값과 다를 수 있습니다.",
        "정정 공시로 값이 바뀔 수 있습니다. 접수번호와 공시 원문을 함께 확인해 주세요.",
        "공식 API 조회와 조건 확인은 사실 검증 완료나 기사 사용 승인이 아닙니다.",
    )


def _amount(raw: object) -> tuple[str, str]:
    if raw is None or (isinstance(raw, str) and raw.strip() in {"", "-"}):
        raise OpenDartError("missing_value")
    if not isinstance(raw, str) or len(raw) > 64:
        raise OpenDartError("invalid_amount")
    raw = raw.strip()
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", raw):
        raise OpenDartError("invalid_amount")
    digits = raw.replace(",", "")
    if len(digits) > 30:
        raise OpenDartError("invalid_amount")
    # No float conversion, rounding, or inferred scale. Zero is a valid reported amount.
    return str(int(digits)), raw


def normalize_revenue(payload: dict, year: int, retrieved_at: datetime) -> AnnualRevenue:
    rows = payload.get("list")
    if not isinstance(rows, list) or len(rows) > 2000:
        raise OpenDartError("invalid_response")
    if not rows:
        raise OpenDartError("no_data")
    candidates = []
    for row in rows:
        if not isinstance(row, dict) or any(
            row.get(key) != value for key, value in {
                "corp_code": SAMSUNG_CORP_CODE, "bsns_year": str(year),
                "reprt_code": ANNUAL_REPORT_CODE,
            }.items()
        ):
            raise OpenDartError("invalid_response")
        # The full-statement endpoint selects CFS in the request; reject contradictory echoes.
        if "fs_div" in row and row["fs_div"] != "CFS":
            raise OpenDartError("invalid_response")
        if row.get("sj_div") in ("IS", "CIS") and row.get("account_id") in REVENUE_ACCOUNT_IDS:
            candidates.append(row)
    if not candidates:
        raise OpenDartError("missing_account")
    if len(candidates) != 1:
        raise OpenDartError("ambiguous_account")
    row = candidates[0]
    if row.get("currency") != "KRW":
        raise OpenDartError("unsupported_currency")
    account_name, receipt_no = row.get("account_nm"), row.get("rcept_no")
    if (
        not isinstance(account_name, str) or not account_name.strip() or len(account_name) > 100
        or not isinstance(receipt_no, str) or not re.fullmatch(r"[0-9]{14}", receipt_no)
        or row.get("account_detail") not in (None, "", "-")
    ):
        raise OpenDartError("invalid_response")
    amount, raw = _amount(row.get("thstrm_amount"))
    return AnnualRevenue(
        year=year, amount=amount, raw_amount=raw,
        account_id=row["account_id"], account_name=account_name.strip(),
        statement_type=row["sj_div"], receipt_no=receipt_no, retrieved_at=retrieved_at,
    )

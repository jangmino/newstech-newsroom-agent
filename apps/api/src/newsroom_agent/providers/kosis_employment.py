"""Verified KOSIS employment contract; no network, settings, or runtime fixture access."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

ORG_ID = "101"
TABLE_ID = "DT_1DA7015S"
TABLE_NAME = "행정구역(시도)/연령별 경제활동인구"
ITEM_ID = "T90"
AGE_CODE = "75"
YEARS = (2020, 2021, 2022, 2023, 2024)
SOURCE_URL = f"https://kosis.kr/statHtml/statHtml.do?orgId={ORG_ID}&tblId={TABLE_ID}"
# Fixed historical comparison scope. Never infer it from ALL or current metadata leaf nodes.
REGIONS = MappingProxyType({
    "11": "서울특별시", "21": "부산광역시", "22": "대구광역시", "23": "인천광역시",
    "24": "광주광역시", "25": "대전광역시", "26": "울산광역시", "29": "세종특별자치시",
    "31": "경기도", "32": "강원특별자치도", "33": "충청북도", "34": "충청남도",
    "35": "전북특별자치도", "36": "전라남도", "37": "경상북도", "38": "경상남도",
    "39": "제주특별자치도",
})
CAPITAL_REGIONS = ("11", "23", "31")
GROUPS = MappingProxyType({
    "전국 시·도": tuple(REGIONS),
    "수도권 시·도": CAPITAL_REGIONS,
    "비수도권 시·도": tuple(code for code in REGIONS if code not in CAPITAL_REGIONS),
})

ERROR_MESSAGES = {
    "disabled": "KOSIS 실제 조회가 꺼져 있습니다. 모의 자료를 선택하거나 운영자에게 문의해 주세요.",
    "configuration": "KOSIS 연결 설정을 확인해야 합니다. 운영자에게 문의해 주세요.",
    "authentication": "KOSIS 인증키 또는 접근 권한을 확인해야 합니다. 운영자에게 문의해 주세요.",
    "rate_limited": "KOSIS 요청 한도에 도달했습니다. 잠시 후 다시 조회해 주세요.",
    "invalid_request": "KOSIS 조회 조건을 처리하지 못했습니다. 조건과 연결 설정을 확인해 주세요.",
    "timeout": "KOSIS 응답 시간이 초과됐습니다. 잠시 후 다시 조회해 주세요.",
    "unavailable": "KOSIS 자료를 가져오지 못했습니다. 잠시 후 다시 조회해 주세요.",
    "unsupported_conditions": "실제 고용 자료는 15~29세 고용률의 시도별 비교만 지원합니다.",
    "unsupported_period": "2020~2024년 안에서 시작 연도보다 늦은 종료 연도를 선택해 주세요.",
    "invalid_response": "KOSIS 자료의 표·지역·연령·항목·주기가 조회 조건과 맞지 않습니다.",
    "invalid_timestamp": "KOSIS 자료의 조회 시각이나 최종수정일을 확인할 수 없습니다.",
    "unsupported_unit": "고용률 단위가 %가 아니거나 확인되지 않습니다. 원표를 확인해 주세요.",
    "no_data": "선택한 조건의 고용률 자료가 없습니다. 기간과 원표를 확인해 주세요.",
    "incomplete_series": "일부 지역·연도의 자료가 없습니다. 누락된 값은 0으로 계산하지 않습니다.",
    "duplicate_value": "같은 지역·연도의 자료가 여러 개입니다. 원표의 조건을 확인해 주세요.",
    "missing_value": "고용률 값이 비어 있습니다. 원표에서 해당 지역·연도의 값을 확인해 주세요.",
    "invalid_value": (
        "고용률을 0~100% 범위의 숫자로 확인할 수 없습니다. 원표의 통계 부호와 주석을 확인해 주세요."
    ),
}


class KosisError(Exception):
    """Fixed messages only: never echo provider values, URLs, or exception details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(ERROR_MESSAGES[code])


class KosisContractError(KosisError):
    """A deterministic request/response contract failure."""


@dataclass(frozen=True, kw_only=True)
class EmploymentQuery:
    entity: str
    metric: str
    age_range: str
    start_year: int
    end_year: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.entity, str) or self.entity not in GROUPS
            or self.metric != "고용률" or self.age_range != "15-29세"
        ):
            raise KosisContractError("unsupported_conditions")
        if (
            type(self.start_year) is not int or type(self.end_year) is not int
            or self.start_year not in YEARS or self.end_year not in YEARS
            or self.start_year >= self.end_year
        ):
            raise KosisContractError("unsupported_period")

    @property
    def region_codes(self) -> tuple[str, ...]:
        return GROUPS[self.entity]

    @property
    def years(self) -> tuple[int, ...]:
        return tuple(range(self.start_year, self.end_year + 1))

    @property
    def parameters(self) -> dict[str, str]:
        """Public parameters only; the backend transport supplies authentication."""
        return {
            "method": "getList", "orgId": ORG_ID, "tblId": TABLE_ID,
            "objL1": "+".join(self.region_codes), "objL2": AGE_CODE, "itmId": ITEM_ID,
            "prdSe": "Y", "startPrdDe": str(self.start_year), "endPrdDe": str(self.end_year),
            "format": "json", "jsonVD": "Y", "smblChk": "Y",
        }


@dataclass(frozen=True, kw_only=True)
class AnnualEmploymentRate:
    region_code: str
    region_name: str
    year: int
    value: str
    raw_value: str
    last_changed_at: date
    unit: str = "%"
    period_code: str = "A"


@dataclass(frozen=True, kw_only=True)
class EmploymentSeries:
    query: EmploymentQuery
    observations: tuple[AnnualEmploymentRate, ...]
    retrieved_at: datetime
    org_id: str = ORG_ID
    table_id: str = TABLE_ID
    item_id: str = ITEM_ID
    age_code: str = AGE_CODE
    source_url: str = SOURCE_URL
    caveats: tuple[str, ...] = (
        "공표된 고용률을 사용합니다. 반올림 전 수치나 취업자 수를 역산하지 않습니다.",
        "시도별 비율을 평균내어 권역 전체 고용률로 해석하지 않습니다.",
        "표본오차·자료 개정·지역 경계 변경과 기간별 비교 가능성을 원표에서 확인해 주세요.",
        "공식 API 조회와 조건 확인은 사실 검증 완료나 기사 사용 승인이 아닙니다.",
    )


def _rate(raw: object) -> tuple[str, str]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise KosisContractError("missing_value")
    if (
        not isinstance(raw, str) or len(raw) > 32
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", raw.strip())
    ):
        # Keep statistical symbols out of arithmetic, without guessing what each means.
        raise KosisContractError("invalid_value")
    value = Decimal(raw.strip())
    if not 0 <= value <= 100:
        raise KosisContractError("invalid_value")
    return format(value, "f"), raw


def _last_changed(raw: object) -> date:
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        raise KosisContractError("invalid_timestamp")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise KosisContractError("invalid_timestamp") from None


def normalize_employment(
    payload: object, query: EmploymentQuery, retrieved_at: datetime,
) -> EmploymentSeries:
    """Require one valid cell per requested region/year; never return a partial ranking."""
    if not isinstance(retrieved_at, datetime) or retrieved_at.utcoffset() is None:
        raise KosisContractError("invalid_timestamp")
    if not isinstance(payload, list) or len(payload) > len(REGIONS) * len(YEARS):
        raise KosisContractError("invalid_response")
    if not payload:
        raise KosisContractError("no_data")
    expected = {(region, str(year)) for region in query.region_codes for year in query.years}
    observations: dict[tuple[str, str], AnnualEmploymentRate] = {}
    for row in payload:
        if not isinstance(row, dict) or any(
            row.get(key) != value for key, value in {
                "ORG_ID": ORG_ID, "TBL_ID": TABLE_ID, "TBL_NM": TABLE_NAME,
                "C1_OBJ_NM": "시도별", "C2_OBJ_NM": "연령계층별",
                "C2": AGE_CODE, "C2_NM": "15 - 29세", "ITM_ID": ITEM_ID,
                "ITM_NM": "고용률", "PRD_SE": "A",
            }.items()
        ):
            raise KosisContractError("invalid_response")
        region, year = row.get("C1"), row.get("PRD_DE")
        if (
            not isinstance(region, str) or not isinstance(year, str)
            or (region, year) not in expected or row.get("C1_NM") != REGIONS[region]
            or any(row.get(f"C{level}") not in (None, "") for level in range(3, 9))
        ):
            raise KosisContractError("invalid_response")
        if row.get("UNIT_NM") != "%":
            raise KosisContractError("unsupported_unit")
        if (region, year) in observations:
            raise KosisContractError("duplicate_value")
        value, raw = _rate(row.get("DT"))
        observations[region, year] = AnnualEmploymentRate(
            region_code=region, region_name=REGIONS[region], year=int(year),
            value=value, raw_value=raw, last_changed_at=_last_changed(row.get("LST_CHN_DE")),
        )
    if set(observations) != expected:
        raise KosisContractError("incomplete_series")
    return EmploymentSeries(
        query=query, retrieved_at=retrieved_at,
        observations=tuple(observations[region, str(year)] for region in query.region_codes
                           for year in query.years),
    )

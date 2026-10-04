"""Verified event catalog and validation. No model-supplied provider codes."""

import re
from datetime import date, timedelta

from newsroom_agent.event_models import EventConditions
from newsroom_agent.providers.kosis_employment import GROUPS, REGIONS

AGES = {"15-29세": "75", "20-29세": "20", "15-64세": "63"}
REGION_CODES = {"전국 집계": "00", **{name: code for code, name in REGIONS.items()}}
ENTITIES = [*GROUPS, *REGION_CODES]
FINANCE_METRICS = ["매출액", "영업이익", "당기순이익"]
EMPLOYMENT_METRICS = {"고용률": ("T90", "%"), "취업자 수": ("T30", "천명"), "실업률": ("T80", "%")}
DISCLOSURE_METRICS = ["투자", "지분", "소송"]
PERIOD_NOTICE = "공식 제공 기간 확인: 2026-09-18. 연간 2025년, 월간 2026년 8월까지 검증했습니다."


def regions(c: EventConditions) -> list[str]:
    result = []
    for entity in c.entities:
        result.extend(GROUPS[entity] if entity in GROUPS else [REGION_CODES[entity]])
    return list(dict.fromkeys(result))


def table_for(c: EventConditions, metric: str) -> str:
    if c.entities == ["전국 집계"]:
        return "DT_1DA7002S"
    return "DT_1DA7031S" if metric == "취업자 수" else "DT_1DA7015S"


def month_index(value: str) -> int:
    if not re.fullmatch(r"20\d{2}-\d{2}", value):
        raise ValueError()
    y, m = map(int, value.split("-"))
    if not 1 <= m <= 12:
        raise ValueError()
    return y * 12 + m - 1


def period_list(c: EventConditions) -> list[str]:
    if c.frequency == "월간":
        a, b = month_index(c.start), month_index(c.end)
        return [f"{i // 12:04d}{i % 12 + 1:02d}" for i in range(a, b + 1)]
    if c.frequency == "분기":
        if not all(re.fullmatch(r"20\d{2}-Q[1-4]", v) for v in (c.start, c.end)):
            raise ValueError()
        a, b = [int(v[:4]) * 4 + int(v[-1]) - 1 for v in (c.start, c.end)]
        return [f"{i // 4}-Q{i % 4 + 1}" for i in range(a, b + 1)]
    if not all(re.fullmatch(r"20\d{2}", v) for v in (c.start, c.end)):
        raise ValueError()
    return [str(y) for y in range(int(c.start), int(c.end) + 1)]


DISCLOSURE_MAX_DAYS = 93
DISCLOSURE_MIN_DATE = "2015-01-01"


def disclosure_period_limits() -> dict:
    return {"max_days": DISCLOSURE_MAX_DAYS, "min_date": DISCLOSURE_MIN_DATE,
            "max_date": date.today().isoformat()}


def disclosure_period_error(start_text: str, end_text: str) -> str:
    try:
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
        if start.isoformat() != start_text or end.isoformat() != end_text:
            raise ValueError()
    except ValueError:
        return "공시 시작일과 종료일을 YYYY-MM-DD 형식의 실제 날짜로 입력해 주세요."
    if start > end:
        return "공시 시작일은 종료일보다 늦을 수 없습니다. 두 날짜를 확인해 주세요."
    if start < date.fromisoformat(DISCLOSURE_MIN_DATE) or end > date.today():
        return f"공시 접수일은 {DISCLOSURE_MIN_DATE}부터 오늘까지 선택해 주세요."
    days = (end - start).days + 1
    if days > DISCLOSURE_MAX_DAYS:
        earliest = end - timedelta(days=DISCLOSURE_MAX_DAYS - 1)
        return (f"선택한 공시 기간은 시작일·종료일 포함 {days}일입니다. "
                f"이 실습 앱은 한 번에 최대 {DISCLOSURE_MAX_DAYS}일을 조회합니다. "
                f"종료일을 유지하려면 시작일을 {earliest.isoformat()} 이후로 바꾸거나, "
                "기간을 나누어 각각 승인해 주세요.")
    return ""


def validate_conditions(c: EventConditions) -> dict[str, str]:
    errors = {}
    if c.tool == "undetermined":
        return {"tool": "기업 공시·기업 실적·청년 고용 중 조사할 내용을 알려 주세요."}
    if not c.entities or len(set(c.entities)) != len(c.entities):
        errors["entities"] = "중복 없이 조사 대상을 선택해 주세요."
    allowed = (
        FINANCE_METRICS
        if c.tool == "financials"
        else EMPLOYMENT_METRICS
        if c.tool == "employment"
        else DISCLOSURE_METRICS
    )
    if (
        not c.metrics
        or len(set(c.metrics)) != len(c.metrics)
        or any(m not in allowed for m in c.metrics)
    ):
        errors["metrics"] = "이 자료에서 제공하는 지표를 선택해 주세요."
    if c.tool in ("financials", "disclosures"):
        if len(c.company_codes) != len(c.entities) or len(set(c.company_codes)) != len(
            c.company_codes
        ):
            errors["entities"] = "회사명과 공식 코드를 계획 단계에서 먼저 확인해 주세요."
    if c.tool == "disclosures":
        if message := disclosure_period_error(c.start, c.end):
            errors["period"] = message
        if c.comparison not in ("접수일순", "종류별"):
            errors["comparison"] = (
                "접수일순 또는 종류별로 비교해 주세요. 뉴스 가치 순위는 사람이 판단합니다."
            )
        return errors
    if c.comparison not in ("증감 폭", "증감률"):
        errors["comparison"] = "증감 폭 또는 증감률을 선택해 주세요."
    if c.comparison_period not in ("전기", "전년 동기", "시작·종료"):
        errors["comparison_period"] = "전기, 전년 동기 또는 시작·종료를 선택해 주세요."
    if c.tool == "financials":
        if len(c.entities) != 1:
            errors["entities"] = "재무 비교는 한 회사의 기간 변화를 조회합니다."
        if (
            c.frequency not in ("연간", "분기")
            or c.statement_basis not in ("연결", "별도")
            or c.amount_basis not in ("당기", "누적")
        ):
            errors["basis"] = "연간/분기, 연결/별도, 당기/누적을 확인해 주세요."
        if (
            c.frequency == "분기"
            and c.amount_basis == "누적"
            and (
                c.comparison_period != "전년 동기"
                and not (c.comparison_period == "시작·종료" and c.start[-2:] == c.end[-2:])
            )
        ):
            errors["comparison_period"] = (
                "누적 분기는 같은 길이의 기간끼리 비교해야 합니다. 전년 동기를 선택해 주세요."
            )
    else:
        if any(e not in ENTITIES for e in c.entities) or c.company_codes:
            errors["entities"] = "공식 전국 집계 또는 시도 범위를 선택해 주세요."
        if c.frequency not in ("연간", "월간"):
            errors["frequency"] = "이 실습은 연간 또는 월간 고용 자료를 지원합니다."
        if c.age_range not in AGES:
            errors["age_range"] = (
                "공식 표에서 확인한 연령은 15~29세·20~29세·15~64세입니다. "
                "다른 연령으로 대신 조회하지 않습니다."
            )
        if c.entities != ["전국 집계"]:
            if "실업률" in c.metrics:
                errors["metrics"] = (
                    "선택한 시도·연령 조합의 실업률은 이 카탈로그에서 제공하지 "
                    "않습니다. 전국 집계의 실업률을 별도로 조사할 수 있습니다."
                )
            if c.frequency == "월간" and "고용률" in c.metrics:
                errors["frequency"] = (
                    "시도별 청년 고용률은 월간 자료가 없습니다. 연간 "
                    "고용률 또는 월간 취업자 수를 선택해 주세요."
                )
    try:
        ps = period_list(c)
        maximum = 5 if c.frequency == "연간" else 13 if c.frequency == "월간" else 8
        if not 2 <= len(ps) <= maximum:
            raise ValueError()
        if c.frequency == "연간" and not ("2020" <= ps[0] <= ps[-1] <= "2025"):
            raise ValueError()
        if c.frequency == "월간" and not ("202001" <= ps[0] <= ps[-1] <= "202608"):
            raise ValueError()
        if c.frequency == "분기" and not ("2020-Q1" <= ps[0] <= ps[-1] <= "2026-Q2"):
            raise ValueError()
        stride = 12 if c.frequency == "월간" else 4 if c.frequency == "분기" else 1
        if c.comparison_period == "전년 동기" and len(ps) <= stride:
            errors["period"] = "전년 동기 값이 포함되도록 시작 기간을 한 해 앞까지 넓혀 주세요."
    except ValueError:
        errors["period"] = (
            "검증된 제공 기간에서 연간 2~5년, 분기 2~8개, 월간 2~13개월을 선택해 주세요."
        )
    return errors

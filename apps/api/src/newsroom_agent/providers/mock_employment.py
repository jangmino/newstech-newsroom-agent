"""Authored synthetic fixture, not KOSIS data or a snapshot of an official response."""

from newsroom_agent.calculations import ValuePair, rank_changes
from newsroom_agent.models import CalculationResult, QueryConditions

DATASET_ID = "synthetic-employment-v1"
YEARS = (2020, 2021, 2022, 2023, 2024)
GROUPS = {
    "전국 시·도": ("가상 지역 A", "가상 지역 B", "가상 지역 C", "가상 지역 D"),
    "수도권 시·도": ("가상 지역 A", "가상 지역 B"),
    "비수도권 시·도": ("가상 지역 C", "가상 지역 D"),
}
# Series align with YEARS. Missing/zero values are deliberate workshop cases.
SERIES = {
    "15-29세": {
        "고용률": {
            "가상 지역 A": ("40", "42", "44", "46", "48"),
            "가상 지역 B": ("50", "52", "56", "58", "59"),
            "가상 지역 C": ("30", "33", "34", "36", "37"),
            "가상 지역 D": ("60", "61", "62", "63", "64"),
        },
        "취업자 수": {
            "가상 지역 A": ("100", "102", "104", "108", "112"),
            "가상 지역 B": ("200", "202", "210", "216", "218"),
            "가상 지역 C": ("80", "82", "85", "87", "89"),
            "가상 지역 D": ("140", "139", "138", "137", "136"),
        },
    },
    "15-34세": {
        "고용률": {
            "가상 지역 A": ("45", "47", "50", "53", "55"),
            "가상 지역 B": ("55", "57", "58", "59", "60"),
            "가상 지역 C": ("35", "36", "37", "39", "40"),
            "가상 지역 D": ("65", "64", "63", "62", "62"),
        },
        "취업자 수": {
            "가상 지역 A": ("0", "10", "12", "14", "16"),
            "가상 지역 B": ("50", "55", "60", "65", "70"),
            "가상 지역 C": ("80", "82", None, "90", None),
            "가상 지역 D": ("100", "101", None, "104", None),
        },
    },
}


def calculate_employment(conditions: QueryConditions) -> CalculationResult:
    start_year, end_year = (int(year) for year in conditions.period.split("-"))
    values = SERIES[conditions.filters["age_range"]][conditions.metric]
    unit = "%" if conditions.metric == "고용률" else "천 명"
    pairs = [
        ValuePair(
            region,
            values[region][YEARS.index(start_year)],
            values[region][YEARS.index(end_year)],
            unit,
            unit,
        )
        for region in GROUPS[conditions.entity]
    ]
    rows, warnings = rank_changes(pairs, unit, conditions.comparison)
    result_unit = "%" if conditions.comparison == "증감률" else "%p" if unit == "%" else unit
    return CalculationResult(
        dataset_id=DATASET_ID,
        start_year=start_year,
        end_year=end_year,
        input_unit=unit,
        result_unit=result_unit,
        rows=rows,
        warnings=warnings,
    )

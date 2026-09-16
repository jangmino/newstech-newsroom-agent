"""Offline contract tests: official public excerpt plus explicitly mutated failure cases."""

import copy
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from newsroom_agent.providers.kosis_employment import (
    EmploymentQuery,
    KosisContractError,
    normalize_employment,
)

FIXTURE = json.loads((Path(__file__).parents[3] / "fixtures/public-data/"
                     "kosis-youth-employment-2020-2024.json").read_text())
CAPTURED = datetime.fromisoformat(FIXTURE["retrieved_at"])


def query(**changes):
    return EmploymentQuery(**({
        "entity": "전국 시·도", "metric": "고용률", "age_range": "15-29세",
        "start_year": 2020, "end_year": 2024,
    } | changes))


def selected_rows(request):
    return copy.deepcopy([
        row for row in FIXTURE["rows"]
        if row["C1"] in request.region_codes and int(row["PRD_DE"]) in request.years
    ])


def test_official_excerpt_matches_contract_and_preserves_auditable_values():
    request = query()
    assert request.parameters == FIXTURE["request"]["parameters"]
    # Input order is irrelevant. Identity is determined by codes, not position or sorting by value.
    result = normalize_employment(list(reversed(FIXTURE["rows"])), request, CAPTURED)
    assert len(result.observations) == 85
    assert result.org_id == "101" and result.table_id == "DT_1DA7015S"
    assert result.item_id == "T90" and result.age_code == "75"
    assert result.source_url == FIXTURE["source_url"]
    assert result.query is request and result.retrieved_at == CAPTURED
    by_cell = {(row.region_code, row.year): row for row in result.observations}
    assert by_cell["11", 2020].value == "46.6"
    assert by_cell["11", 2024].value == "51.2"
    assert by_cell["39", 2024].value == "42.1"
    for raw in FIXTURE["rows"]:
        value = by_cell[raw["C1"], int(raw["PRD_DE"])]
        assert value.raw_value == raw["DT"]
        assert Decimal(value.value) == Decimal(raw["DT"])
        assert value.region_name == raw["C1_NM"]
        assert value.unit == raw["UNIT_NM"] == "%"
        assert value.period_code == raw["PRD_SE"] == "A"
        assert value.last_changed_at == date.fromisoformat(raw["LST_CHN_DE"])
        assert value.last_changed_at != result.retrieved_at.date()
    assert "기사 사용 승인" in result.caveats[-1]
    assert FIXTURE["verification"]["human_statistical_review_completed"] is False


def test_official_metadata_supports_only_the_documented_dimensions():
    metadata = FIXTURE["metadata"]
    items = metadata["items"]
    metric = next(row for row in items if row["OBJ_ID"] == "ITEM" and row["ITM_ID"] == "T90")
    assert metric["ITM_NM"] == "고용률" and metric["UNIT_NM"] == "%"
    assert not any(row["ITM_NM"] == "취업자 수" or row["ITM_ID"] == "T30" for row in items)
    age = next(row for row in items if row["OBJ_ID"] == "G" and row["ITM_ID"] == "75")
    assert age["ITM_NM"] == "15 - 29세" and age["OBJ_ID_SN"] == "2"
    assert not any(row["OBJ_ID"] == "G" and "34" in row["ITM_NM"]
                   and row["ITM_NM"].startswith("15") for row in items)
    regions = {row["ITM_ID"]: row for row in items if row["OBJ_ID"] == "A"}
    request = query()
    assert set(regions) - set(request.region_codes) == {"00", "12"}
    for row in normalize_employment(FIXTURE["rows"], request, CAPTURED).observations:
        assert regions[row.region_code]["ITM_NM"] == row.region_name
        assert regions[row.region_code]["OBJ_ID_SN"] == "1"
    assert {str(year) for year in request.years} <= set(metadata["annual_periods"])


@pytest.mark.parametrize("entity,count", [("전국 시·도", 17), ("수도권 시·도", 3),
                                         ("비수도권 시·도", 14)])
def test_region_subsets_keep_individual_rates_and_inclusive_years(entity, count):
    request = query(entity=entity, start_year=2021, end_year=2023)
    result = normalize_employment(selected_rows(request), request, CAPTURED)
    assert len(result.observations) == count * 3
    assert {row.year for row in result.observations} == {2021, 2022, 2023}
    assert request.parameters["startPrdDe"] == "2021"
    assert request.parameters["endPrdDe"] == "2023"
    assert request.parameters["objL1"].split("+") == list(request.region_codes)
    assert all(row.region_code not in ("00", "12") for row in result.observations)
    if entity == "수도권 시·도":
        assert {row.region_name for row in result.observations} == {
            "서울특별시", "인천광역시", "경기도",
        }
    if entity == "비수도권 시·도":
        assert not {"11", "23", "31"} & set(request.region_codes)


@pytest.mark.parametrize("change,code", [
    ({"age_range": "15-34세"}, "unsupported_conditions"),
    ({"metric": "취업자 수"}, "unsupported_conditions"),
    ({"metric": "경제활동참가율"}, "unsupported_conditions"),
    ({"entity": "전국"}, "unsupported_conditions"),
    ({"entity": []}, "unsupported_conditions"),
    ({"start_year": 2019}, "unsupported_period"),
    ({"end_year": 2025}, "unsupported_period"),
    ({"start_year": 2024, "end_year": 2024}, "unsupported_period"),
    ({"start_year": 2024, "end_year": 2020}, "unsupported_period"),
    ({"start_year": "2020"}, "unsupported_period"),
    ({"start_year": True}, "unsupported_period"),
    ({"end_year": 2024.0}, "unsupported_period"),
])
def test_unsupported_conditions_are_not_silently_substituted(change, code):
    with pytest.raises(KosisContractError) as caught:
        query(**change)
    assert caught.value.code == code


@pytest.mark.parametrize("change,code", [
    ({"ORG_ID": "999"}, "invalid_response"),
    ({"TBL_ID": "another-table"}, "invalid_response"),
    ({"TBL_NM": "다른 표"}, "invalid_response"),
    ({"C1": "00"}, "invalid_response"),
    ({"C1": "12"}, "invalid_response"),
    ({"C1": []}, "invalid_response"),
    ({"C1_NM": "다른 지역"}, "invalid_response"),
    ({"C1_OBJ_NM": "성별"}, "invalid_response"),
    ({"C2": "301"}, "invalid_response"),
    ({"C2_NM": "15-34세"}, "invalid_response"),
    ({"C2_OBJ_NM": "성별"}, "invalid_response"),
    ({"C3": "성별코드"}, "invalid_response"),
    ({"ITM_ID": "T60"}, "invalid_response"),
    ({"ITM_NM": "경제활동참가율"}, "invalid_response"),
    ({"PRD_SE": "Y"}, "invalid_response"),
    ({"PRD_SE": "Q"}, "invalid_response"),
    ({"PRD_DE": "202001"}, "invalid_response"),
    ({"PRD_DE": "2025"}, "invalid_response"),
    ({"PRD_DE": 2020}, "invalid_response"),
    ({"UNIT_NM": "천명"}, "unsupported_unit"),
    ({"UNIT_NM": "%p"}, "unsupported_unit"),
    ({"UNIT_NM": None}, "unsupported_unit"),
    ({"LST_CHN_DE": "2026-02-30"}, "invalid_timestamp"),
    ({"LST_CHN_DE": "20260629"}, "invalid_timestamp"),
    ({"LST_CHN_DE": None}, "invalid_timestamp"),
])
def test_identity_unit_and_date_mismatches_fail_the_whole_series(change, code):
    rows = selected_rows(query())
    rows[0].update(change)
    with pytest.raises(KosisContractError) as caught:
        normalize_employment(rows, query(), CAPTURED)
    assert caught.value.code == code


@pytest.mark.parametrize("raw,code", [
    (None, "missing_value"), ("", "missing_value"), ("  ", "missing_value"),
    ("-", "invalid_value"), ("...", "invalid_value"), ("X", "invalid_value"),
    ("p", "invalid_value"), ("51.2p", "invalid_value"), ("-1", "invalid_value"),
    ("100.1", "invalid_value"), ("1e1", "invalid_value"), ("NaN", "invalid_value"),
    ("Infinity", "invalid_value"), ("51,2", "invalid_value"), ("５０", "invalid_value"),
    (50.0, "invalid_value"), (True, "invalid_value"), ({}, "invalid_value"),
    ("0" * 33, "invalid_value"), ("https://invalid/?apiKey=private", "invalid_value"),
])
def test_missing_symbols_and_invalid_numbers_are_never_zero_filled(raw, code):
    rows = selected_rows(query())
    rows[0]["DT"] = raw
    with pytest.raises(KosisContractError) as caught:
        normalize_employment(rows, query(), CAPTURED)
    assert caught.value.code == code
    assert "private" not in str(caught.value) and "apiKey" not in str(caught.value)


@pytest.mark.parametrize("raw,value", [("0", "0"), ("0.0", "0.0"), ("100", "100"),
                                     (" 51.20 ", "51.20"), ("00.10", "0.10")])
def test_zero_is_valid_and_published_precision_is_not_rounded(raw, value):
    rows = selected_rows(query())
    rows[0]["DT"] = raw
    row = normalize_employment(rows, query(), CAPTURED).observations[0]
    assert row.value == value and row.raw_value == raw


def test_missing_duplicate_or_extra_cells_never_create_a_partial_result():
    request = query(entity="수도권 시·도", start_year=2022)
    rows = selected_rows(request)
    for payload, code in (
        (rows[1:], "incomplete_series"),
        (rows + [rows[0]], "duplicate_value"),
        (rows + [FIXTURE["rows"][0]], "invalid_response"),  # unrequested 2020
        (FIXTURE["rows"], "invalid_response"),  # unrequested regions and years
    ):
        with pytest.raises(KosisContractError) as caught:
            normalize_employment(payload, request, CAPTURED)
        assert caught.value.code == code


@pytest.mark.parametrize("payload,code", [
    ([], "no_data"), (None, "invalid_response"), ({"err": "30"}, "invalid_response"),
    ([None], "invalid_response"), ([{}] * 86, "invalid_response"),
])
def test_wrong_payload_shapes_fail_safely(payload, code):
    with pytest.raises(KosisContractError) as caught:
        normalize_employment(payload, query(), CAPTURED)
    assert caught.value.code == code


@pytest.mark.parametrize("when", [None, "2026-09-16", datetime(2026, 9, 16)])
def test_retrieval_time_requires_explicit_timezone(when):
    with pytest.raises(KosisContractError) as caught:
        normalize_employment(FIXTURE["rows"], query(), when)
    assert caught.value.code == "invalid_timestamp"


def test_retrieval_time_is_supplied_by_caller_never_replaced_with_the_fixture_date():
    fresh = datetime(2026, 9, 17, tzinfo=UTC)
    result = normalize_employment(FIXTURE["rows"], query(), fresh)
    assert result.retrieved_at == fresh
    assert result.observations[0].last_changed_at == date(2026, 6, 29)

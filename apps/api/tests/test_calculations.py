from decimal import ROUND_DOWN, localcontext

import pytest

from newsroom_agent.calculations import CalculationDataError, ValuePair, rank_changes


def pair(region, start, end, unit="%"):
    return ValuePair(region, start, end, unit, unit)


def test_difference_and_relative_change_produce_different_rankings():
    inputs = [pair("A", "40", "48"), pair("B", "50", "59"), pair("C", "30", "37")]
    difference, warnings = rank_changes(inputs, "%", "증감 폭")
    relative, _ = rank_changes(inputs, "%", "증감률")
    assert warnings == []
    assert [(row.region, row.change, row.rank) for row in difference] == [
        ("B", "9.00", 1),
        ("A", "8.00", 2),
        ("C", "7.00", 3),
    ]
    assert [(row.region, row.change, row.rank) for row in relative] == [
        ("C", "23.33", 1),
        ("A", "20.00", 2),
        ("B", "18.00", 3),
    ]


def test_decimal_subtraction_and_half_up_rounding():
    rows, _ = rank_changes(
        [
            pair("decimal", "0.1", "0.3"),
            pair("positive", "1", "2.005"),
            pair("negative", "2", "0.995"),
        ],
        "%",
        "증감 폭",
    )
    assert {row.region: row.change for row in rows} == {
        "decimal": "0.20",
        "positive": "1.01",
        "negative": "-1.01",
    }


def test_ranks_use_unrounded_values_and_competition_ties():
    inputs = [pair("B", "1", "2"), pair("C", "1", "1.5"), pair("A", "0", "1")]
    tied, _ = rank_changes(inputs, "%", "증감 폭")
    assert [(row.region, row.rank) for row in tied] == [("A", 1), ("B", 1), ("C", 3)]
    close, _ = rank_changes([pair("A", "1", "1.0011"), pair("B", "1", "1.0012")], "%", "증감 폭")
    assert [(row.region, row.change, row.rank) for row in close] == [
        ("B", "0.00", 1),
        ("A", "0.00", 2),
    ]


def test_result_does_not_depend_on_input_order_or_global_decimal_context():
    inputs = [pair("B", "30", "37"), pair("A", "30", "37"), pair("C", "50", "49.995")]
    expected = rank_changes(inputs, "%", "증감률")
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        actual = rank_changes(list(reversed(inputs)), "%", "증감률")
    assert actual == expected


def test_negative_changes_remain_negative_and_are_ranked_descending():
    rows, _ = rank_changes([pair("A", "10", "8"), pair("B", "10", "9")], "%", "증감 폭")
    assert [(row.region, row.change, row.rank) for row in rows] == [
        ("B", "-1.00", 1),
        ("A", "-2.00", 2),
    ]


def test_zero_baseline_blocks_relative_change_but_not_difference():
    inputs = [pair("A", "0", "5", "천 명"), pair("B", "10", "12", "천 명")]
    relative, warnings = rank_changes(inputs, "천 명", "증감률")
    assert relative[0].region == "B" and relative[0].rank == 1
    assert relative[1].status == "zero_baseline"
    assert relative[1].rank is None and relative[1].change is None
    assert warnings and "1개" in warnings[0]
    difference, _ = rank_changes(inputs, "천 명", "증감 폭")
    assert difference[0].region == "A" and difference[0].change == "5.00"


def test_missing_values_remain_visible_and_all_missing_has_no_winner():
    rows, warnings = rank_changes([pair("A", None, "5"), pair("B", "6", None)], "%", "증감 폭")
    assert len(rows) == 2
    assert all(
        row.rank is None and row.change is None and row.status == "missing_value" for row in rows
    )
    assert rows[0].start_value is None and rows[1].end_value is None
    assert "0개" in warnings[0]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "-1", "101", "not a number", ""])
def test_invalid_rate_values_stop_calculation_even_if_other_endpoint_is_missing(value):
    with pytest.raises(CalculationDataError):
        rank_changes([pair("A", None, value)], "%", "증감 폭")


def test_unit_mismatch_duplicate_regions_and_empty_dataset_are_rejected():
    cases = [
        [],
        [pair("A", "1", "2"), pair("A", "3", "4")],
        [ValuePair("A", "1", "2", "%", "천 명")],
    ]
    for inputs in cases:
        with pytest.raises(CalculationDataError):
            rank_changes(inputs, "%", "증감 폭")


def test_non_finite_overflow_and_unsupported_calculations_are_rejected():
    for unit, comparison, start in [
        ("원", "증감 폭", "1"),
        ("천 명", "순위", "1"),
        ("천 명", "증감 폭", "1e100"),
    ]:
        with pytest.raises(CalculationDataError):
            rank_changes([pair("A", start, "2", unit)], unit, comparison)


def test_precise_provider_values_do_not_become_false_ties_before_display_rounding():
    rows, _ = rank_changes([
        pair("A", "1", "2.00000000000000000000000000001"),
        pair("B", "1", "2.00000000000000000000000000002"),
    ], "%", "증감 폭", region_label="시도")
    assert [(row.region, row.rank, row.change) for row in rows] == [
        ("B", 1, "1.00"), ("A", 2, "1.00"),
    ]

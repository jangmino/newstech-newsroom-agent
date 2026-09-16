"""Deterministic arithmetic for mock observations, independent of providers and LLMs."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext

from newsroom_agent.models import CalculationRow


class CalculationDataError(ValueError):
    """The supplied dataset cannot safely be used for calculation."""


@dataclass(frozen=True)
class ValuePair:
    region: str
    start_value: str | None
    end_value: str | None
    start_unit: str
    end_unit: str


def _number(value: str | None, unit: str) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(value)
    except (DecimalException, ValueError, TypeError) as exc:
        raise CalculationDataError("자료에 숫자로 해석할 수 없는 값이 있습니다.") from exc
    if not number.is_finite() or number < 0 or (unit == "%" and number > 100):
        raise CalculationDataError("자료에 지표의 허용 범위를 벗어난 값이 있습니다.")
    return number


def rank_changes(
    pairs: list[ValuePair],
    input_unit: str,
    comparison: str,
) -> tuple[list[CalculationRow], list[str]]:
    if input_unit not in ("%", "천 명") or comparison not in ("증감 폭", "증감률"):
        raise CalculationDataError("지원하지 않는 단위나 비교 기준입니다.")
    if not pairs or len({pair.region for pair in pairs}) != len(pairs):
        raise CalculationDataError("자료에 지역이 없거나 중복되어 있습니다.")

    calculated: list[tuple[Decimal, CalculationRow]] = []
    unavailable: list[CalculationRow] = []
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_UP
        for pair in pairs:
            if pair.start_unit != input_unit or pair.end_unit != input_unit:
                raise CalculationDataError("시작·종료 값의 단위가 일치하지 않습니다.")
            start = _number(pair.start_value, input_unit)
            end = _number(pair.end_value, input_unit)
            row = CalculationRow(
                region=pair.region,
                start_value=pair.start_value,
                end_value=pair.end_value,
                status="calculated",
            )
            if start is None or end is None:
                row.status = "missing_value"
                row.reason = "시작 또는 종료 값이 없어 계산과 순위에서 제외했습니다."
                unavailable.append(row)
                continue
            if comparison == "증감률" and start == 0:
                row.status = "zero_baseline"
                row.reason = "시작 값이 0이므로 증감률을 계산할 수 없습니다."
                unavailable.append(row)
                continue
            try:
                change = end - start
                if comparison == "증감률":
                    change = change / start * 100
                rounded = change.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except DecimalException as exc:
                raise CalculationDataError("자료의 숫자 범위를 확인해야 합니다.") from exc
            row.change = format(abs(rounded) if rounded == 0 else rounded, ".2f")
            calculated.append((change, row))

    calculated.sort(key=lambda item: (item[0].copy_negate(), item[1].region))
    last_value = None
    last_rank = 0
    for position, (change, row) in enumerate(calculated, start=1):
        if change != last_value:
            last_rank = position
        row.rank = last_rank
        last_value = change
    unavailable.sort(key=lambda row: row.region)
    warnings = []
    if unavailable:
        warnings.append(
            f"계산 가능한 {len(calculated)}개 가상 지역만 순위를 매겼습니다. "
            "계산 불가 지역을 포함한 전체 순위로 해석하지 마세요."
            if calculated
            else "계산 가능한 가상 지역이 0개여서 순위를 매기지 않았습니다."
        )
        warnings.extend(f"{row.region}: {row.reason}" for row in unavailable)
    return [row for _, row in calculated] + unavailable, warnings

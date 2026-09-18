"""Period-aware decimal comparisons; no language-model arithmetic."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

from newsroom_agent.event_models import EventConditions
from newsroom_agent.research_models import ResearchFact


def calculate(raw: list[ResearchFact], c: EventConditions) -> tuple[list[ResearchFact], list[str]]:
    facts = [row.model_copy(deep=True) for row in raw]
    warnings = []
    groups = {}
    if c.tool == "disclosures":
        for i, fact in enumerate(facts, 1):
            fact.id = f"F{i}"
        return facts, warnings
    for row in raw:
        groups.setdefault((row.entity, row.metric), []).append(row)
    with localcontext() as ctx:
        ctx.prec = 64
        for (entity, metric), rows in groups.items():
            rows.sort(key=lambda r: r.period)
            stride = 12 if c.frequency == "월간" else 4 if c.frequency == "분기" else 1
            pairs = (
                [(rows[0], rows[-1])]
                if c.comparison_period == "시작·종료"
                else list(
                    zip(
                        rows,
                        rows[stride if c.comparison_period == "전년 동기" else 1 :],
                        strict=False,
                    )
                )
            )
            for start, end in pairs:
                before, after = Decimal(start.value), Decimal(end.value)
                if c.tool == "financials":
                    same_account = start.details.get("account_id") == end.details.get("account_id")
                    prior = end.details.get("prior_reported_value", "")
                    restated = (
                        c.frequency == "연간"
                        and int(end.period) - int(start.period) == 1
                        and prior.lstrip("-").isdigit()
                        and Decimal(prior) != before
                    )
                    if not same_account or restated:
                        warnings.append(
                            f"{entity} {metric} {start.period}→{end.period}: "
                            "계정 변경 또는 후속 보고서 비교값의 재작성을 발견해 증감을 "
                            "계산하지 않았습니다. 두 보고서 원문을 확인해 주세요."
                        )
                        continue
                if c.comparison == "증감률" and before <= 0:
                    warnings.append(
                        f"{entity} {metric} {start.period}: "
                        f"기준값이 0 이하라 증감률을 계산하지 않았습니다."
                    )
                    continue
                change = after - before
                growth = c.comparison == "증감률"
                value = change / before * 100 if growth else change
                unit = "%" if growth else "%p" if start.unit == "%" else start.unit
                facts.append(
                    ResearchFact(
                        id="pending",
                        entity=entity,
                        metric=f"{metric} {c.comparison}",
                        period=f"{start.period}→{end.period}",
                        value=format(
                            value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                            if growth
                            else value,
                            "f",
                        ),
                        unit=unit,
                        kind="change",
                        retrieved_at=end.retrieved_at,
                        source_urls=list(dict.fromkeys(start.source_urls + end.source_urls)),
                        formula="(종료값 − 시작값) ÷ 시작값 × 100" if growth else "종료값 − 시작값",
                        details={
                            "start_value": start.value,
                            "end_value": end.value,
                            "unrounded_change": str(value),
                            "direction": "실업률은 하락이 개선 방향"
                            if metric == "실업률"
                            else "증가 방향 기준",
                            "basis": f"{c.statement_basis} · {c.amount_basis}"
                            if c.tool == "financials"
                            else c.age_range,
                        },
                    )
                )
        ranking_groups = {}
        for row in facts:
            if c.tool == "employment" and row.kind == "change" and row.entity != "전국 집계":
                ranking_groups.setdefault((row.metric, row.period), []).append(row)
        for (metric, _), rows in ranking_groups.items():
            ordered = sorted(
                [Decimal(row.details["unrounded_change"]) for row in rows],
                reverse=not metric.startswith("실업률"),
            )
            if len(rows) > 1:
                for row in rows:
                    row.rank = ordered.index(Decimal(row.details["unrounded_change"])) + 1
    for i, fact in enumerate(facts, 1):
        fact.id = f"F{i}"
    return facts, warnings

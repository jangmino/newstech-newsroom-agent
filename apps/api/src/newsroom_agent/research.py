"""Single orchestrator for discover → propose → approve → retrieve → brief."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext

from newsroom_agent.planning import InvalidPlannerOutput
from newsroom_agent.providers.gemini_planner import GeminiQuestionPlanner
from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.kosis_employment import GROUPS, REGIONS, EmploymentQuery
from newsroom_agent.providers.opendart_research import OpenDartResearchClient, find_companies
from newsroom_agent.providers.planner import (
    PlannerDisabled,
    PlannerRateLimited,
    PlannerTimedOut,
    PlannerUnavailable,
)
from newsroom_agent.public_data_cache import PublicDataCache
from newsroom_agent.request_logging import record_error, request_id
from newsroom_agent.research_briefing import (
    BRIEF_INSTRUCTION,
    brief_payload,
    render_brief,
    scripted_brief,
)
from newsroom_agent.research_models import (
    BriefDraft,
    Company,
    ResearchBrief,
    ResearchConditions,
    ResearchExecuteRequest,
    ResearchExecutionResponse,
    ResearchFact,
    ResearchPlanRequest,
    ResearchPlanResponse,
)
from newsroom_agent.research_planning import (
    KOSIS_ENTITIES,
    KOSIS_YEARS,
    MOCK_COMPANIES,
    REASONS,
    RESEARCH_INSTRUCTION,
    ResearchIntent,
    available_metrics,
    condition_errors,
    interpretation_payload,
    mock_intent,
    parse_intent,
    propose_conditions,
)


class ResearchError(Exception):
    def __init__(self, message: str, field_errors: dict[str, str] | None = None):
        self.field_errors = field_errors or {}
        super().__init__(message)


class ResearchService:
    def __init__(
        self,
        *,
        dart: Callable[[], OpenDartResearchClient],
        kosis: Callable[[], KosisClient],
        model: Callable[[str, dict, bool], GeminiQuestionPlanner],
        require_source: Callable[[str], None],
        metadata_cache: PublicDataCache,
        data_cache: PublicDataCache | None,
    ):
        self.dart = dart
        self.kosis = kosis
        self.model = model
        self.require_source = require_source
        self.metadata_cache = metadata_cache
        self.data_cache = data_cache

    async def companies(self, mode: str) -> tuple[Company, ...]:
        if mode == "mock":
            return MOCK_COMPANIES
        self.require_source("opendart")
        result, _ = await self.metadata_cache.get(
            (("tool", "company-directory-v1"),), lambda: self.dart().companies()
        )
        return result

    async def years(self, company: Company, mode: str) -> list[int]:
        if mode == "mock":
            return KOSIS_YEARS
        result, _ = await self.metadata_cache.get(
            (("tool", "annual-reports-v1"), ("company", company.code)),
            lambda: self.dart().annual_years(company),
        )
        return result

    async def plan(self, request: ResearchPlanRequest) -> ResearchPlanResponse:
        model_name = None
        if request.interpretation_method == "gemini":
            planner = self.model(RESEARCH_INSTRUCTION, ResearchIntent.model_json_schema(), False)
            intent = parse_intent(
                await asyncio.to_thread(planner.interpret, interpretation_payload(request))
            )
            model_name = planner.model
        else:
            intent = mock_intent(request)
        companies = []
        years = []
        if intent.selected_source != "undetermined" and request.mode == "live":
            self.require_source(intent.selected_source)
        if intent.selected_source == "opendart" and intent.entity and not intent.unsupported:
            companies = find_companies(await self.companies(request.mode), intent.entity)
            if len(companies) == 1:
                years = await self.years(companies[0], request.mode)
        elif intent.selected_source == "kosis":
            years = KOSIS_YEARS
        conditions, proposals = propose_conditions(intent, years)
        if len(companies) == 1:
            conditions.entity, conditions.company_code = companies[0].name, companies[0].code
        errors = condition_errors(conditions, years)
        if intent.unsupported:
            errors["scope"] = intent.clarification or "현재 지원하는 조사 범위를 벗어났습니다."
        clarifications = list(
            dict.fromkeys(
                [*errors.values(), *([intent.clarification] if intent.clarification else [])]
            )
        )
        return ResearchPlanResponse(
            request_id=request_id(),
            question=request.question,
            conditions=conditions,
            selection_reason=REASONS[intent.selected_source],
            proposals=proposals,
            clarification_questions=clarifications,
            field_errors=errors,
            companies=companies,
            available_years=years,
            available_entities=KOSIS_ENTITIES if intent.selected_source == "kosis" else [],
            available_metrics=available_metrics(intent.selected_source),
            metadata_notice=(
                "가상 회사 목록·제공 기간입니다. 외부 API를 호출하지 않았습니다."
                if request.mode == "mock"
                else "회사·보고서 목록 또는 검증된 통계표 설명만 확인했습니다. "
                "수치 조회와 브리핑 작성은 조건 승인 후 실행합니다. "
                "보고서가 있어도 선택한 연결 재무 항목이 없을 수 있습니다."
            ),
            interpretation_method=request.interpretation_method,
            interpretation_model=model_name,
            data_mode=request.mode,
        )

    async def execute(self, request: ResearchExecuteRequest) -> ResearchExecutionResponse:
        # Model validation also requires StrictBool true. Keep this boundary explicit for callers.
        if request.approved is not True:
            raise ResearchError("조사 조건을 먼저 승인해 주세요.")
        c = request.conditions
        company = None
        years = KOSIS_YEARS
        if c.selected_source == "opendart":
            matches = [
                company
                for company in await self.companies(request.mode)
                if company.code == c.company_code and company.name == c.entity
            ]
            if len(matches) != 1:
                raise ResearchError(
                    "회사명이 공식 코드와 맞지 않습니다. 계획을 다시 확인해 주세요."
                )
            company = matches[0]
            years = await self.years(company, request.mode)
        errors = condition_errors(c, years)
        if errors:
            raise ResearchError("조사 조건을 확인해 주세요.", errors)
        if request.mode == "live":
            self.require_source(c.selected_source)
        cache = None

        async def fetch():
            if request.mode == "mock":
                return mock_facts(c)
            if company:
                return await self.dart().financials(
                    company, list(range(c.start_year, c.end_year + 1)), c.metrics
                )
            query = EmploymentQuery(
                entity=c.entity,
                metric="고용률",
                age_range=c.age_range,
                start_year=c.start_year,
                end_year=c.end_year,
                allow_single_region=True,
            )
            series = await self.kosis().fetch_employment(query)
            return [
                ResearchFact(
                    id="pending",
                    entity=row.region_name,
                    metric="고용률",
                    period=str(row.year),
                    value=row.value,
                    unit="%",
                    kind="observation",
                    source_urls=[series.source_url],
                    retrieved_at=series.retrieved_at.isoformat(),
                    details={
                        **query.parameters,
                        "region_code": row.region_code,
                        "age_range": c.age_range,
                        "last_changed_at": row.last_changed_at.isoformat(),
                        "raw_value": row.raw_value,
                    },
                )
                for row in series.observations
            ]

        if request.mode == "live" and self.data_cache:
            key = (
                ("tool", "research-values-v1"),
                ("source", c.selected_source),
                ("entity", c.entity),
                ("company", c.company_code),
                ("metrics", ",".join(sorted(c.metrics))),
                ("start", str(c.start_year)),
                ("end", str(c.end_year)),
                ("age", c.age_range),
                ("basis", c.statement_basis),
            )
            facts, cache = await self.data_cache.get(key, fetch)
        else:
            facts = await fetch()
        facts, warnings = calculated_facts(facts, c)
        caveats = [
            *(
                ["모든 숫자는 직접 만든 가상 자료입니다. 실제 취재 근거로 사용할 수 없습니다."]
                if request.mode == "mock"
                else []
            ),
            "자료 조회와 AI 초안 작성은 사실 검증 완료나 기사 사용 승인이 아닙니다.",
            "관찰된 변화만으로 원인·정책 효과·기업이나 지역의 상황 전반을 단정할 수 없습니다.",
            *(
                [
                    "연결 기준의 각 사업보고서 당기값입니다. "
                    "정정과 최신 보고서의 재작성 값은 다를 수 있습니다.",
                    "금액은 원 단위입니다. 공시 원문의 백만원 표기와 구분해 대조해 주세요.",
                ]
                if company
                else [
                    "시도별 고용률을 평균내어 전국·권역 고용률을 만들지 않습니다.",
                    "표본오차·공표 반올림·자료 개정·지역 경계와 연령 정의를 확인해 주세요.",
                ]
            ),
            *warnings,
        ]
        brief = ResearchBrief(
            status="complete",
            generation_method="scripted",
            content=scripted_brief(facts, request.mode),
        )
        if request.briefing_method == "gemini":
            composer = self.model(BRIEF_INSTRUCTION, BriefDraft.model_json_schema(), True)
            try:
                raw = await asyncio.to_thread(
                    composer.interpret,
                    brief_payload(request.question, c, facts, caveats, request.mode),
                )
                brief = ResearchBrief(
                    status="complete",
                    generation_method="gemini",
                    model=composer.model,
                    content=render_brief(raw, facts),
                )
            except (PlannerUnavailable, InvalidPlannerOutput) as exc:
                code, message = {
                    PlannerDisabled: (
                        "planner_disabled",
                        "현재 Gemini 브리핑 작성이 꺼져 있습니다. "
                        "운영자에게 브리핑 설정 확인을 요청해 주세요.",
                    ),
                    PlannerRateLimited: (
                        "planner_rate_limited",
                        "Gemini 사용 한도에 도달했습니다. 잠시 후 다시 승인해 주세요.",
                    ),
                    PlannerTimedOut: ("planner_timeout", "Gemini 브리핑 응답 시간이 초과됐습니다."),
                    InvalidPlannerOutput: (
                        "invalid_planner_output",
                        "Gemini 브리핑의 형식이나 근거 참조를 확인하지 못했습니다.",
                    ),
                }.get(type(exc), ("planner_unavailable", "Gemini 브리핑을 작성하지 못했습니다."))
                record_error(code)
                brief = ResearchBrief(
                    status="failed",
                    generation_method="gemini",
                    model=composer.model,
                    error=message + " 조회한 자료는 아래에 남아 있습니다. "
                    "조건을 다시 승인해 재시도하거나 모의 문장 작성을 선택해 주세요.",
                )
        return ResearchExecutionResponse(
            request_id=request_id(),
            question=request.question,
            conditions=c.model_copy(deep=True),
            data_mode=request.mode,
            source_name=(
                "OpenDART · 금융감독원 전자공시" if company else "KOSIS · 경제활동인구조사"
            ),
            table_or_report=(
                f"{c.entity} 연간 연결 재무제표"
                if company
                else "행정구역(시도)/연령별 경제활동인구 · 15~29세 고용률"
            ),
            facts=facts,
            caveats=caveats,
            cache=cache,
            brief=brief,
        )


def mock_facts(c: ResearchConditions) -> list[ResearchFact]:
    now = datetime.now(UTC).isoformat()
    if c.selected_source == "opendart":
        entities = [c.entity]
    else:
        entities = (
            [REGIONS[code] for code in GROUPS[c.entity]] if c.entity in GROUPS else [c.entity]
        )
    facts = []
    for index, entity in enumerate(entities):
        for year in range(c.start_year, c.end_year + 1):
            for metric in c.metrics:
                value = (
                    100_000_000_000 + (year - 2020) * 13_000_000_000
                    if metric == "매출액"
                    else (-4_000_000_000 if year == 2023 else (year - 2019) * 2_000_000_000)
                    if metric == "영업이익"
                    else Decimal("40") + index + Decimal(year - 2020) * Decimal("0.7")
                )
                facts.append(
                    ResearchFact(
                        id="pending",
                        entity=entity,
                        metric=metric,
                        period=str(year),
                        value=str(value),
                        unit="원" if c.selected_source == "opendart" else "%",
                        kind="observation",
                        retrieved_at=now,
                        details={"origin": "synthetic", "note": "직접 만든 가상 수치"},
                    )
                )
    return facts


def calculated_facts(
    raw: list[ResearchFact], c: ResearchConditions
) -> tuple[list[ResearchFact], list[str]]:
    facts = [f.model_copy(deep=True) for f in raw]
    warnings = []
    grouped = {}
    for fact in raw:
        grouped.setdefault((fact.entity, fact.metric), []).append(fact)
    with localcontext() as context:
        context.prec = 64
        for (entity, metric), rows in grouped.items():
            rows.sort(key=lambda f: int(f.period))
            pairs = (
                list(zip(rows, rows[1:], strict=False))
                if c.selected_source == "opendart"
                else [(rows[0], rows[-1])]
            )
            if len(rows) > 2 and c.selected_source == "opendart":
                pairs.append((rows[0], rows[-1]))
            for start, end in pairs:
                before, after = Decimal(start.value), Decimal(end.value)
                difference = after - before
                if c.comparison == "증감률" and before <= 0:
                    warnings.append(
                        f"{entity} {metric} {start.period}→{end.period}: 기준값이 0 이하라 "
                        "증감률을 계산하지 않았습니다. 원자료 또는 증감 폭을 확인해 주세요."
                    )
                    continue
                growth = c.comparison == "증감률"
                value = (
                    (difference / before * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if growth
                    else difference
                )
                unit = "%" if growth else "%p" if start.unit == "%" else "원"
                facts.append(
                    ResearchFact(
                        id="pending",
                        entity=entity,
                        metric=f"{metric} {c.comparison}",
                        period=f"{start.period}→{end.period}",
                        value=format(value, "f"),
                        unit=unit,
                        kind="change",
                        source_urls=list(dict.fromkeys(start.source_urls + end.source_urls)),
                        retrieved_at=end.retrieved_at,
                        formula="(종료값 − 시작값) ÷ 시작값 × 100" if growth else "종료값 − 시작값",
                        details={
                            "start_value": start.value,
                            "end_value": end.value,
                            "rounding": "증감률만 소수 둘째 자리 반올림",
                        },
                    )
                )
    if c.selected_source == "kosis":
        changes = [fact for fact in facts if fact.kind == "change"]
        with localcontext() as context:
            context.prec = 64

            def raw_change(fact):
                before = Decimal(fact.details["start_value"])
                difference = Decimal(fact.details["end_value"]) - before
                return difference / before if c.comparison == "증감률" else difference

            ordered = sorted(changes, key=raw_change, reverse=True)
            for fact in changes:
                fact.rank = next(
                    i + 1 for i, row in enumerate(ordered) if raw_change(row) == raw_change(fact)
                )
    for index, fact in enumerate(facts, 1):
        fact.id = f"F{index}"
    return facts, warnings

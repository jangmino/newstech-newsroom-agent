"""Offline analysis/contract regressions; replay official extracts, never live APIs."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from newsroom_agent.event_catalog import validate_conditions
from newsroom_agent.event_models import (
    EventConditions,
    EventExecuteRequest,
    EventPlanRequest,
    EventResult,
)
from newsroom_agent.event_service import EventService
from newsroom_agent.investigation_calculations import analyze, checked_rows
from newsroom_agent.investigation_catalog import SCENARIOS, archive, catalog
from newsroom_agent.providers.investigation import fetch
from newsroom_agent.providers.planner import PlannerUnavailable
from newsroom_agent.research import ResearchError


def conditions(tool, **changes):
    s = SCENARIOS[tool]
    c = dict(
        tool=tool,
        **{k: s[k] for k in ["entities", "metrics", "start", "end", "frequency"]},
        comparison="심층 비교",
        comparison_period="조사 계획",
        age_range="20-34세",
    )
    return EventConditions(**(c | changes))


@pytest.mark.parametrize("tool", SCENARIOS)
def test_official_archive_replay_has_reproducible_tables_and_citations(tool):
    c = conditions(tool)
    assert not validate_conditions(c)
    result = analyze(c, archive(tool))
    ids = {f.id for f in result.facts}
    assert len(ids) == len(result.facts) and result.analysis.focus_ids
    assert set(result.analysis.focus_ids) <= ids
    for t in result.analysis.tables:
        assert all(len(row) == len(t.columns) for row in t.rows)
        assert set(t.evidence_ids) <= ids and t.rows
    assert all(f.source_urls and f.retrieved_at and f.formula for f in result.facts)
    assert {v["tool"] for v in catalog()} == set(SCENARIOS)


def test_births_month_on_month_is_not_year_on_year_and_gap_breaks_streak():
    c = conditions("births", start="2025-01", end="2026-07", entities=["전국"])
    material = deepcopy(archive("births"))
    for ds in material["datasets"]:
        for r in ds["rows"]:
            if r["C1"] == "00" and r["PRD_DE"] == "202606":
                r["DT"] = "-"
    result = analyze(c, material)
    current = next(f for f in result.facts if f.metric == "현재 연속 증가")
    assert current.value == "1"
    rate = next(f for f in result.facts if f.metric == "전년 동월 대비 증가율")
    assert "전년 동월" in rate.formula and rate.details["previous_year"]


def test_unknown_age_and_period_never_silently_substitute():
    assert "age_range" in validate_conditions(conditions("migration", age_range="15-29세"))
    assert "period" in validate_conditions(conditions("prices", start="2024-09"))
    assert "entities" in validate_conditions(conditions("business_mix", entities=["삼성전자"]))
    assert "basis" in validate_conditions(conditions("business_mix", statement_basis="별도"))


def test_migration_separates_destinations_from_net_and_handles_boundary():
    r = analyze(conditions("migration"), archive("migration"))
    assert any("군위군" in v for v in r.caveats)
    assert not any(f.entity == "경상북도" and f.metric == "연평균 순이동률" for f in r.facts)
    assert any(f.entity.startswith("경상북도 → ") for f in r.facts)
    assert any(f.entity == "의성군" and f.metric == "연평균 순이동률" for f in r.facts)
    for f in r.facts:
        if f.metric == "연평균 순이동률":
            assert "기간 합계 주민등록연앙인구" in f.formula


def test_migration_does_not_rank_a_missing_denominator():
    material = deepcopy(archive("migration"))
    pop = next(d for d in material["datasets"] if d["parameters"]["tblId"] == "DT_1B040M5_1")
    pop["rows"] = [r for r in pop["rows"] if r["C1_NM"] != "의성군"]
    r = analyze(conditions("migration"), material)
    assert any("의성군" in v and "분모" in v for v in r.caveats)
    assert not any(f.entity == "의성군" and f.unit == "%" for f in r.facts)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "literal_location", [None, "summary", "limitations", "follow_up_questions"],
)
async def test_migration_brief_rejects_unslotted_age_numbers(literal_location):
    draft = {
        "summary": {
            "text": "승인한 청년 연령의 {{F1.metric}}을 확인합니다.", "evidence_ids": ["F1"],
        },
        "findings": [{"text": "{{F1.entity}}: {{F1.value}} {{F1.unit}}", "evidence_ids": ["F1"]}],
        "limitations": ["세부 연령대별 차이는 이 결과만으로 알 수 없습니다."],
        "follow_up_questions": ["청년층의 이동 이유를 추가 취재할 수 있을까요?"],
    }
    if literal_location == "summary":
        draft["summary"]["text"] = "20~34세의 이동을 확인합니다."
    elif literal_location:
        draft[literal_location] = ["20~24세 등 세부 연령대 확인이 필요합니다."]
    composer = SimpleNamespace(model="offline", interpret=Mock(return_value=json.dumps(draft)))
    research = SimpleNamespace(model=Mock(return_value=composer), data_cache=None)
    c = conditions("migration")
    result = await EventService(research).execute(EventExecuteRequest(
        question=SCENARIOS["migration"]["question"], conditions=c, approved=True, mode="archive",
    ))
    assert result.conditions.age_range == "20-34세"
    assert result.facts and result.analysis
    assert result.brief.status == ("failed" if literal_location else "complete")
    assert composer.interpret.call_count == 1


def test_cpi_leaf_weights_and_official_total_reconciliation():
    from decimal import Decimal

    items = archive("price-weights")["items"]
    assert len(items) == 458 and sum(Decimal(v["WGT_CO"]) for v in items) == 1000
    r = analyze(conditions("prices"), archive("prices"))
    assert len(r.analysis.tables[0].rows) == len(r.analysis.tables[1].rows) == 20
    assert any(f.metric == "근사 기여도 합계와 총지수 상승률의 차이" for f in r.facts)
    assert not any(f.entity == "0 총지수" for f in r.facts)
    material = deepcopy(archive("prices"))
    material["datasets"][0]["rows"] = [
        v for v in material["datasets"][0]["rows"] if v["C2"] != "A01101"
    ]
    with pytest.raises(ResearchError, match="일부"):
        analyze(conditions("prices"), material)


def test_compensation_uses_report_total_not_gender_mean_or_highest_paid():
    r = analyze(conditions("compensation"), archive("compensation"))
    avgs = {f.entity: f.value for f in r.facts if f.metric == "공식 직원 합계 평균급여"}
    assert avgs == {"NAVER": "146000000", "카카오": "109000000"}
    assert not any("한성숙" in f.metric or "홍은택" in f.metric for f in r.facts)
    assert any(f.metric == "대표이사 최수연 보수총액" and f.value == "3029000000" for f in r.facts)
    assert any("미행사" in warning for warning in r.caveats)


def test_business_mix_uses_corrected_table_and_same_report_prior():
    material = archive("business_mix")
    kakao = next(r for r in material["records"] if r["company"] == "카카오" and r["year"] == "2021")
    assert kakao["total_million"] == "5910513"  # correction sheet also contains superseded 6136669
    r = analyze(conditions("business_mix"), material)
    f = next(
        f
        for f in r.facts
        if f.entity == "NAVER" and f.period == "2022" and f.metric == "서치플랫폼 매출 증가액"
    )
    assert f.value == "260129" and f.details["prior"] == "3307835"
    # Previous year's reported amount differs; never subtract it silently.
    old = next(
        f
        for f in r.facts
        if f.entity == "NAVER" and f.period == "2021" and f.metric == "서치플랫폼 매출"
    )
    assert old.value == "3290489"
    assert any("정정" in v for v in r.caveats)


@pytest.mark.parametrize("alteration", ["duplicate", "table", "dimension", "period"])
def test_provider_mismatch_is_rejected(alteration):
    ds = deepcopy(archive("births")["datasets"][0])
    if alteration == "duplicate":
        ds["rows"].append(ds["rows"][0])
    if alteration == "table":
        ds["rows"][0]["TBL_ID"] = "another"
    if alteration == "dimension":
        ds["rows"][0]["C2"] = "20"
    if alteration == "period":
        ds["rows"][0]["PRD_DE"] = "209901"
    with pytest.raises(ResearchError):
        checked_rows(ds)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", SCENARIOS)
async def test_plan_is_metadata_only_and_archive_execution_preserves_approved_conditions(tool):
    c = conditions(tool)
    planner = SimpleNamespace(
        model="offline", interpret=Mock(return_value=json.dumps({"conditions": c.model_dump()}))
    )
    composer = SimpleNamespace(model="offline", interpret=Mock(side_effect=PlannerUnavailable()))
    research = SimpleNamespace(
        model=Mock(side_effect=[planner, composer]),
        data_cache=None,
        require_source=Mock(side_effect=AssertionError("no live call")),
        companies=AsyncMock(side_effect=AssertionError("no discovery")),
        kosis=Mock(side_effect=AssertionError("no data before approval")),
    )
    svc = EventService(research)
    plan = await svc.plan(EventPlanRequest(question=SCENARIOS[tool]["question"]))
    assert plan.status == "ready" and "facts" not in plan.model_dump()
    research.kosis.assert_not_called()
    result = await svc.execute(
        EventExecuteRequest(
            question=plan.question, conditions=plan.conditions, approved=True, mode="archive"
        )
    )
    assert result.conditions == plan.conditions and result.data_mode == "archive"
    assert result.facts and result.analysis and result.brief.status == "failed"
    assert any("재분석" in t.tool for t in result.trace)
    payload = json.loads(composer.interpret.call_args.args[0])
    assert len(payload["facts"]) <= 40 and payload["data_mode"] == "archive"


@pytest.mark.asyncio
async def test_archive_requires_explicit_approval_and_enabled_source_mode():
    with pytest.raises(ValidationError):
        EventExecuteRequest(
            question="원문 확인", conditions=conditions("births"), approved=False, mode="archive"
        )
    svc = EventService(SimpleNamespace(), snapshots_enabled=False)
    with pytest.raises(ResearchError, match="꺼져"):
        await svc.execute(
            EventExecuteRequest(
                question="원문 확인", conditions=conditions("births"), approved=True, mode="archive"
            )
        )
    with pytest.raises(ResearchError, match="공식 저장"):
        await fetch(conditions("business_mix"), SimpleNamespace(), "live")


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,expected", [("births", 3), ("migration", 3), ("prices", 2)])
async def test_live_queries_are_bounded_and_replay_same_official_values(tool, expected):
    material = archive(tool)

    async def respond(params):
        result = []
        for d in material["datasets"]:
            if d["parameters"]["tblId"] != params["tblId"]:
                continue
            for row in d["rows"]:
                if not params["startPrdDe"] <= row["PRD_DE"] <= params["endPrdDe"]:
                    continue
                if all(
                    params.get(f"objL{i}", "ALL") == "ALL"
                    or row.get(f"C{i}") in params[f"objL{i}"].split("+")
                    for i in range(1, 5)
                ):
                    result.append(row)
        return result

    client = SimpleNamespace(fetch_parameters=AsyncMock(side_effect=respond))
    research = SimpleNamespace(require_source=Mock(), kosis=Mock(return_value=client))
    c = conditions(tool)
    live = await fetch(c, research, "live")
    stored = analyze(c, material)
    assert [(f.entity, f.metric, f.value) for f in live.facts] == [
        (f.entity, f.metric, f.value) for f in stored.facts
    ]
    assert client.fetch_parameters.call_count == expected


def test_caveats_do_not_claim_missing_coverage_when_all_values_are_present():
    for tool in ["prices", "compensation", "business_mix"]:
        r = analyze(conditions(tool), archive(tool))
        assert r.caveats and r.coverage == "complete"


def test_missing_destination_is_partial_and_not_invented():
    material = deepcopy(archive("migration"))
    ds = next(d for d in material["datasets"] if d["parameters"]["tblId"] == "DT_1B26003")
    ds["rows"] = [r for r in ds["rows"] if r["C2_NM"] != "서울특별시"]
    r = analyze(conditions("migration"), material)
    assert r.coverage == "partial"
    assert any("전체 목적지 순위가 아닙니다" in s for s in r.caveats)
    assert not any(f.entity == "경상북도 → 서울특별시" for f in r.facts)


@pytest.mark.asyncio
async def test_thirty_approved_requests_share_five_calculations_but_not_briefings(monkeypatch):
    import asyncio

    from newsroom_agent.public_data_cache import PublicDataCache

    loader = AsyncMock(side_effect=fetch)
    monkeypatch.setattr("newsroom_agent.providers.investigation.fetch", loader)
    model = SimpleNamespace(model="offline", interpret=Mock(side_effect=PlannerUnavailable()))
    cache = PublicDataCache()
    research = SimpleNamespace(
        data_cache=cache,
        model=Mock(return_value=model),
        require_source=Mock(side_effect=AssertionError("no HTTP")),
    )
    service = EventService(research)
    requests = [
        EventExecuteRequest(
            question=SCENARIOS[t]["question"],
            conditions=conditions(t),
            approved=True,
            mode="archive",
        )
        for t in SCENARIOS
        for _ in range(6)
    ]
    try:
        results = await asyncio.gather(*(service.execute(r) for r in requests))
        assert len(results) == 30 and loader.call_count == 5
        assert model.interpret.call_count == 30
        assert sum(r.cache.status == "miss" for r in results) == 5
        assert all(r.facts and r.brief.status == "failed" for r in results)
        assert all(r.conditions == q.conditions for r, q in zip(results, requests, strict=True))
        # Caller mutation cannot change shared evidence or the next approved result.
        results[0].facts[0].value = "tampered"
        again = await service.execute(requests[0])
        assert again.facts[0].value != "tampered"
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_approval_and_source_selection_are_checked_before_archive_or_live_calls():
    with pytest.raises(ValidationError):
        EventExecuteRequest(
            question="조사 질문", conditions=conditions("births"), approved=False, mode="archive"
        )
    research = SimpleNamespace(data_cache=None)
    request = EventExecuteRequest(
        question="조사 질문", conditions=conditions("business_mix"), approved=True, mode="archive"
    )
    with pytest.raises(ResearchError, match="꺼져"):
        await EventService(research, snapshots_enabled=False).execute(request)
    with pytest.raises(ResearchError, match="다시 승인"):
        await EventService(research).execute(request.model_copy(update={"mode": "live"}))


@pytest.mark.parametrize("tool", list(SCENARIOS))
def test_emergency_snapshots_equal_official_archive_calculation_and_keep_generation_time(tool):
    from newsroom_agent.event_service import load_snapshots

    saved = load_snapshots()["investigation-" + tool]
    result = EventResult.model_validate(saved["result"])
    expected = analyze(result.conditions, archive(tool))
    assert result.facts == expected.facts and result.analysis == expected.analysis
    assert result.brief.status == "complete" and result.data_mode == "snapshot"
    assert result.generated_at == saved["validation"]["prepared_at"]
    assert saved["general"]["conditions"] == result.conditions.model_dump()
    assert saved["general"]["question"] == result.question

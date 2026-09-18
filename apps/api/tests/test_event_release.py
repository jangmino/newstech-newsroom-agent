"""Event behavior uses stored public fixtures and mocked transports, never live APIs."""

import io
import json
import zipfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from newsroom_agent import main
from newsroom_agent.event_calculations import calculate
from newsroom_agent.event_catalog import validate_conditions
from newsroom_agent.event_models import EventConditions, EventExecuteRequest, EventPlanRequest
from newsroom_agent.event_service import GENERAL_INSTRUCTION, EventService
from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.kosis_employment import KosisError
from newsroom_agent.providers.kosis_event import normalize, parameters
from newsroom_agent.providers.opendart_event import (
    EventDartClient,
    document_excerpt,
    normalize_finance,
)
from newsroom_agent.providers.opendart_financials import OpenDartError
from newsroom_agent.providers.planner import PlannerUnavailable
from newsroom_agent.public_data_cache import PublicDataCache
from newsroom_agent.research import ResearchError, ResearchService
from newsroom_agent.research_models import Company, ResearchFact

FIXTURES = Path(__file__).parent / "fixtures" / "event"
NOW = datetime(2026, 9, 18, tzinfo=UTC)
HYUNDAI = Company(name="현대자동차", code="00164742", stock_code="005380")


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def conditions(**changes):
    return EventConditions(
        tool="employment",
        entities=["서울특별시", "전국 집계"],
        metrics=["고용률"],
        start="2021",
        end="2025",
        comparison_period="시작·종료",
        **changes,
    )


def finance(**changes):
    base = dict(
        tool="financials",
        entities=[HYUNDAI.name],
        company_codes=[HYUNDAI.code],
        metrics=["매출액", "영업이익", "당기순이익"],
        start="2024",
        end="2025",
    )
    return EventConditions(**(base | changes))


@pytest.mark.parametrize("changed_account", [False, True])
def test_financial_restatement_or_changed_account_blocks_comparison(changed_account):
    rows = normalize_finance(
        fixture("hyundai-2025-11011-CFS")["payload"],
        HYUNDAI,
        2025,
        "11011",
        "CFS",
        "당기",
        ["매출액"],
        NOW.isoformat(),
    )
    end = rows[0]
    start = end.model_copy(deep=True)
    start.period = "2024"
    start.value = end.details["prior_reported_value"]
    if changed_account:
        start.details["account_id"] = "different_account"
    else:
        start.value = str(int(start.value) + 1)
    result, warnings = calculate([start, end], finance(metrics=["매출액"]))
    assert len(result) == 2 and all(r.kind == "observation" for r in result)
    assert any("재작성" in warning for warning in warnings)


@pytest.mark.parametrize("approved", [False, 1, "true", None])
def test_event_requires_strict_approval(approved):
    with pytest.raises(ValidationError):
        EventExecuteRequest(question="현대차 실적", conditions=finance(), approved=approved)


def test_event_rejects_mock_and_extraneous_provider_codes():
    with pytest.raises(ValidationError):
        EventExecuteRequest(
            question="현대차 실적", conditions=finance(), approved=True, mode="mock"
        )
    with pytest.raises(ValidationError):
        EventConditions(tool="employment", apiKey="not-a-real-key")


@pytest.mark.parametrize(
    "patch,field",
    [
        ({"frequency": "월간", "start": "202508", "end": "202608"}, "frequency"),
        ({"age_range": "15-34세"}, "age_range"),
        ({"metrics": ["실업률"]}, "metrics"),
        ({"entities": ["서울특별시", "서울특별시"]}, "entities"),
        ({"start": "2026", "end": "2027"}, "period"),
    ],
)
def test_unsupported_combinations_not_substituted(patch, field):
    c = conditions().model_copy(update=patch)
    assert field in validate_conditions(c)
    assert all(getattr(c, k) == v for k, v in patch.items())


def test_national_monthly_and_regional_monthly_count_have_distinct_tables():
    c = conditions().model_copy(
        update={
            "entities": ["전국 집계"],
            "metrics": ["실업률"],
            "frequency": "월간",
            "start": "2025-08",
            "end": "2026-08",
            "comparison_period": "전년 동기",
        }
    )
    assert not validate_conditions(c)
    assert parameters(c, "실업률")["tblId"] == "DT_1DA7002S"
    c = c.model_copy(update={"entities": ["서울특별시", "전국 집계"], "metrics": ["취업자 수"]})
    assert not validate_conditions(c)
    assert parameters(c, "취업자 수")["tblId"] == "DT_1DA7031S"
    assert "comparison_period" in validate_conditions(
        finance(frequency="분기", start="2025-Q1", end="2026-Q2", amount_basis="누적")
    )


def test_official_national_values_used_without_regional_average():
    data = fixture("DT_1DA7015S-Y-values")
    c = conditions()
    facts = normalize(data["payload"], c, "고용률", NOW)
    assert len(facts) == 10
    national = next(f for f in facts if f.entity == "전국 집계" and f.period == "2021")
    assert national.value == "44.2"
    result, _ = calculate(facts, c)
    national_change = next(f for f in result if f.entity == "전국 집계" and f.kind == "change")
    assert national_change.rank is None
    assert national_change.unit == "%p"


@pytest.mark.parametrize(
    "field,value",
    [
        ("UNIT_NM", "명"),
        ("C2", "20"),
        ("ITM_ID", "T80"),
        ("PRD_SE", "M"),
        ("DT", "-"),
        ("DT", "101"),
        ("TBL_ID", "fake"),
    ],
)
def test_wrong_kosis_dimensions_fail_closed(field, value):
    rows = fixture("DT_1DA7015S-Y-values")["payload"]
    rows[0][field] = value
    with pytest.raises(KosisError):
        normalize(rows, conditions(), "고용률", NOW)


def test_missing_duplicate_kosis_cells_rejected():
    rows = fixture("DT_1DA7015S-Y-values")["payload"]
    for data in (rows[:-1], rows[:-1] + [rows[0]]):
        with pytest.raises(KosisError):
            normalize(data, conditions(), "고용률", NOW)


def test_monthly_yoy_preserves_thousand_people():
    c = conditions().model_copy(
        update={
            "metrics": ["취업자 수"],
            "frequency": "월간",
            "start": "2025-08",
            "end": "2026-08",
            "comparison_period": "전년 동기",
        }
    )
    facts = normalize(fixture("DT_1DA7031S-M-values")["payload"], c, "취업자 수", NOW)
    result, _ = calculate(facts, c)
    changes = [f for f in result if f.kind == "change"]
    assert len(changes) == 2
    assert all(f.unit == "천명" and f.period == "202508→202608" for f in changes)


def test_finance_profit_duplicate_is_cis_and_current_cumulative():
    payload = fixture("hyundai-2026-11012-CFS")["payload"]
    current = normalize_finance(
        payload, HYUNDAI, 2026, "11012", "CFS", "당기", ["당기순이익"], NOW.isoformat()
    )[0]
    cumulative = normalize_finance(
        payload, HYUNDAI, 2026, "11012", "CFS", "누적", ["당기순이익"], NOW.isoformat()
    )[0]
    assert current.value == "2887962000000"
    assert cumulative.value == "5472888000000"
    assert current.details["statement"] == "IS"
    assert "20260814003521" in current.source_urls[0]


def test_disagreeing_is_cis_profit_or_wrong_identity_rejected():
    raw = fixture("hyundai-2026-11012-CFS")["payload"]
    bad = deepcopy(raw)
    next(
        r for r in bad["list"] if r["sj_div"] == "CIS" and r["account_id"] == "ifrs-full_ProfitLoss"
    )["thstrm_amount"] = "1"
    with pytest.raises(OpenDartError):
        normalize_finance(
            bad, HYUNDAI, 2026, "11012", "CFS", "당기", ["당기순이익"], NOW.isoformat()
        )
    with pytest.raises(OpenDartError):
        normalize_finance(
            raw, HYUNDAI, 2025, "11012", "CFS", "당기", ["당기순이익"], NOW.isoformat()
        )


def test_negative_base_growth_not_invented():
    rows = [
        ResearchFact(
            id="pending",
            entity="기업",
            metric="영업이익",
            period=y,
            value=v,
            unit="원",
            kind="observation",
            retrieved_at=NOW.isoformat(),
        )
        for y, v in [("2024", "-10"), ("2025", "10")]
    ]
    result, warnings = calculate(rows, finance(comparison="증감률"))
    assert len(result) == 2 and "0 이하" in warnings[0]


def zip_document(text):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("report.xml", text)
    return out.getvalue()


def test_document_is_text_not_executable_markup_and_entities_rejected():
    assert document_excerpt(zip_document("<p>공식 내용</p><script>bad()</script>")) == "공식 내용"
    with pytest.raises(OpenDartError):
        document_excerpt(zip_document('<!ENTITY x SYSTEM "file:///test"><p>bad</p>'))
    with pytest.raises(OpenDartError):
        document_excerpt(b"not a zip")


@pytest.mark.asyncio
async def test_disclosure_dedup_corrections_body_and_empty_are_distinct():
    naver = Company(name="NAVER", code="00266961", stock_code="035420")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("list.json"):
            p = fixture("NAVER-list")["payload"]
            p["list"].append(p["list"][0])
            p["list"][0]["rm"] = "정"
            return httpx.Response(200, json=p)
        return httpx.Response(200, content=zip_document("<p>특정증권 소유상황 본문</p>"))

    client = EventDartClient(
        "fixture", enabled=True, transport=httpx.MockTransport(handler), clock=lambda: NOW
    )
    c = EventConditions(
        tool="disclosures",
        entities=["NAVER"],
        company_codes=[naver.code],
        metrics=["지분"],
        start="2026-08-18",
        end="2026-09-18",
        comparison="접수일순",
    )
    result = await client.event_disclosures([naver], c)
    assert len(result.facts) == 4
    assert any(f.details["status"] == "정정 확인 필요" for f in result.facts)
    assert all("공식 본문 발췌" in f.details for f in result.facts)
    assert result.coverage == "complete"
    c.metrics = ["소송"]
    empty = await client.event_disclosures([naver], c)
    assert empty.coverage == "empty" and not empty.facts
    assert "0건" in empty.caveats[0]


@pytest.mark.asyncio
async def test_finance_transport_selects_ofs_and_report_codes():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        report = request.url.params["reprt_code"]
        return httpx.Response(200, json=fixture(f"hyundai-2026-{report}-CFS")["payload"])

    client = EventDartClient(
        "fixture", enabled=True, transport=httpx.MockTransport(handler), clock=lambda: NOW
    )
    result = await client.event_financials(
        HYUNDAI, finance(frequency="분기", start="2026-Q1", end="2026-Q2", statement_basis="별도")
    )
    assert all(p["fs_div"] == "OFS" for p in seen)
    assert [p["reprt_code"] for p in seen] == ["11013", "11012"]
    assert {f.period for f in result.facts} == {"2026-Q1", "2026-Q2"}


class FakeModel:
    model = "fixture-model"

    def __init__(self, value):
        self.value = value

    def interpret(self, _):
        if isinstance(self.value, Exception):
            raise self.value
        return json.dumps(self.value, ensure_ascii=False)


def service(model_value):
    async def companies(_):
        return (HYUNDAI,)

    base = ResearchService(
        dart=lambda: None,
        kosis=lambda: KosisClient(
            "fixture",
            enabled=True,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=fixture("DT_1DA7015S-Y-values")["payload"])
            ),
        ),
        model=lambda *_: FakeModel(model_value),
        require_source=lambda _: None,
        metadata_cache=PublicDataCache(),
        data_cache=PublicDataCache(),
    )
    base.companies = companies
    return EventService(base)


@pytest.mark.asyncio
async def test_plan_has_no_values_and_resolves_alias_without_fetching_financials():
    value = {"conditions": finance().model_dump(), "clarification": "", "unsupported": False}
    value["conditions"]["entities"] = ["현대차"]
    value["conditions"]["company_codes"] = []
    plan = await service(value).plan(EventPlanRequest(question="현대차 실적은 악화됐나?"))
    assert plan.conditions.entities == ["현대자동차"]
    assert plan.conditions.company_codes == [HYUNDAI.code]
    assert not {"facts", "brief"} & plan.model_dump().keys()


@pytest.mark.asyncio
async def test_composer_failure_keeps_evidence_and_cache_reapproval():
    svc = service(PlannerUnavailable())
    request = EventExecuteRequest(
        question="서울과 전국 청년 고용률", conditions=conditions(), approved=True
    )
    result = await svc.execute(request)
    assert result.brief.status == "failed" and len(result.facts) == 12
    again = await svc.execute(request)
    assert again.cache.status == "hit"
    assert all(t.tool != "KOSIS 공식 통계" for t in again.trace)
    assert again.conditions == request.conditions


@pytest.mark.asyncio
async def test_general_model_gets_same_conditions_but_no_evidence_or_tools():
    captured = []
    svc = service({"text": "확인할 자료가 필요합니다."})

    def model(instruction, schema, briefing):
        assert instruction == GENERAL_INSTRUCTION and briefing
        return SimpleNamespace(
            model="fixture-model",
            interpret=lambda value: (
                captured.append(json.loads(value)) or '{"text":"확인할 자료가 필요합니다."}'
            ),
        )

    svc.research.model = model
    req = EventExecuteRequest(question="서울 청년 고용", conditions=conditions(), approved=True)
    response = await svc.general(req)
    assert response.tools == [] and response.conditions == req.conditions
    assert captured == [
        {"question": req.question, "approved_conditions": req.conditions.model_dump()}
    ]


@pytest.mark.asyncio
async def test_snapshot_requires_exact_conditions_and_is_never_automatic():
    svc = service(PlannerUnavailable())
    req = EventExecuteRequest(
        question="저장 안 된 질문",
        conditions=conditions(),
        approved=True,
        mode="snapshot",
        snapshot_id="missing",
    )
    with pytest.raises(ResearchError):
        await svc.execute(req)


def test_event_http_contract_blocks_unapproved_and_mock():
    with TestClient(main.app) as client:
        for patch in ({"approved": False}, {"mode": "mock"}):
            body = {
                "question": "서울 청년 고용",
                "conditions": conditions().model_dump(),
                "approved": True,
            } | patch
            assert client.post("/api/v1/event/execute", json=body).status_code == 422
        catalog = client.get("/api/v1/event/catalog")
        assert catalog.status_code == 200
        assert "15-29세" in catalog.json()["ages"]


@pytest.mark.asyncio
async def test_official_snapshots_replay_exact_provenance_without_providers():
    from newsroom_agent.event_service import load_snapshots, snapshot_catalog

    assert len(snapshot_catalog()) == 4
    svc = service(PlannerUnavailable())
    for snapshot_id, item in load_snapshots().items():
        original = item["result"]
        req = EventExecuteRequest(
            question=original["question"],
            conditions=original["conditions"],
            approved=True,
            mode="snapshot",
            snapshot_id=snapshot_id,
        )
        replay = await svc.execute(req)
        general = await svc.general(req)
        assert replay.data_mode == "snapshot" and replay.brief.status == "complete"
        assert replay.generated_at == original["generated_at"]
        assert replay.facts[0].retrieved_at == original["facts"][0]["retrieved_at"]
        assert len(replay.trace) == 1 and "再" not in replay.trace[0].tool
        assert general.data_mode == "snapshot" and general.tools == []
        req.conditions.comparison = "증감률" if req.conditions.tool != "disclosures" else "종류별"
        with pytest.raises(ResearchError):
            await svc.execute(req)


@pytest.mark.asyncio
async def test_blank_model_comparison_is_an_explicit_proposal():
    value = {
        "conditions": conditions()
        .model_copy(update={"comparison": "", "comparison_period": ""})
        .model_dump()
    }
    plan = await service(value).plan(EventPlanRequest(question="서울과 전국 청년 고용은?"))
    assert plan.conditions.comparison == "증감 폭"
    assert plan.conditions.comparison_period == "시작·종료"
    assert any("명시하지 않은" in p for p in plan.proposals)
    assert not plan.field_errors

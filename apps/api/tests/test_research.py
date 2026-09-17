"""Part 2 behavior. All provider transports are mocked; no environment files."""

import io
import json
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from google import genai
from google.genai import types

from newsroom_agent import main
from newsroom_agent.planning import InvalidPlannerOutput
from newsroom_agent.providers.gemini_planner import GeminiCallLimiter, GeminiQuestionPlanner
from newsroom_agent.providers.kosis_employment import EmploymentQuery
from newsroom_agent.providers.opendart_financials import OpenDartError
from newsroom_agent.providers.opendart_research import (
    OpenDartResearchClient,
    find_companies,
    normalize_financials,
    read_companies,
)
from newsroom_agent.providers.planner import PlannerUnavailable
from newsroom_agent.research import calculated_facts, mock_facts
from newsroom_agent.research_briefing import render_brief
from newsroom_agent.research_models import ResearchConditions
from newsroom_agent.research_planning import MOCK_COMPANIES, ResearchIntent, propose_conditions

NOW = datetime(2026, 9, 17, tzinfo=UTC)
COMPANY = MOCK_COMPANIES[1]
QUESTION = "SK하이닉스 최근 실적이 좋아졌는지 확인하고 싶어."


def zip_directory(xml=None):
    body = io.BytesIO()
    if xml is None:
        xml = (
            "<result>"
            + "".join(
                f"<list><corp_code>{c.code}</corp_code><corp_name>{c.name}</corp_name>"
                f"<stock_code>{c.stock_code}</stock_code></list>"
                for c in MOCK_COMPANIES
            )
            + "</result>"
        )
    with zipfile.ZipFile(body, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)
    return body.getvalue()


def financial_payload(year, company=COMPANY):
    return {
        "status": "000",
        "list": [
            {
                "corp_code": company.code,
                "bsns_year": str(year),
                "reprt_code": "11011",
                "sj_div": "IS",
                "account_id": account,
                "account_nm": name,
                "thstrm_amount": amount,
                "currency": "KRW",
                "account_detail": "-",
                "rcept_no": f"{year + 1}0317000001",
            }
            for account, name, amount in [
                ("ifrs-full_Revenue", "매출액", f"{(year - 2020) * 1000:,}"),
                (
                    "dart_OperatingIncomeLoss",
                    "영업이익(손실)",
                    "-2,000" if year == 2023 else "3,000",
                ),
            ]
        ],
    }


@pytest.fixture
def client():
    with TestClient(main.app) as client:
        yield client


def get_plan(client, **extra):
    response = client.post("/api/v1/research/plan", json={"question": QUESTION, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def execute_body(plan, **extra):
    return {
        "question": plan["question"],
        "conditions": plan["conditions"],
        "mode": plan["data_mode"],
        "approved": True,
        **extra,
    }


def test_mock_end_to_end_approval_and_final_conditions(client):
    plan = get_plan(client)
    assert not {"facts", "brief", "evidence"} & plan.keys()
    assert plan["field_errors"] == {}
    assert plan["conditions"]["entity"] == "SK하이닉스"
    assert plan["conditions"]["metrics"] == ["매출액", "영업이익"]
    assert plan["proposals"]
    body = execute_body(plan, approved=False)
    assert client.post("/api/v1/research/execute", json=body).status_code == 422
    body.update(approved=True)
    body["conditions"]["start_year"] = 2023
    response = client.post("/api/v1/research/execute", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["conditions"] == body["conditions"]
    assert result["brief"]["generation_method"] == "scripted"
    assert result["brief"]["verification_status"] == "review_required"
    assert any(f["value"] == "-4000000000" for f in result["facts"])
    assert all(not f["source_urls"] for f in result["facts"])
    assert "가상" in result["caveats"][0]
    assert response.headers["X-Request-ID"] == result["request_id"]


@pytest.mark.parametrize("approved", [False, "true", 1, None])
def test_strict_approval_rejected_before_tools(client, monkeypatch, approved):
    plan = get_plan(client)
    monkeypatch.setattr(main, "get_research_service", lambda *_: pytest.fail("provider created"))
    assert (
        client.post(
            "/api/v1/research/execute", json=execute_body(plan, approved=approved)
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "question",
    [
        "실적이 어때?",
        "서울 주가",
        "기업 실적과 청년 고용 관계",
        "삼성전자 분기 영업이익",
        "전국 평균 청년 고용률",
    ],
)
def test_ambiguity_and_unsupported_scope(client, question):
    plan = get_plan(client, question=question)
    assert plan["field_errors"]
    assert plan["clarification_questions"]
    assert "brief" not in plan


def test_refinement_changes_company_metrics_and_recent_period(client):
    first = get_plan(client)
    second = get_plan(
        client,
        previous_conditions=first["conditions"],
        revision="삼성전자로 바꾸고 최근 2년 매출만 봐줘",
    )
    c = second["conditions"]
    assert c["entity"] == "삼성전자" and c["company_code"] == MOCK_COMPANIES[0].code
    assert c["metrics"] == ["매출액"] and c["start_year"] == 2023 and c["end_year"] == 2024


def test_kosis_single_region_plan_and_exact_query(client):
    plan = get_plan(client, question="서울 청년 고용률은 어떻게 달라졌을까?")
    assert plan["conditions"]["selected_source"] == "kosis"
    assert plan["conditions"]["entity"] == "서울특별시"
    result = client.post("/api/v1/research/execute", json=execute_body(plan)).json()
    assert {f["entity"] for f in result["facts"]} == {"서울특별시"}
    assert all(f["rank"] is None for f in result["facts"])
    query = EmploymentQuery(
        entity="서울특별시",
        metric="고용률",
        age_range="15-29세",
        start_year=2022,
        end_year=2024,
        allow_single_region=True,
    )
    assert query.parameters["objL1"] == "11"


def test_tampered_company_code_and_out_of_range_period_rejected(client):
    plan = get_plan(client)
    body = execute_body(plan)
    body["conditions"]["company_code"] = MOCK_COMPANIES[0].code
    assert client.post("/api/v1/research/execute", json=body).status_code == 422
    body["conditions"].update(company_code=COMPANY.code, end_year=2099)
    assert client.post("/api/v1/research/execute", json=body).status_code == 422


def test_mock_never_creates_live_tools(client, monkeypatch):
    monkeypatch.setattr(OpenDartResearchClient, "companies", lambda *_: pytest.fail("live"))
    monkeypatch.setattr(main, "get_question_planner", lambda *_: pytest.fail("model"))
    plan = get_plan(client)
    assert client.post("/api/v1/research/execute", json=execute_body(plan)).status_code == 200


def test_live_tools_metadata_only_before_approval_and_cache_reuse(client, monkeypatch):
    calls = []

    def transport(request):
        path = request.url.path
        calls.append(path)
        if path.endswith("corpCode.xml"):
            return httpx.Response(200, content=zip_directory())
        if path.endswith("list.json"):
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    "total_page": 1,
                    "list": [
                        {"corp_code": COMPANY.code, "report_nm": f"사업보고서 ({y}.12)", "rm": ""}
                        for y in (2022, 2023, 2024)
                    ],
                },
            )
        assert request.url.params["corp_code"] == COMPANY.code
        return httpx.Response(200, json=financial_payload(int(request.url.params["bsns_year"])))

    original = OpenDartResearchClient.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs, transport=httpx.MockTransport(transport), clock=lambda: NOW)

    monkeypatch.setattr(OpenDartResearchClient, "__init__", init)
    monkeypatch.setattr(main.settings, "live_api_enabled", True)
    monkeypatch.setattr(main.settings, "public_data_mode", "live")
    monkeypatch.setattr(main.settings, "opendart_enabled", True)
    monkeypatch.setattr(main.settings, "opendart_api_key", "test-key-never-real")
    monkeypatch.setattr(main.settings, "public_data_cache_enabled", True)
    plan = get_plan(client, mode="live")
    assert calls == ["/api/corpCode.xml", "/api/list.json"]
    assert (
        client.post("/api/v1/research/execute", json=execute_body(plan, approved=False)).status_code
        == 422
    )
    assert len(calls) == 2
    first = client.post("/api/v1/research/execute", json=execute_body(plan))
    assert first.status_code == 200, first.text
    assert len(calls) == 5
    body = execute_body(plan)
    body["conditions"]["comparison"] = "증감률"
    second = client.post("/api/v1/research/execute", json=body).json()
    assert len(calls) == 5
    assert second["cache"]["status"] == "hit"
    assert second["facts"][0]["retrieved_at"] == first.json()["facts"][0]["retrieved_at"]
    assert any("0 이하" in warning for warning in second["caveats"])
    assert "test-key" not in first.text


def test_directory_matching_and_xml_safety():
    companies = read_companies(zip_directory())
    assert find_companies(companies, " sk 하이닉스 ") == [COMPANY]
    assert find_companies(companies, "000660") == [COMPANY]
    for body in [b"not-a-zip", zip_directory('<!DOCTYPE x [<!ENTITY a "x">]><result/>')]:
        with pytest.raises(OpenDartError, match="형식"):
            read_companies(body)


@pytest.mark.parametrize(
    "mutation", ["wrong-company", "duplicate", "missing", "bad-amount", "currency"]
)
def test_financial_normalization_rejects_uncertain_data(mutation):
    payload = financial_payload(2023)
    if mutation == "wrong-company":
        payload["list"][0]["corp_code"] = "00000000"
    elif mutation == "duplicate":
        payload["list"].append(payload["list"][0])
    elif mutation == "missing":
        payload["list"][1]["thstrm_amount"] = "-"
    elif mutation == "bad-amount":
        payload["list"][0]["thstrm_amount"] = "12,34"
    else:
        payload["list"][0]["currency"] = "USD"
    with pytest.raises(OpenDartError):
        normalize_financials(payload, COMPANY, 2023, ["매출액", "영업이익"], NOW)


def facts():
    c = ResearchConditions(
        selected_source="opendart",
        entity=COMPANY.name,
        company_code=COMPANY.code,
        metrics=["영업이익"],
        start_year=2023,
        end_year=2024,
    )
    return c, calculated_facts(mock_facts(c), c)[0]


def valid_draft():
    sentence = {
        "text": "{{F1.entity}}의 {{F1.period}}년 값은 {{F1.value}} {{F1.unit}}입니다.",
        "evidence_ids": ["F1"],
    }
    return {
        "summary": sentence,
        "findings": [dict(sentence)],
        "limitations": ["가상 자료이며 실제 기업을 평가할 수 없습니다."],
        "follow_up_questions": ["공시 원문에서 확인할 내용은 무엇인가?"],
    }


@pytest.mark.parametrize("bad", ["literal-number", "missing-id", "unlisted-ref", "url", "slot"])
def test_brief_rejects_unsupported_numbers_and_references(bad):
    draft = valid_draft()
    if bad == "literal-number":
        draft["summary"]["text"] = "매출이 999조원입니다."
    elif bad == "missing-id":
        draft["summary"]["evidence_ids"] = ["F999"]
    elif bad == "unlisted-ref":
        draft["summary"]["evidence_ids"] = ["F2"]
    elif bad == "url":
        draft["limitations"] = ["https://example.com"]
    else:
        draft["summary"]["text"] = "{{F1.fake}}"
    with pytest.raises(InvalidPlannerOutput):
        render_brief(json.dumps(draft), facts()[1])


def test_gemini_sdk_schema_and_grounded_output(client, monkeypatch):
    calls = []

    def transport(request):
        payload = json.loads(request.content)
        calls.append(payload)
        text = json.dumps(valid_draft(), ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": text}]},
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    def planner(*_):
        return GeminiQuestionPlanner(
            client_factory=lambda: genai.Client(
                vertexai=False,
                api_key="test-key",
                http_options=types.HttpOptions(
                    httpx_client=httpx.Client(transport=httpx.MockTransport(transport)),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            ),
            model="gemini-test",
            enabled=True,
            configured=True,
            limiter=GeminiCallLimiter(30, 8),
        )

    monkeypatch.setattr(main, "get_question_planner", planner)
    monkeypatch.setattr(main.settings, "live_api_enabled", True)
    monkeypatch.setattr(main.settings, "gemini_briefing_enabled", True, raising=False)
    plan = get_plan(client)
    assert calls == []
    result = client.post(
        "/api/v1/research/execute", json=execute_body(plan, briefing_method="gemini")
    ).json()
    assert len(calls) == 1
    assert calls[0]["generationConfig"]["responseJsonSchema"]
    assert "tools" not in calls[0]
    assert result["brief"]["status"] == "complete"
    assert "{{" not in result["brief"]["content"]["summary"]["text"]
    assert result["brief"]["content"]["summary"]["evidence_ids"] == ["F1"]


def test_brief_failure_keeps_evidence_and_does_not_masquerade_as_success(client, monkeypatch):
    def fail(_):
        raise PlannerUnavailable()

    monkeypatch.setattr(
        main,
        "get_question_planner",
        lambda *_: SimpleNamespace(model="gemini-test", interpret=fail),
    )
    plan = get_plan(client)
    response = client.post(
        "/api/v1/research/execute", json=execute_body(plan, briefing_method="gemini")
    )
    assert response.status_code == 200
    result = response.json()
    assert result["facts"]
    assert result["brief"]["status"] == "failed"
    assert result["brief"]["content"] is None
    assert result["conditions"] == plan["conditions"]


def test_loss_growth_is_not_fabricated():
    c, raw = facts()
    c.comparison = "증감률"
    calculated, warnings = calculated_facts([f for f in raw if f.kind == "observation"], c)
    assert warnings and all(f.kind == "observation" for f in calculated)


def test_model_short_region_name_is_normalized_without_changing_geography():
    intent = ResearchIntent(
        **{
            k: None
            for k in ResearchIntent.model_fields
            if k
            not in {
                "selected_source",
                "entity",
                "unsupported",
            }
        },
        selected_source="kosis",
        entity="서울",
        unsupported=False,
    )
    conditions, _ = propose_conditions(intent, [2020, 2021, 2022, 2023, 2024])
    assert conditions.entity == "서울특별시"


def test_gemini_selects_catalog_source_without_guided_keyword_router(client, monkeypatch):
    calls = []
    intent = ResearchIntent(
        **{
            k: None
            for k in ResearchIntent.model_fields
            if k
            not in {
                "selected_source",
                "entity",
                "unsupported",
            }
        },
        selected_source="opendart",
        entity="SK하이닉스",
        unsupported=False,
    )

    def interpret(payload):
        calls.append(json.loads(payload))
        return intent.model_dump_json()

    monkeypatch.setattr(
        main,
        "get_question_planner",
        lambda *_: SimpleNamespace(model="gemini-test", interpret=interpret),
    )
    plan = get_plan(
        client, question="종목번호 000660의 최근 성과를 조사해줘", interpretation_method="gemini"
    )
    assert len(calls) == 1
    assert plan["conditions"]["entity"] == "SK하이닉스"
    assert plan["interpretation_model"] == "gemini-test"
    assert not plan["field_errors"]
    assert "facts" not in plan and "brief" not in plan


def test_kosis_ranking_uses_unrounded_values_and_ties():
    c = ResearchConditions(
        selected_source="kosis",
        entity="수도권 시·도",
        metrics=["고용률"],
        start_year=2022,
        end_year=2024,
        comparison="증감률",
    )
    raw = mock_facts(c)
    for fact in raw:
        fact.value = (
            "40" if fact.period == "2022" else ("40.001" if fact.entity == "경기도" else "40.002")
        )
    results, _ = calculated_facts(raw, c)
    changes = {f.entity: f for f in results if f.kind == "change"}
    assert changes["서울특별시"].rank == changes["인천광역시"].rank == 1
    assert changes["경기도"].rank == 3


def test_missing_later_year_fails_whole_financial_query():
    calls = []

    def response(request):
        year = int(request.url.params["bsns_year"])
        calls.append(year)
        return httpx.Response(
            200,
            json=financial_payload(year)
            if year == 2022
            else {"status": "013", "message": "provider-secret"},
        )

    client = OpenDartResearchClient(
        "test-key", transport=httpx.MockTransport(response), enabled=True, clock=lambda: NOW
    )
    import asyncio

    with pytest.raises(OpenDartError) as error:
        asyncio.run(client.financials(COMPANY, [2022, 2023, 2024], ["매출액"]))
    assert calls == [2022, 2023]
    assert "provider-secret" not in str(error.value)

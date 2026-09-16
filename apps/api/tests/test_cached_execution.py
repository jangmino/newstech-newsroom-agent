"""Approval, adapters and cache together, with offline transports and a fake clock."""

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from newsroom_agent import main
from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.opendart import OpenDartClient
from newsroom_agent.public_data_cache import PublicDataCache

ROOT = Path(__file__).parents[3] / "fixtures/public-data"
EMPLOYMENT = json.loads((ROOT / "kosis-youth-employment-2020-2024.json").read_text())["rows"]
REVENUE = json.loads((ROOT / "opendart-samsung-revenue-2022-2024.json").read_text())["observations"]
BODY = {
    "kosis": {"question": "전국 시·도 15-29세 청년 고용률 2020-2024년 연간 증감 폭 비교",
              "mode": "live", "approved": True, "conditions": {
                  "selected_source": "kosis", "entity": "전국 시·도", "metric": "고용률",
                  "period": "2020-2024", "comparison": "증감 폭",
                  "filters": {"age_range": "15-29세", "frequency": "연간"}}},
    "opendart": {"question": "삼성전자 2022-2024년 연간 연결 매출액 증감 폭 비교",
                 "mode": "live", "approved": True, "conditions": {
                     "selected_source": "opendart", "entity": "삼성전자", "metric": "매출액",
                     "period": "2022-2024", "comparison": "증감 폭",
                     "filters": {"statement_basis": "연결", "report_type": "연간"}}},
}


@pytest_asyncio.fixture
async def environment(monkeypatch):
    for name, value in {
        "live_api_enabled": True, "public_data_mode": "live", "kosis_enabled": True,
        "opendart_enabled": True, "kosis_api_key": "offline-kosis-key",
        "opendart_api_key": "offline-dart-key", "public_data_cache_enabled": True,
        "cache_ttl_seconds": 10, "cache_max_entries": 4,
    }.items():
        monkeypatch.setattr(main.settings, name, value)
    state = SimpleNamespace(seconds=0, calls=[], fail=False, invalid=False,
                            release=None, started=asyncio.Event())

    def now():
        return datetime(2026, 9, 16, tzinfo=UTC) + timedelta(seconds=state.seconds)

    async def transport(request):
        state.calls.append(request)
        state.started.set()
        if state.release is not None:
            await state.release.wait()
        kosis = request.url.host == "kosis.kr"
        if state.fail and (kosis or request.url.params["bsns_year"] == "2024"):
            return httpx.Response(503)
        if kosis:
            p = request.url.params
            rows = [row for row in EMPLOYMENT if row["C1"] in p["objL1"].split("+")
                    and p["startPrdDe"] <= row["PRD_DE"] <= p["endPrdDe"]]
            return httpx.Response(200, json=rows[:-1] if state.invalid else rows)
        year = request.url.params["bsns_year"]
        row = next(row for row in REVENUE if str(row["year"]) == year)
        return httpx.Response(200, json={"status": "000", "list": [{
            "corp_code": row["corp_code"], "bsns_year": year,
            "reprt_code": row["report_code"], "account_id": row["account_id"],
            "account_nm": row["account_name"], "rcept_no": row["receipt_no"],
            "currency": row["currency"], "sj_div": row["statement_type"],
            "thstrm_amount": "-" if state.invalid else row["raw_amount"],
        }]})

    monkeypatch.setattr(main, "KosisClient", lambda *a, **k: KosisClient(
        "offline-kosis-key", enabled=True, clock=now, transport=httpx.MockTransport(transport),
    ))
    monkeypatch.setattr(main, "OpenDartClient", lambda *a, **k: OpenDartClient(
        "offline-dart-key", enabled=True, clock=now, transport=httpx.MockTransport(transport),
    ))
    async with main.lifespan(main.app):
        main.app.state.employment_cache = PublicDataCache(
            10, 4, timer=lambda: state.seconds, clock=now,
        )
        main.app.state.revenue_cache = PublicDataCache(
            10, 4, timer=lambda: state.seconds, clock=now,
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                     base_url="http://offline.test") as client:
            state.client = client
            yield state
    assert not main.app.state.employment_cache._entries
    assert not main.app.state.revenue_cache._entries


async def execute(env, source, **changes):
    body = copy.deepcopy(BODY[source])
    body["conditions"].update(changes)
    return await env.client.post("/api/v1/execute", json=body)


@pytest.mark.asyncio
@pytest.mark.parametrize("source,requests", [("kosis", 1), ("opendart", 2)])
async def test_comparison_reuses_only_data_with_new_result(environment, source, requests):
    env = environment
    first = (await execute(env, source)).json()
    env.seconds = 3
    second = (await execute(env, source, comparison="증감률")).json()
    assert len(env.calls) == requests
    assert first["cache"]["status"] == "miss" and second["cache"]["status"] == "hit"
    assert second["cache"]["age_seconds"] == 3
    assert first["cache"]["expires_at"] == second["cache"]["expires_at"]
    assert first["evidence"]["retrieved_at"] == second["evidence"]["retrieved_at"]
    assert first["evidence"]["raw_values"] == second["evidence"]["raw_values"]
    assert first["request_id"] != second["request_id"]
    assert second["query_plan"]["comparison"] == "증감률"
    assert second["evidence"]["query_parameters"]["comparison"] == "증감률"
    assert first["brief"]["summary"] != second["brief"]["summary"]
    assert second["brief"]["verification_status"] == "review_required"
    assert second["general_response"]["data_mode"] == "mock"
    for secret in ("offline-kosis-key", "offline-dart-key", "apiKey", "crtfc_key"):
        assert secret not in json.dumps(second)
    calc = "calculation" if source == "kosis" else "financial_calculation"
    assert second[calc]["result_unit"] == "%"
    if source == "kosis":
        assert second[calc]["rows"][0]["region"] == "전북특별자치도"
    else:
        assert second[calc]["change"] == "-0.45"


@pytest.mark.asyncio
async def test_scope_period_and_provider_have_distinct_cache_keys(environment):
    env = environment
    assert (await execute(env, "kosis")).json()["cache"]["status"] == "miss"
    subset = (await execute(env, "kosis", entity="수도권 시·도")).json()
    shorter = (await execute(env, "kosis", entity="수도권 시·도", period="2021-2023")).json()
    assert len(subset["evidence"]["raw_values"]) == 15
    assert len(shorter["evidence"]["raw_values"]) == 9
    assert subset["cache"]["status"] == shorter["cache"]["status"] == "miss"
    assert (await execute(env, "opendart")).json()["cache"]["status"] == "miss"
    assert len(env.calls) == 5
    assert (await execute(env, "kosis")).json()["cache"]["status"] == "hit"
    assert len(env.calls) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("source,requests", [("kosis", 1), ("opendart", 2)])
async def test_concurrent_api_requests_share_transport_not_result_id(environment, source, requests):
    env = environment
    env.release = asyncio.Event()
    tasks = [asyncio.create_task(execute(env, source)) for _ in range(8)]
    await env.started.wait()
    env.release.set()
    results = [response.json() for response in await asyncio.gather(*tasks)]
    assert len(env.calls) == requests
    assert [r["cache"]["status"] for r in results].count("miss") == 1
    assert [r["cache"]["status"] for r in results].count("coalesced") == 7
    assert len({r["request_id"] for r in results}) == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("source,requests", [("kosis", 1), ("opendart", 2)])
async def test_expired_data_and_partial_pairs_are_not_fallbacks(environment, source, requests):
    env = environment
    first = (await execute(env, source)).json()
    env.seconds = 10
    env.fail = True
    failure = await execute(env, source)
    assert failure.status_code == 503
    assert set(failure.json()) == {"detail"}
    assert len(env.calls) == requests * 2
    env.fail = False
    env.seconds = 11
    retried = (await execute(env, source)).json()
    assert len(env.calls) == requests * 3  # Both DART years fetched after second-year failure.
    assert retried["cache"]["status"] == "miss"
    assert retried["evidence"]["retrieved_at"] != first["evidence"]["retrieved_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["kosis", "opendart"])
async def test_normalization_failures_do_not_enter_cache(environment, source):
    env = environment
    env.invalid = True
    assert (await execute(env, source)).status_code == 503
    env.invalid = False
    success = await execute(env, source)
    assert success.status_code == 200 and success.json()["cache"]["status"] == "miss"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["kosis", "opendart"])
async def test_warm_cache_cannot_bypass_gates_or_approval(environment, monkeypatch, source):
    env = environment
    assert (await execute(env, source)).status_code == 200
    calls = len(env.calls)
    body = copy.deepcopy(BODY[source])
    body["approved"] = False
    assert (await env.client.post("/api/v1/execute", json=body)).status_code == 422
    assert (await execute(env, source, period="2024-2024")).status_code == 422
    body["approved"] = True
    body["question"] = "삼성전자 매출" if source == "kosis" else "청년 고용률"
    assert (await env.client.post("/api/v1/execute", json=body)).status_code == 422
    for name, value in ((f"{source}_enabled", False), (f"{source}_api_key", ""),
                        ("live_api_enabled", False), ("public_data_mode", "mock")):
        with monkeypatch.context() as patch:
            patch.setattr(main.settings, name, value)
            response = await execute(env, source)
            assert response.status_code == 503 and set(response.json()) == {"detail"}
    assert len(env.calls) == calls


@pytest.mark.asyncio
async def test_plan_mock_and_legacy_do_not_touch_live_cache(environment):
    env = environment
    body = BODY["kosis"]
    plan = await env.client.post("/api/v1/plan", json={
        "question": body["question"], "mode": "live",
    })
    assert plan.status_code == 200 and "cache" not in plan.json()
    mock = await env.client.post("/api/v1/execute", json={**body, "mode": "mock"})
    assert mock.status_code == 200 and mock.json()["cache"] is None
    legacy = await env.client.post("/api/v1/analyze", json={"question": body["question"]})
    assert legacy.status_code == 200 and "cache" not in legacy.json()
    assert not env.calls and not main.app.state.employment_cache._entries


@pytest.mark.asyncio
@pytest.mark.parametrize("source,requests", [("kosis", 2), ("opendart", 4)])
async def test_disabled_cache_keeps_uncached_flow(environment, monkeypatch, source, requests):
    env = environment
    monkeypatch.setattr(main.settings, "public_data_cache_enabled", False)
    for _ in range(2):
        result = (await execute(env, source)).json()
        assert result["cache"] is None and result["evidence"]["data_mode"] == "live"
    assert len(env.calls) == requests
    assert not main.app.state.employment_cache._entries
    assert not main.app.state.revenue_cache._entries

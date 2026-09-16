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

ROOT = Path(__file__).parents[1] / "src/newsroom_agent/snapshot_data"
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
        limiter=k.get("limiter"),
    ))
    monkeypatch.setattr(main, "OpenDartClient", lambda *a, **k: OpenDartClient(
        "offline-dart-key", enabled=True, clock=now, transport=httpx.MockTransport(transport),
        limiter=k.get("limiter"),
    ))
    async with main.lifespan(main.app):
        def configure_limits(rpm=30, concurrent=2):
            monkeypatch.setattr(main.settings, "public_data_requests_per_minute", rpm)
            monkeypatch.setattr(main.settings, "public_data_max_concurrent_requests", concurrent)
            for source in ("kosis", "opendart"):
                main.get_public_data_limiter(source, rpm, concurrent)._timer = lambda: state.seconds

        state.configure_limits = configure_limits
        configure_limits()
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
    env.configure_limits(rpm=requests, concurrent=1)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("source,requests", [("kosis", 1), ("opendart", 2)])
async def test_cache_hit_bypasses_exhausted_quota_but_expired_data_does_not(
    environment, source, requests,
):
    env = environment
    env.configure_limits(rpm=requests)
    assert (await execute(env, source)).status_code == 200
    hit = await execute(env, source, comparison="증감률")
    assert hit.status_code == 200 and hit.json()["cache"]["status"] == "hit"
    assert len(env.calls) == requests
    env.seconds = 10
    limited = await execute(env, source)
    assert limited.status_code == 429
    assert set(limited.json()) == {"detail"}  # No stale evidence or briefing.
    assert limited.json()["detail"] == {
        "code": "public_data_rate_limited", "message": limited.json()["detail"]["message"],
        "field_errors": {}, "source": source, "scope": "process", "retry_after_seconds": 50,
    }
    assert "이 조건으로 조회" in limited.json()["detail"]["message"]
    assert limited.headers["retry-after"] == "50"
    assert limited.headers["cache-control"] == "no-store"
    assert "offline-" not in limited.text
    assert len(env.calls) == requests
    env.seconds = 60
    retried = await execute(env, source)
    assert retried.status_code == 200 and retried.json()["cache"]["status"] == "miss"
    assert len(env.calls) == requests * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("source,requests", [("kosis", 1), ("opendart", 2)])
async def test_busy_uncached_query_does_not_block_cache_hit_or_consume_quota(
    environment, monkeypatch, source, requests,
):
    env = environment
    env.configure_limits(rpm=requests * 3, concurrent=1)
    assert (await execute(env, source)).status_code == 200
    periods = ("2020-2023", "2021-2024") if source == "kosis" else ("2022-2024", "2022-2024")
    # DART currently supports one fixed pair; bypass cache to exercise independent HTTP attempts.
    if source == "opendart":
        monkeypatch.setattr(main.settings, "public_data_cache_enabled", False)
    env.release = asyncio.Event()
    env.started.clear()
    active = asyncio.create_task(execute(env, source, period=periods[0]))
    try:
        await asyncio.wait_for(env.started.wait(), 2)
        monkeypatch.setattr(main.settings, "public_data_cache_enabled", True)
        assert (await execute(env, source)).json()["cache"]["status"] == "hit"
        if source == "opendart":
            monkeypatch.setattr(main.settings, "public_data_cache_enabled", False)
        for _ in range(3):
            rejected = await execute(env, source, period=periods[1])
            assert rejected.status_code == 429
            assert rejected.json()["detail"]["code"] == "public_data_busy"
            assert rejected.json()["detail"]["retry_after_seconds"] is None
            assert rejected.json()["detail"]["source"] == source
            assert "retry-after" not in rejected.headers
            assert rejected.headers["cache-control"] == "no-store"
            assert len(env.calls) == requests + 1
    finally:
        env.release.set()
        completed = await active
    assert completed.status_code == 200
    assert (await execute(env, source, period=periods[1])).status_code == 200
    assert len(env.calls) == requests * 3


@pytest.mark.asyncio
@pytest.mark.parametrize("source,requests", [("kosis", 1), ("opendart", 2)])
async def test_disabling_cache_cannot_disable_http_limits(
    environment, monkeypatch, source, requests,
):
    env = environment
    env.configure_limits(rpm=requests)
    monkeypatch.setattr(main.settings, "public_data_cache_enabled", False)
    assert (await execute(env, source)).status_code == 200
    assert (await execute(env, source)).status_code == 429
    assert len(env.calls) == requests


@pytest.mark.asyncio
async def test_partial_dart_pair_is_not_cached_and_provider_budgets_are_independent(environment):
    env = environment
    env.configure_limits(rpm=2)
    # Spend one DART call before the pair; the first year fits, the second does not.
    with main.get_public_data_limiter("opendart", 2, 2).slot():
        pass
    response = await execute(env, "opendart")
    assert response.status_code == 429
    assert len(env.calls) == 1 and env.calls[0].url.params["bsns_year"] == "2022"
    assert not main.app.state.revenue_cache._entries
    assert (await execute(env, "kosis")).status_code == 200
    assert (await execute(env, "kosis", entity="수도권 시·도")).status_code == 200
    env.seconds = 60
    success = await execute(env, "opendart")
    assert success.status_code == 200 and success.json()["cache"]["status"] == "miss"
    assert [r.url.params["bsns_year"] for r in env.calls if "bsns_year" in r.url.params] == [
        "2022", "2022", "2024",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["kosis", "opendart"])
async def test_invalid_normalization_counts_attempt_and_releases_slot(environment, source):
    env = environment
    env.configure_limits(rpm=1, concurrent=1)
    env.invalid = True
    assert (await execute(env, source)).status_code == 503
    limited = await execute(env, source)
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "public_data_rate_limited"
    env.seconds = 60
    # A second invalid HTTP result, not a leaked busy slot.
    assert (await execute(env, source)).status_code == 503
    assert len(env.calls) == 2


@pytest.mark.asyncio
async def test_mock_plan_and_validation_do_not_use_or_require_public_data_quota(environment):
    env = environment
    env.configure_limits(rpm=1)
    body = copy.deepcopy(BODY["kosis"])
    body["approved"] = False
    assert (await env.client.post("/api/v1/execute", json=body)).status_code == 422
    assert (await execute(env, "kosis", period="2024-2024")).status_code == 422
    assert not env.calls
    assert (await execute(env, "kosis")).status_code == 200  # Validation used no quota.
    body["approved"] = True
    for _ in range(2):
        assert (await env.client.get("/health")).status_code == 200
        assert (await env.client.post("/api/v1/plan", json={
            "question": body["question"], "mode": "live",
        })).status_code == 200
        assert (await env.client.post("/api/v1/execute", json={
            **body, "mode": "mock",
        })).status_code == 200
        assert (await env.client.post("/api/v1/analyze", json={
            "question": body["question"],
        })).status_code == 200
    assert len(env.calls) == 1


@pytest.mark.asyncio
async def test_dart_years_are_counted_at_separate_http_start_times(environment):
    env = environment
    env.configure_limits(rpm=2)
    env.release = asyncio.Event()
    active = asyncio.create_task(execute(env, "opendart"))
    try:
        await asyncio.wait_for(env.started.wait(), 2)
        env.seconds = 30
    finally:
        env.release.set()
        result = await active
    assert result.status_code == 200
    env.seconds = 60  # Only the first year has left the rolling window.
    limited = await execute(env, "opendart")
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "30"
    assert len(env.calls) == 3


@pytest.mark.asyncio
async def test_cancelled_cache_waiter_does_not_release_active_http_slot(environment):
    env = environment
    env.configure_limits(rpm=2, concurrent=1)
    env.release = asyncio.Event()
    first = asyncio.create_task(execute(env, "kosis"))
    await asyncio.wait_for(env.started.wait(), 2)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    # The cache's underlying HTTP request still runs even after its waiter disconnects.
    busy = await execute(env, "kosis", entity="수도권 시·도")
    assert busy.status_code == 429
    assert busy.json()["detail"]["code"] == "public_data_busy"
    env.release.set()
    shared = await execute(env, "kosis")
    assert shared.status_code == 200
    assert len(env.calls) == 1
    assert (await execute(env, "kosis", entity="수도권 시·도")).status_code == 200
    assert len(env.calls) == 2

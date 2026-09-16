"""Synthetic API-shaped examples only; these are not Samsung financial data or snapshots."""

import asyncio
import copy
import logging
import traceback
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from newsroom_agent import main
from newsroom_agent.providers.opendart import OpenDartClient
from newsroom_agent.providers.opendart_financials import OpenDartError, normalize_revenue

NOW = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)
FAKE_KEY = "test-only-not-a-real-credential"


def row(year="2022", amount="1,234"):
    return {
        "corp_code": "00126380", "bsns_year": year, "reprt_code": "11011",
        "sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "수익(매출액)",
        "account_detail": "-", "currency": "KRW", "rcept_no": "20250301000001",
        "thstrm_amount": amount, "frmtrm_amount": "999", "thstrm_add_amount": "777",
    }


def payload(year="2022", amount="1,234"):
    return {"status": "000", "message": "synthetic test", "list": [row(year, amount)]}


def adapter(handler, **options):
    return OpenDartClient(**({
        "api_key": FAKE_KEY, "transport": httpx.MockTransport(handler),
        "enabled": True, "clock": lambda: NOW,
    } | options))


@pytest.mark.asyncio
async def test_two_year_contract_exact_amounts_and_auditable_metadata(caplog):
    calls = []
    caplog.set_level(logging.DEBUG)

    def handler(request):
        params = dict(request.url.params)
        calls.append(params)
        assert request.method == "GET"
        assert request.url.host == "opendart.fss.or.kr" and request.url.scheme == "https"
        assert request.url.path == "/api/fnlttSinglAcntAll.json"
        assert params == {
            "corp_code": "00126380", "bsns_year": params["bsns_year"],
            "reprt_code": "11011", "fs_div": "CFS", "crtfc_key": FAKE_KEY,
        }
        assert set(request.extensions["timeout"].values()) == {20}
        amount = "9,007,199,254,740,993" if params["bsns_year"] == "2022" else "0"
        body = payload(params["bsns_year"], amount)
        # Unrelated rows do not affect account selection; array order does not define meaning.
        other = row(params["bsns_year"], "555")
        other.update(account_id="ifrs-full_Assets", account_nm="자산총계", sj_div="BS")
        body["list"].insert(0, other)
        return httpx.Response(200, json=body)

    client = adapter(handler)
    result = await client.fetch_revenue(2022, 2024)
    assert [call["bsns_year"] for call in calls] == ["2022", "2024"]
    assert result.start.amount == "9007199254740993" and result.end.amount == "0"
    assert result.start.raw_amount == "9,007,199,254,740,993"
    assert result.start.currency == "KRW" and result.start.unit == "원"
    assert result.start.statement_basis == "CFS" and result.start.account_id == "ifrs-full_Revenue"
    assert result.start.receipt_no == "20250301000001"
    assert result.start.source_url == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250301000001"
    assert result.start.retrieved_at == NOW and result.end.retrieved_at == NOW
    assert result.start.query_parameters == {
        "corp_code": "00126380", "bsns_year": "2022", "reprt_code": "11011", "fs_div": "CFS",
    }
    assert "기사 사용 승인" in result.caveats[-1]
    assert FAKE_KEY not in repr(result) + repr(client) + caplog.text
    assert "crtfc_key" not in caplog.text


@pytest.mark.parametrize("statement,account_id", [("IS", "ifrs-full_Revenue"),
                                                  ("CIS", "ifrs_Revenue")])
def test_supported_account_identifiers_do_not_depend_on_korean_label(statement, account_id):
    body = payload()
    body["list"][0].update(sj_div=statement, account_id=account_id, account_nm="매출액")
    assert normalize_revenue(body, 2022, NOW).amount == "1234"


@pytest.mark.parametrize("change,code", [
    ({"corp_code": "00000000"}, "invalid_response"),
    ({"bsns_year": "2024"}, "invalid_response"),
    ({"bsns_year": 2022}, "invalid_response"),
    ({"reprt_code": "11012"}, "invalid_response"),
    ({"fs_div": "OFS"}, "invalid_response"),
    ({"currency": "USD"}, "unsupported_currency"),
    ({"currency": "백만원"}, "unsupported_currency"),
    ({"currency": None}, "unsupported_currency"),
    ({"sj_div": "CF"}, "missing_account"),
    ({"sj_div": {}}, "missing_account"),
    ({"account_id": "-표준계정코드 미사용-"}, "missing_account"),
    ({"account_id": "ifrs-full_ProfitLoss"}, "missing_account"),
    ({"account_id": {}}, "missing_account"),
    ({"rcept_no": "not-a-receipt?crtfc_key=private"}, "invalid_response"),
    ({"account_nm": ""}, "invalid_response"),
    ({"account_detail": "segment member"}, "invalid_response"),
])
@pytest.mark.asyncio
async def test_wrong_identity_scope_unit_or_account_stops_before_second_year(change, code):
    calls = []

    def handler(request):
        calls.append(request)
        body = payload()
        body["list"][0].update(change)
        return httpx.Response(200, json=body)

    with pytest.raises(OpenDartError) as caught:
        await adapter(handler).fetch_revenue(2022, 2024)
    assert caught.value.code == code and len(calls) == 1


@pytest.mark.parametrize("raw,code", [
    (None, "missing_value"), ("", "missing_value"), ("  ", "missing_value"),
    ("-", "missing_value"), ("-1", "invalid_amount"), ("(1,000)", "invalid_amount"),
    ("1,00", "invalid_amount"), ("1,,000", "invalid_amount"), ("1.5", "invalid_amount"),
    ("1e3", "invalid_amount"), ("NaN", "invalid_amount"), ("Infinity", "invalid_amount"),
    (1234, "invalid_amount"), (True, "invalid_amount"), ("１２００", "invalid_amount"),
    ("1" * 31, "invalid_amount"), ("1" * 65, "invalid_amount"),
])
def test_missing_or_invalid_current_amount_never_uses_prior_or_cumulative_amount(raw, code):
    with pytest.raises(OpenDartError) as caught:
        normalize_revenue(payload(amount=raw), 2022, NOW)
    assert caught.value.code == code


@pytest.mark.parametrize("raw,normalized", [
    ("0", "0"), ("000123", "123"), (" 1,234 ", "1234"),
    ("999999999999999", "999999999999999"),
])
def test_integer_amounts_are_normalized_without_scaling_or_rounding(raw, normalized):
    result = normalize_revenue(payload(amount=raw), 2022, NOW)
    assert result.amount == normalized and result.raw_amount == raw.strip()


@pytest.mark.parametrize("same_statement", [True, False])
def test_duplicate_revenue_is_ambiguous_even_if_amounts_agree(same_statement):
    body = payload()
    duplicate = copy.deepcopy(body["list"][0])
    if not same_statement:
        duplicate["sj_div"] = "CIS"
    body["list"].append(duplicate)
    with pytest.raises(OpenDartError) as caught:
        normalize_revenue(body, 2022, NOW)
    assert caught.value.code == "ambiguous_account"


@pytest.mark.parametrize("status,code", [
    ("010", "authentication"), ("011", "authentication"), ("012", "authentication"),
    ("901", "authentication"), ("013", "no_data"), ("014", "no_data"),
    ("020", "rate_limited"), ("100", "invalid_request"), ("101", "invalid_request"),
    ("800", "unavailable"), ("900", "unavailable"), ("999", "unavailable"),
])
@pytest.mark.asyncio
async def test_provider_statuses_are_safe_and_not_retried(status, code, caplog):
    caplog.set_level(logging.DEBUG)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"status": status, "message": f"private-body {FAKE_KEY}"})

    with pytest.raises(OpenDartError) as caught:
        await adapter(handler).fetch_revenue(2022, 2024)
    assert caught.value.code == code and len(calls) == 1
    output = "".join(traceback.format_exception(caught.value)) + caplog.text
    assert FAKE_KEY not in output and "private-body" not in output


@pytest.mark.parametrize("status,code", [
    (301, "unavailable"), (400, "invalid_request"), (401, "authentication"),
    (403, "authentication"), (408, "timeout"), (429, "rate_limited"),
    (500, "unavailable"), (503, "unavailable"), (504, "timeout"),
])
@pytest.mark.asyncio
async def test_http_errors_and_redirects_do_not_follow_retry_or_expose_keys(status, code, caplog):
    caplog.set_level(logging.DEBUG)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=f"private-body {FAKE_KEY}", headers={
            "Location": f"https://untrusted.invalid/?crtfc_key={FAKE_KEY}",
        })

    with pytest.raises(OpenDartError) as caught:
        await adapter(handler).fetch_revenue(2022, 2024)
    assert caught.value.code == code and len(calls) == 1
    assert FAKE_KEY not in str(caught.value) + caplog.text


@pytest.mark.parametrize("raw,code", [
    (b"<html>not JSON</html>", "invalid_response"), (b"[]", "invalid_response"),
    (b"{}", "invalid_response"), (b'{"status":0}', "invalid_response"),
    (b'{"status":"not-a-status"}', "invalid_response"),
    (b'{"status":"013","status":"000","list":[]}', "invalid_response"),
    (b'{"status":"000","list":NaN}', "invalid_response"),
    (b'{"status":"000","list":[]}', "no_data"),
    (b'{"status":"000","list":{}}', "invalid_response"),
    (b'{"status":"000","list":[null]}', "invalid_response"),
    (b" " * 2_000_001, "invalid_response"),
])
@pytest.mark.asyncio
async def test_malformed_or_oversized_payloads_fail_safely(raw, code):
    with pytest.raises(OpenDartError) as caught:
        await adapter(lambda request: httpx.Response(200, content=raw)).fetch_revenue(2022, 2024)
    assert caught.value.code == code


@pytest.mark.parametrize("start,end", [
    (2014, 2024), (2022, 2022), (2024, 2022), (2022, 2026), (2022, 2027),
    (True, 2024), ("2022", 2024), (2022, 2024.0),
])
@pytest.mark.asyncio
async def test_invalid_years_never_open_transport(start, end):
    with pytest.raises(OpenDartError) as caught:
        await adapter(lambda request: pytest.fail("No request expected")).fetch_revenue(start, end)
    assert caught.value.code == "invalid_request"


@pytest.mark.parametrize("options,code", [
    ({"enabled": False}, "disabled"), ({"enabled": "true"}, "disabled"),
    ({"api_key": " "}, "configuration"), ({"timeout_seconds": 0}, "configuration"),
    ({"timeout_seconds": float("nan")}, "configuration"),
])
@pytest.mark.asyncio
async def test_disabled_or_bad_configuration_never_sends(options, code):
    with pytest.raises(OpenDartError) as caught:
        await adapter(lambda request: pytest.fail("No request expected"), **options).fetch_revenue(
            2022, 2024,
        )
    assert caught.value.code == code


@pytest.mark.asyncio
async def test_second_year_failure_never_returns_a_partial_pair():
    calls = []

    def handler(request):
        year = request.url.params["bsns_year"]
        calls.append(year)
        return httpx.Response(200, json=payload(year) if year == "2022" else {"status": "013"})

    with pytest.raises(OpenDartError) as caught:
        await adapter(handler).fetch_revenue(2022, 2024)
    assert caught.value.code == "no_data" and calls == ["2022", "2024"]


@pytest.mark.parametrize("exception,code", [(httpx.ReadTimeout, "timeout"),
                                           (httpx.ConnectError, "unavailable"),
                                           (ValueError, "unavailable")])
@pytest.mark.asyncio
async def test_transport_exceptions_are_safe_and_log_filter_is_restored(exception, code, caplog):
    caplog.set_level(logging.DEBUG)

    def handler(request):
        logging.getLogger("httpcore.http11").debug("private headers %s", FAKE_KEY)
        raise exception(f"private-provider-detail {request.url}")

    with pytest.raises(OpenDartError) as caught:
        await adapter(handler).fetch_revenue(2022, 2024)
    logging.getLogger("httpx").info("unrelated-request-after-error")
    assert caught.value.code == code
    assert "unrelated-request-after-error" in caplog.text
    assert FAKE_KEY not in caplog.text + "".join(traceback.format_exception(caught.value))
    assert "private-provider-detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_log_suppression_is_local_to_the_opendart_task(caplog):
    caplog.set_level(logging.DEBUG)
    entered, resume = asyncio.Event(), asyncio.Event()

    async def handler(request):
        entered.set()
        await resume.wait()
        logging.getLogger("httpx").info("private %s", FAKE_KEY)
        return httpx.Response(200, json=payload(request.url.params["bsns_year"]))

    task = asyncio.create_task(adapter(handler).fetch_revenue(2022, 2024))
    await entered.wait()
    logging.getLogger("httpx").info("unrelated-concurrent-request")
    resume.set()
    await task
    assert "unrelated-concurrent-request" in caplog.text and FAKE_KEY not in caplog.text


@pytest.mark.asyncio
async def test_stalled_body_has_total_deadline_and_closes_stream():
    class StalledBody(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"{"
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    body = StalledBody()
    with pytest.raises(OpenDartError) as caught:
        await adapter(lambda request: httpx.Response(200, stream=body),
                      timeout_seconds=1).fetch_revenue(2022, 2024)
    assert caught.value.code == "timeout" and body.closed


@pytest.mark.asyncio
async def test_cancellation_closes_transport_and_does_not_start_second_year(caplog):
    entered = asyncio.Event()
    calls = []
    caplog.set_level(logging.INFO)

    async def handler(request):
        calls.append(request)
        entered.set()
        await asyncio.Event().wait()

    class TrackedTransport(httpx.MockTransport):
        closed = False

        async def aclose(self):
            self.closed = True

    transport = TrackedTransport(handler)

    async def run():
        try:
            await adapter(handler, transport=transport).fetch_revenue(2022, 2024)
        finally:
            logging.getLogger("httpx").info("after-cancel-in-same-task")

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.closed and len(calls) == 1
    assert "after-cancel-in-same-task" in caplog.text


@pytest.mark.asyncio
async def test_company_scaffold_uses_safe_errors_and_explicit_activation():
    with pytest.raises(OpenDartError) as caught:
        await OpenDartClient(FAKE_KEY).company("00126380")
    assert caught.value.code == "disabled"
    with pytest.raises(OpenDartError) as caught:
        await adapter(lambda request: httpx.Response(200, json={
            "status": "010", "message": FAKE_KEY,
        })).company("00126380")
    assert caught.value.code == "authentication" and FAKE_KEY not in str(caught.value)


def test_participant_routes_remain_mock_even_with_gemini_enabled(monkeypatch):
    monkeypatch.setattr(main.settings, "live_api_enabled", True)
    monkeypatch.setattr(main.settings, "gemini_planner_enabled", True)
    monkeypatch.setattr(OpenDartClient, "__init__", lambda *args, **kwargs: pytest.fail(
        "Participant routes must not construct OpenDART in this slice",
    ))
    api = TestClient(main.app)
    question = "삼성전자 매출액 2022-2024 증감률 연결 연간 비교"
    plan = api.post("/api/v1/plan", json={"question": question}).json()
    conditions = {key: plan["query_plan"][key] for key in (
        "selected_source", "entity", "metric", "period", "comparison", "filters",
    )}
    response = api.post("/api/v1/execute", json={
        "question": question, "mode": "mock", "approved": True, "conditions": conditions,
    })
    assert response.status_code == 200
    assert response.json()["evidence"]["data_mode"] == "mock"
    assert response.json()["brief"]["verification_status"] == "review_required"
    assert api.post("/api/v1/execute", json={
        "question": question, "mode": "live", "approved": True, "conditions": conditions,
    }).status_code == 422

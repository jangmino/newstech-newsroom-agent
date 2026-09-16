"""KOSIS transport behavior with public fixtures and mocked HTTP, never live credentials."""

import asyncio
import json
import logging
import traceback
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.kosis_employment import EmploymentQuery, KosisError

FIXTURE = json.loads((Path(__file__).parents[1] / "src/newsroom_agent/snapshot_data/"
                     "kosis-youth-employment-2020-2024.json").read_text())
NOW = datetime(2026, 9, 16, 13, 0, tzinfo=UTC)
FAKE_KEY = "offline-only-kosis-credential"
QUERY = EmploymentQuery(entity="전국 시·도", metric="고용률", age_range="15-29세",
                        start_year=2020, end_year=2024)


def adapter(handler, **options):
    return KosisClient(**({
        "api_key": FAKE_KEY, "transport": httpx.MockTransport(handler),
        "enabled": True, "clock": lambda: NOW,
    } | options))


@pytest.mark.asyncio
async def test_single_bounded_request_preserves_contract_and_hides_transport_logs(caplog):
    caplog.set_level(logging.DEBUG)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.scheme == "https" and request.url.host == "kosis.kr"
        assert request.url.path == "/openapi/Param/statisticsParameterData.do"
        assert dict(request.url.params) == {**FIXTURE["request"]["parameters"], "apiKey": FAKE_KEY}
        assert set(request.extensions["timeout"].values()) == {20}
        logging.getLogger("httpcore.http11").debug("sensitive %s", FAKE_KEY)
        return httpx.Response(200, json=FIXTURE["rows"])

    client = adapter(handler)
    result = await client.fetch_employment(QUERY)
    assert len(calls) == 1 and len(result.observations) == 85
    assert result.retrieved_at == NOW
    assert result.observations[0].raw_value == "46.6"
    assert FAKE_KEY not in repr(result) + repr(client) + caplog.text
    assert "apiKey" not in caplog.text
    logging.getLogger("httpx").info("unrelated request remains visible")
    assert "unrelated request remains visible" in caplog.text


@pytest.mark.parametrize("status,code", [
    ("10", "authentication"), ("11", "authentication"), ("12", "authentication"),
    ("20", "invalid_request"), ("21", "invalid_request"), ("30", "no_data"),
    (30, "no_data"), ("31", "invalid_request"), ("40", "rate_limited"),
    ("41", "rate_limited"), ("42", "authentication"), ("50", "unavailable"),
    ("999", "invalid_response"), (True, "invalid_response"),
])
@pytest.mark.asyncio
async def test_provider_errors_are_fixed_messages_without_retry(status, code, caplog):
    caplog.set_level(logging.DEBUG)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"err": status, "errMsg": f"private {FAKE_KEY}"})

    with pytest.raises(KosisError) as caught:
        await adapter(handler).fetch_employment(QUERY)
    assert caught.value.code == code and len(calls) == 1
    output = "".join(traceback.format_exception(caught.value)) + caplog.text
    assert FAKE_KEY not in output and "private" not in output


@pytest.mark.parametrize("status,code", [
    (301, "unavailable"), (302, "unavailable"), (400, "invalid_request"),
    (401, "authentication"), (403, "authentication"), (408, "timeout"),
    (429, "rate_limited"), (500, "unavailable"), (503, "unavailable"), (504, "timeout"),
])
@pytest.mark.asyncio
async def test_http_errors_and_redirects_are_not_followed_or_retried(status, code, caplog):
    caplog.set_level(logging.DEBUG)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=FAKE_KEY, headers={
            "Location": f"https://invalid.test/?apiKey={FAKE_KEY}",
        })

    with pytest.raises(KosisError) as caught:
        await adapter(handler).fetch_employment(QUERY)
    assert caught.value.code == code and len(calls) == 1
    assert FAKE_KEY not in str(caught.value) + caplog.text


@pytest.mark.parametrize("raw,code", [
    (b"not json", "invalid_response"), (b"[]", "no_data"), (b"{}", "invalid_response"),
    (b"[null]", "invalid_response"), (b"[NaN]", "invalid_response"),
    (b'{"err":30,"err":11}', "invalid_response"),
    (b'[{"ORG_ID":"101","ORG_ID":"999"}]', "invalid_response"),
    (b" " * 2_000_001, "invalid_response"),
])
@pytest.mark.asyncio
async def test_invalid_json_and_oversized_payloads_stop(raw, code):
    with pytest.raises(KosisError) as caught:
        await adapter(lambda request: httpx.Response(200, content=raw)).fetch_employment(QUERY)
    assert caught.value.code == code


@pytest.mark.parametrize("options,code", [
    ({"enabled": False}, "disabled"), ({"enabled": "true"}, "disabled"),
    ({"api_key": ""}, "configuration"), ({"api_key": "  "}, "configuration"),
    ({"timeout_seconds": 0}, "configuration"), ({"timeout_seconds": True}, "configuration"),
    ({"timeout_seconds": float("inf")}, "configuration"),
])
@pytest.mark.asyncio
async def test_configuration_is_checked_before_transport(options, code):
    with pytest.raises(KosisError) as caught:
        client = adapter(lambda request: pytest.fail("No request allowed"), **options)
        await client.fetch_employment(QUERY)
    assert caught.value.code == code


@pytest.mark.parametrize("exception,code", [
    (httpx.ReadTimeout, "timeout"), (httpx.ConnectTimeout, "timeout"),
    (TimeoutError, "timeout"), (httpx.ConnectError, "unavailable"),
    (RuntimeError, "unavailable"),
])
@pytest.mark.asyncio
async def test_transport_exceptions_never_expose_original_details(exception, code, caplog):
    def handler(request):
        raise exception(f"private exception {FAKE_KEY}")

    with pytest.raises(KosisError) as caught:
        await adapter(handler).fetch_employment(QUERY)
    assert caught.value.code == code
    assert FAKE_KEY not in "".join(traceback.format_exception(caught.value)) + caplog.text


@pytest.mark.asyncio
async def test_whole_response_timeout_closes_stream():
    class SlowBody(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"["
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    body = SlowBody()
    with pytest.raises(KosisError) as caught:
        await adapter(lambda request: httpx.Response(200, stream=body), timeout_seconds=1
                      ).fetch_employment(QUERY)
    assert caught.value.code == "timeout" and body.closed


@pytest.mark.asyncio
async def test_proxy_environment_and_http_retries_are_disabled(monkeypatch):
    real_client = httpx.AsyncClient
    captured = []

    def client(**kwargs):
        captured.append(kwargs)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setenv("HTTPS_PROXY", "http://unused-proxy.invalid")
    await adapter(lambda request: httpx.Response(200, json=FIXTURE["rows"])).fetch_employment(QUERY)
    assert captured[0]["trust_env"] is False and captured[0]["follow_redirects"] is False


@pytest.mark.asyncio
async def test_bad_data_does_not_return_partial_values():
    with pytest.raises(KosisError) as caught:
        await adapter(lambda request: httpx.Response(200, json=FIXTURE["rows"][1:])
                      ).fetch_employment(QUERY)
    assert caught.value.code == "incomplete_series"

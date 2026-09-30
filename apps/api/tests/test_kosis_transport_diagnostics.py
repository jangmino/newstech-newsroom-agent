"""Offline transport diagnosis must never serialize credential-bearing trace data."""

import json

import httpx
import pytest

from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.kosis_employment import KosisError
from newsroom_agent.request_logging import LOGGER, record_kosis_timeout


@pytest.mark.asyncio
@pytest.mark.parametrize("event,phase", [
    ("connection.connect_tcp.started", "connect"),
    ("connection.start_tls.started", "tls"),
    ("http11.send_request_headers.started", "request"),
    ("http11.receive_response_headers.started", "response_headers"),
    ("http11.receive_response_body.started", "response_body"),
    ("secret-not-an-event", "client"),
])
async def test_timeout_records_only_fixed_phase(monkeypatch, event, phase):
    logs = []
    monkeypatch.setattr(LOGGER, "warning", logs.append)

    async def transport(request):
        await request.extensions["trace"](event, {
            "url": "https://kosis.kr/?apiKey=secret-test-key",
            "exception": RuntimeError("secret-exception"),
        })
        # Cleanup events must not obscure the phase that timed out.
        await request.extensions["trace"]("http11.response_closed.complete", {})
        raise httpx.ReadTimeout("secret-test-key")

    client = KosisClient("secret-test-key", enabled=True, transport=httpx.MockTransport(transport))
    with pytest.raises(KosisError) as exc:
        await client.fetch_parameters({})
    assert exc.value.code == "timeout"
    assert len(logs) == 1 and "secret" not in logs[0] and "https" not in logs[0]
    record = json.loads(logs[0])
    assert record["event"] == "provider_transport_timeout" and record["phase"] == phase
    assert set(record) == {"timestamp", "severity", "event", "request_id", "provider", "phase"}


def test_unknown_diagnostic_phase_is_not_echoed(monkeypatch):
    logs = []
    monkeypatch.setattr(LOGGER, "warning", logs.append)
    record_kosis_timeout("secret-invalid-phase")
    assert json.loads(logs[0])["phase"] == "unknown"
    assert "secret" not in logs[0]

from datetime import datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from newsroom_agent import main, operations
from newsroom_agent.providers import snapshot

client = TestClient(main.app)


def configure(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setattr(main.settings, name, value)


def test_default_contract_has_no_evidence_and_uses_bundled_snapshots():
    response = client.get("/api/v1/operations")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "X-Workshop-Code" in response.headers["vary"]
    assert response.headers["x-request-id"]
    body = response.json()
    assert set(body) == {"checked_at", "external_calls_made", "providers", "snapshots",
                         "cache", "limits", "briefing"}
    assert body["briefing"] == "disabled"
    assert datetime.fromisoformat(body["checked_at"]).utcoffset() is not None
    assert body["external_calls_made"] is False
    assert body["providers"] == dict.fromkeys(("gemini", "opendart", "kosis"), "disabled")
    for source, data in body["snapshots"].items():
        assert data == {"status": "available", "metadata": snapshot.load_snapshot(source)
                       .metadata.model_dump()}
    assert body["cache"] == {"scope": "process", "enabled": False, "ttl_seconds": 3600,
                             "max_entries_per_source": 64}
    assert body["limits"] == {
        "scope": "process", "window_seconds": 60,
        "gemini": {"requests_per_minute": 30, "max_concurrent_requests": 8},
        "public_data_per_source": {"requests_per_minute": 30, "max_concurrent_requests": 2},
    }
    for field in ("raw_values", "brief", "observations", "amount", "query_plan"):
        assert f'"{field}"' not in response.text


@pytest.mark.parametrize("source", ["gemini", "opendart", "kosis"])
@pytest.mark.parametrize("enabled,key,expected", [
    (False, "synthetic-secret", "disabled"),
    (True, "  ", "missing_configuration"),
    (True, "synthetic-secret", "configured"),
])
def test_provider_flags_and_configuration(monkeypatch, source, enabled, key, expected):
    configure(monkeypatch, live_api_enabled=True, public_data_mode="live")
    flag = "gemini_planner_enabled" if source == "gemini" else f"{source}_enabled"
    configure(monkeypatch, **{flag: enabled, f"{source}_api_key": key})
    body = client.get("/api/v1/operations").json()
    assert body["providers"][source] == expected
    assert [state for name, state in body["providers"].items() if name != source] == [
        "disabled", "disabled",
    ]


@pytest.mark.parametrize("live,mode,expected", [
    (False, "live", ("disabled", "disabled")),
    (True, "mock", ("configured", "disabled")),
    (True, "live", ("configured", "configured")),
])
def test_global_gate_and_public_mode_are_independent(monkeypatch, live, mode, expected):
    configure(monkeypatch, live_api_enabled=live, public_data_mode=mode,
              gemini_planner_enabled=True, gemini_api_key="synthetic-gemini",
              opendart_enabled=True, opendart_api_key="synthetic-dart",
              kosis_enabled=True, kosis_api_key="synthetic-kosis")
    providers = client.get("/api/v1/operations").json()["providers"]
    assert providers == {"gemini": expected[0], "opendart": expected[1], "kosis": expected[1]}


@pytest.mark.parametrize("auth,project,location,expected", [
    ("vertex_ai", "synthetic-project", "asia-northeast3", "configured"),
    ("vertex_ai", " ", "asia-northeast3", "missing_configuration"),
    ("vertex_ai", "synthetic-project", " ", "missing_configuration"),
    ("unknown", "synthetic-project", "asia-northeast3", "missing_configuration"),
])
def test_vertex_checks_configuration_only(monkeypatch, auth, project, location, expected):
    configure(monkeypatch, live_api_enabled=True, gemini_planner_enabled=True,
              gemini_auth_mode=auth, google_cloud_project=project, google_cloud_location=location)
    response = client.get("/api/v1/operations")
    assert response.json()["providers"]["gemini"] == expected
    assert "synthetic-project" not in response.text


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
def test_snapshot_failure_is_isolated_and_sanitized(monkeypatch, failure):
    original = snapshot._read

    def read(filename):
        if filename.startswith("kosis"):
            if failure == "missing":
                raise OSError("private-file-path-secret")
            return b"private-file-content-secret"
        return original(filename)

    monkeypatch.setattr(snapshot, "_read", read)
    response = client.get("/api/v1/operations")
    assert response.status_code == 200
    assert response.json()["snapshots"]["kosis"] == {"status": "unavailable", "metadata": None}
    assert response.json()["snapshots"]["opendart"]["status"] == "available"
    assert "private-file" not in response.text


def test_disabled_snapshot_does_not_read_files(monkeypatch):
    configure(monkeypatch, fallback_snapshot_enabled=False)
    loader = Mock(side_effect=AssertionError("must not load disabled snapshots"))
    monkeypatch.setattr(operations, "load_snapshot", loader)
    assert client.get("/api/v1/operations").json()["snapshots"] == {
        source: {"status": "disabled", "metadata": None} for source in ("opendart", "kosis")
    }
    loader.assert_not_called()


def test_live_settings_do_not_probe_providers_mutate_caches_or_disclose_secrets(monkeypatch):
    code = "synthetic-workshop-code"
    secrets = ["synthetic-gemini-key", "synthetic-dart-key", "synthetic-kosis-key", code,
               "private-project", "private-location", "private-model"]
    configure(monkeypatch, live_api_enabled=True, public_data_mode="live",
              gemini_planner_enabled=True, opendart_enabled=True, kosis_enabled=True,
              gemini_api_key=secrets[0], opendart_api_key=secrets[1], kosis_api_key=secrets[2],
              workshop_access_code=code, google_cloud_project=secrets[4],
              google_cloud_location=secrets[5], gemini_model=secrets[6],
              public_data_cache_enabled=True, cache_ttl_seconds=123, cache_max_entries=9,
              requests_per_minute=11, max_concurrent_requests=3,
              public_data_requests_per_minute=13, public_data_max_concurrent_requests=4)
    blocked = Mock(side_effect=AssertionError("no runtime provider/cache/limiter work"))
    for name in ("get_question_planner", "get_gemini_limiter", "get_public_data_limiter",
                 "OpenDartClient", "KosisClient"):
        monkeypatch.setattr(main, name, blocked)
    for name in ("employment_cache", "revenue_cache"):
        monkeypatch.setattr(main.app.state, name, blocked, raising=False)
    for _ in range(2):
        response = client.get("/api/v1/operations", headers={"X-Workshop-Code": code})
        assert response.status_code == 200
        assert all(secret not in response.text for secret in secrets)
        body = response.json()
        assert body["cache"] == {"scope": "process", "enabled": True, "ttl_seconds": 123,
                                 "max_entries_per_source": 9}
        assert body["limits"]["gemini"] == {"requests_per_minute": 11, "max_concurrent_requests": 3}
        assert body["limits"]["public_data_per_source"] == {
            "requests_per_minute": 13, "max_concurrent_requests": 4,
        }
    assert blocked.mock_calls == []


@pytest.mark.parametrize("env,code,header,status", [
    ("test", "synthetic-workshop-code", None, 401),
    ("test", "synthetic-workshop-code", "wrong-synthetic-code", 401),
    ("stage", "", None, 503),
])
def test_access_guard_runs_before_status_checks(monkeypatch, env, code, header, status):
    configure(monkeypatch, app_env=env, workshop_access_code=code)
    check = Mock(side_effect=AssertionError("unauthorized status check"))
    monkeypatch.setattr(main, "operations_status", check)
    response = client.get(
        "/api/v1/operations", headers={"X-Workshop-Code": header} if header else {},
    )
    assert response.status_code == status
    check.assert_not_called()


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_operations_are_read_only(method):
    assert getattr(client, method)("/api/v1/operations").status_code == 405

"""Install public test settings before app import; never load .env or credentials."""

import socket
from types import SimpleNamespace

import pytest

from newsroom_agent import config

_patch = pytest.MonkeyPatch()


def pytest_configure() -> None:
    settings = SimpleNamespace(
        app_env="test",
        workshop_access_code="",
        public_data_mode="mock",
        live_api_enabled=False,
        fallback_snapshot_enabled=True,
        opendart_enabled=False, opendart_api_key="",
        kosis_enabled=False, kosis_api_key="",
        gemini_planner_enabled=False,
        gemini_auth_mode="api_key", gemini_api_key="", gemini_model="gemini-3.8-flash",
        gemini_timeout_ms=20_000, gemini_max_output_tokens=2048,
        google_cloud_project="", google_cloud_location="asia-northeast3",
        requests_per_minute=30, max_concurrent_requests=8,
        public_data_requests_per_minute=30, public_data_max_concurrent_requests=2,
        public_data_cache_enabled=False, cache_ttl_seconds=3600, cache_max_entries=64,
        cors_origin_list=["http://localhost:5173"],
    )
    _patch.setattr(config, "get_settings", lambda: settings)

    def forbid_settings(*args, **kwargs):
        raise AssertionError("Tests must not load environment files or credentials")

    _patch.setattr(config, "Settings", forbid_settings)
    for name in ("connect", "connect_ex"):
        original = getattr(socket.socket, name)

        def guarded_connect(self, address, _original=original):
            if self.family in (socket.AF_INET, socket.AF_INET6):
                raise AssertionError("External network calls are forbidden in tests")
            return _original(self, address)

        _patch.setattr(socket.socket, name, guarded_connect)


def pytest_unconfigure() -> None:
    _patch.undo()

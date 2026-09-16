"""Install public test settings before app import; never load .env or credentials."""

import socket
from types import SimpleNamespace

import pytest

from newsroom_agent import config

_patch = pytest.MonkeyPatch()


def pytest_configure() -> None:
    settings = SimpleNamespace(
        app_env="test",
        public_data_mode="mock",
        live_api_enabled=False,
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

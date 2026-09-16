"""Read-only, allowlisted configuration summary; never probe external providers."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from newsroom_agent.config import Settings
from newsroom_agent.models import SnapshotMetadata
from newsroom_agent.providers.snapshot import SnapshotError, load_snapshot

ProviderState = Literal["disabled", "missing_configuration", "configured"]


class ProviderStatuses(BaseModel):
    gemini: ProviderState
    opendart: ProviderState
    kosis: ProviderState


class SnapshotStatus(BaseModel):
    status: Literal["disabled", "unavailable", "available"]
    metadata: SnapshotMetadata | None = None


class SnapshotStatuses(BaseModel):
    opendart: SnapshotStatus
    kosis: SnapshotStatus


class CacheSettings(BaseModel):
    scope: Literal["process"] = "process"
    enabled: bool
    ttl_seconds: int
    max_entries_per_source: int


class CallLimitSettings(BaseModel):
    requests_per_minute: int
    max_concurrent_requests: int


class LimitSettings(BaseModel):
    scope: Literal["process"] = "process"
    window_seconds: Literal[60] = 60
    gemini: CallLimitSettings
    public_data_per_source: CallLimitSettings


class OperationsStatus(BaseModel):
    checked_at: str
    external_calls_made: Literal[False] = False
    providers: ProviderStatuses
    snapshots: SnapshotStatuses
    cache: CacheSettings
    limits: LimitSettings


def _provider_state(enabled: bool, configured: bool) -> ProviderState:
    if not enabled:
        return "disabled"
    return "configured" if configured else "missing_configuration"


def _snapshot_status(source: str, enabled: bool) -> SnapshotStatus:
    if not enabled:
        return SnapshotStatus(status="disabled")
    try:
        return SnapshotStatus(status="available", metadata=load_snapshot(source).metadata)
    except SnapshotError:
        return SnapshotStatus(status="unavailable")


def operations_status(settings: Settings) -> OperationsStatus:
    public_live = settings.live_api_enabled and settings.public_data_mode == "live"
    gemini_configured = (
        settings.gemini_auth_mode == "api_key" and bool(settings.gemini_api_key.strip())
    ) or (
        settings.gemini_auth_mode == "vertex_ai"
        and bool(settings.google_cloud_project.strip())
        and bool(settings.google_cloud_location.strip())
    )
    return OperationsStatus(
        checked_at=datetime.now(UTC).isoformat(),
        providers=ProviderStatuses(
            gemini=_provider_state(
                settings.live_api_enabled and settings.gemini_planner_enabled, gemini_configured,
            ),
            opendart=_provider_state(
                public_live and settings.opendart_enabled, bool(settings.opendart_api_key.strip()),
            ),
            kosis=_provider_state(
                public_live and settings.kosis_enabled, bool(settings.kosis_api_key.strip()),
            ),
        ),
        snapshots=SnapshotStatuses(
            opendart=_snapshot_status("opendart", settings.fallback_snapshot_enabled),
            kosis=_snapshot_status("kosis", settings.fallback_snapshot_enabled),
        ),
        cache=CacheSettings(
            enabled=settings.public_data_cache_enabled, ttl_seconds=settings.cache_ttl_seconds,
            max_entries_per_source=settings.cache_max_entries,
        ),
        limits=LimitSettings(
            gemini=CallLimitSettings(
                requests_per_minute=settings.requests_per_minute,
                max_concurrent_requests=settings.max_concurrent_requests,
            ),
            public_data_per_source=CallLimitSettings(
                requests_per_minute=settings.public_data_requests_per_minute,
                max_concurrent_requests=settings.public_data_max_concurrent_requests,
            ),
        ),
    )

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(Path.cwd() / ".env", Path.cwd() / "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"
    public_data_mode: str = "mock"
    live_api_enabled: bool = False
    fallback_snapshot_enabled: bool = True
    workshop_access_code: str = Field(default="", repr=False)
    cors_origins: str = "http://localhost:5173"

    gemini_auth_mode: str = "api_key"
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model: str = "gemini-3.8-flash"
    gemini_planner_enabled: bool = False
    gemini_briefing_enabled: bool = False
    gemini_timeout_ms: int = Field(default=20_000, ge=1000, le=60_000)
    gemini_max_output_tokens: int = Field(default=2048, ge=256, le=4096)
    google_cloud_project: str = ""
    google_cloud_location: str = "asia-northeast3"

    opendart_api_key: str = Field(default="", repr=False)
    opendart_enabled: bool = False
    kosis_api_key: str = Field(default="", repr=False)
    kosis_enabled: bool = False

    requests_per_minute: int = Field(default=30, ge=1, le=300)
    max_concurrent_requests: int = Field(default=8, ge=1, le=30)
    public_data_requests_per_minute: int = Field(default=30, ge=1, le=300)
    public_data_max_concurrent_requests: int = Field(default=2, ge=1, le=30)
    public_data_cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=3600, ge=1, le=86400)
    cache_max_entries: int = Field(default=64, ge=1, le=256)

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REPOVOX_", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["development", "test", "production"] = "production"
    dev_auth: bool = False
    fixtures: bool = False
    analysis: bool = False
    github_token: SecretStr | None = None
    database_url: SecretStr
    worker_database_url: SecretStr | None = None
    # Product video generation lives in a separate media database with its own roles.
    video: bool = False
    media_database_url: SecretStr | None = None
    media_worker_database_url: SecretStr | None = None
    # Seconds between analysis-to-media handoff passes in the API process; 0 turns it off.
    media_handoff_seconds: float = Field(default=3, ge=0, le=300)
    # Development and test only: serve locally authored synthetic repositories from this
    # directory instead of acquiring anything from GitHub.
    synthetic_source_dir: str | None = None
    session_secret: SecretStr = Field(min_length=32)
    session_seconds: int = Field(default=3600, ge=60, le=86400)
    origin: str = "http://localhost:3000"
    redis_url: str = "redis://redis:6379/0"
    storage_endpoint: str = "http://storage:8333"
    storage_access_key: SecretStr
    storage_secret_key: SecretStr
    storage_bucket: str = "repovox-private"

    @model_validator(mode="after")
    def fail_closed(self) -> "Settings":
        if self.environment == "production":
            raise ValueError(
                "Phase 1 has no production identity adapter; production boot is disabled"
            )
        if not self.synthetic_source_dir:
            self.synthetic_source_dir = None  # An empty setting means it is off.
        if self.synthetic_source_dir is not None and not self.fixtures:
            raise ValueError("Synthetic source requires the development fixture mode")
        if not self.dev_auth:
            raise ValueError("An explicitly enabled development identity adapter is required")
        if self.origin not in {"http://localhost:3000", "http://127.0.0.1:3000"}:
            raise ValueError("Phase 1 requires an authorized local browser origin")
        return self

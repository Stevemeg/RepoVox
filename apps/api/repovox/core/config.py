from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The only browser origins a deployment without TLS may use, and only on this host.
LOOPBACK_ORIGINS = frozenset({"http://localhost:3000", "http://127.0.0.1:3000"})


def https_origin(value: str) -> bool:
    """An exact `https://host[:port]` origin: no path, query, fragment, user info or wildcard."""
    try:
        parts = urlsplit(value)
        port = parts.port  # Raises on a malformed port.
    except ValueError:
        return False
    host = parts.hostname or ""
    if parts.scheme != "https" or not host or "*" in value or parts.username or parts.password:
        return False
    if parts.path or parts.query or parts.fragment or value.endswith(("?", "#")):
        return False
    return value == f"https://{host}" + (f":{port}" if port is not None else "")


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
    # Seconds between analysis-to-media handoff passes in the API process; 0 turns that pass
    # off. The dispatcher runs the same pass every five seconds regardless.
    media_handoff_seconds: float = Field(default=3, ge=0, le=300)
    # Development and test only: serve locally authored synthetic repositories from this
    # directory instead of acquiring anything from GitHub.
    synthetic_source_dir: str | None = None
    session_secret: SecretStr = Field(min_length=32)
    session_seconds: int = Field(default=3600, ge=60, le=86400)
    origin: str = "http://localhost:3000"
    # Production may use a loopback origin over plain HTTP only when this is set explicitly.
    allow_loopback_origin: bool = False
    # Identity adapter: "dev" signs in seeded development identities; "github" signs in
    # operator-provisioned GitHub accounts through OAuth 2.0.
    auth_provider: Literal["dev", "github"] = "dev"
    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None
    redis_url: str = "redis://redis:6379/0"
    storage_endpoint: str = "http://storage:8333"
    storage_access_key: SecretStr
    storage_secret_key: SecretStr
    storage_bucket: str = "repovox-private"

    @property
    def github_configured(self) -> bool:
        secret = self.github_client_secret.get_secret_value() if self.github_client_secret else ""
        return bool((self.github_client_id or "").strip() and secret.strip())

    @model_validator(mode="after")
    def fail_closed(self) -> "Settings":
        if not self.synthetic_source_dir:
            self.synthetic_source_dir = None  # An empty setting means it is off.
        if self.environment == "production":
            # Every check refuses to start rather than run with a weaker identity boundary.
            if self.dev_auth:
                raise ValueError("Production forbids the development identity adapter")
            if self.fixtures or self.synthetic_source_dir is not None:
                raise ValueError("Production forbids fixtures and synthetic sources")
            if self.auth_provider != "github" or not self.github_configured:
                raise ValueError(
                    "Production requires the GitHub identity adapter with a client id and secret"
                )
            if not https_origin(self.origin) and not (
                self.allow_loopback_origin and self.origin in LOOPBACK_ORIGINS
            ):
                raise ValueError("Production requires an exact https:// browser origin")
            return self
        if self.synthetic_source_dir is not None and not self.fixtures:
            raise ValueError("Synthetic source requires the development fixture mode")
        if self.auth_provider == "github":
            # Development and test may exercise the GitHub adapter, never alongside the
            # development identities.
            if self.dev_auth:
                raise ValueError("The GitHub identity adapter excludes development identities")
            if not self.github_configured:
                raise ValueError("The GitHub identity adapter requires a client id and secret")
            if self.origin not in LOOPBACK_ORIGINS and not https_origin(self.origin):
                raise ValueError("The GitHub identity adapter requires a local or https origin")
            return self
        if not self.dev_auth:
            raise ValueError("An explicitly enabled development identity adapter is required")
        if self.origin not in LOOPBACK_ORIGINS:
            raise ValueError("Phase 1 requires an authorized local browser origin")
        return self

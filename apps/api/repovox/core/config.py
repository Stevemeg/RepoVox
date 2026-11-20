import os
import re
from pathlib import PurePath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The only browser origins a deployment without TLS may use, and only on this host.
LOOPBACK_ORIGINS = frozenset({"http://localhost:3000", "http://127.0.0.1:3000"})
LLMProvider = Literal["deterministic", "ollama", "openai_compatible", "anthropic"]
# Endpoints used when REPOVOX_LLM_BASE_URL is not set.
LLM_BASE_URLS: dict[str, str] = {
    "ollama": "http://127.0.0.1:11434",
    "openai_compatible": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
}
# Hosts a narration model may be reached on over plain HTTP: this machine, or the Docker host
# for a local Ollama. Every other host requires HTTPS.
LLM_PLAIN_HTTP_HOSTS = frozenset({"127.0.0.1", "localhost", "host.docker.internal"})
LLM_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}")
LLM_KEY = re.compile(r"[\x21-\x7e]{8,512}")


TTSProvider = Literal["auto", "deterministic", "kokoro_onnx"]
TTS_VOICE = r"^[a-z0-9_-]{2,32}$"


def neural_asset(value: str, suffix: str) -> bool:
    """An absolute local file path with the expected suffix: no NUL byte or `..` component."""
    if any(ord(c) < 32 for c in value) or not os.path.isabs(value):
        return False
    path = PurePath(value)
    return ".." not in path.parts and path.suffix.lower() == suffix


def llm_endpoint(value: str) -> bool:
    """`http(s)://host[:port][/path]`: no user info, query, fragment, wildcard or whitespace."""
    try:
        parts = urlsplit(value)
        port = parts.port  # Raises on a malformed port.
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not host or port == 0:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    if "@" in parts.netloc or "*" in value or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    if parts.query or parts.fragment or value.endswith(("?", "#")):
        return False
    return parts.scheme == "https" or host in LLM_PLAIN_HTTP_HOSTS


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
    # Optional narration refinement. The default rewords nothing and makes no network call; a
    # model only ever sees the verified storyboard plan, outside the parser sandbox.
    llm_provider: LLMProvider = "deterministic"
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    # Unset: hosted providers receive no sampling parameter, which current reasoning and
    # Claude models require; Ollama keeps temperature 0. Set only to send an explicit value.
    llm_temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    # Narration voice. "auto" uses the local Kokoro ONNX voice only when its package and both
    # operator-supplied files are present, and the operating-system voice otherwise;
    # "kokoro_onnx" requires it and fails the speech stage without it. Nothing is downloaded.
    tts_provider: TTSProvider = "auto"
    tts_model_path: str | None = None
    tts_voices_path: str | None = None
    tts_voice: str = Field(default="af_heart", pattern=TTS_VOICE)
    tts_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    # Neural voice inference threads; unset keeps the runtime default (every host core). Set
    # it to the media worker's CPU allocation.
    tts_threads: int | None = Field(default=None, ge=1, le=64)
    # Seconds the narration stage may spend, after its own checks, speaking the approved
    # script ahead into the media worker's in-memory speech cache; 0 turns this off. Every
    # media stage stays bounded by its own lease and deadline.
    media_speech_prewarm_seconds: float = Field(default=240, ge=0, le=300)
    # Encoder and probe time limit for one video: base plus a share per minute of video,
    # capped. A media stage's own deadline still bounds the whole stage.
    media_encode_base_seconds: float = Field(default=170, ge=30, le=1800)
    media_encode_seconds_per_minute: float = Field(default=30, ge=0, le=600)
    media_encode_max_seconds: float = Field(default=900, ge=30, le=3600)

    @model_validator(mode="after")
    def tts_fail_closed(self) -> "Settings":
        """Refuse an explicitly demanded neural voice without its files, or unsafe file paths."""
        self.tts_model_path = (self.tts_model_path or "").strip() or None
        self.tts_voices_path = (self.tts_voices_path or "").strip() or None
        model, voices = self.tts_model_path, self.tts_voices_path
        if model is not None and not neural_asset(model, ".onnx"):
            raise ValueError("The neural voice model path must be an absolute .onnx file path")
        if voices is not None and not neural_asset(voices, ".bin"):
            raise ValueError("The neural voice file path must be an absolute .bin file path")
        if (model is None) != (voices is None):
            raise ValueError("The neural voice needs both its model and its voices file")
        if self.tts_provider == "kokoro_onnx" and model is None:
            raise ValueError("The kokoro_onnx voice requires its model and voices files")
        return self

    @property
    def llm_endpoint(self) -> str | None:
        """The narration model endpoint, or None when narration stays deterministic."""
        if self.llm_provider == "deterministic":
            return None
        return (self.llm_base_url or LLM_BASE_URLS[self.llm_provider]).rstrip("/")

    @model_validator(mode="after")
    def llm_fail_closed(self) -> "Settings":
        """Refuse to start with a narration model that is incomplete or reached insecurely."""
        self.llm_model = (self.llm_model or "").strip() or None
        self.llm_base_url = (self.llm_base_url or "").strip() or None
        key = self.llm_api_key.get_secret_value() if self.llm_api_key else ""
        if not key.strip():
            self.llm_api_key = None
        if self.llm_base_url is not None and not llm_endpoint(self.llm_base_url):
            raise ValueError(
                "The narration model URL must be https://, or http:// only on 127.0.0.1, "
                "localhost or host.docker.internal, without credentials, query or fragment"
            )
        if self.llm_provider == "deterministic":
            return self
        if self.llm_model is None or not LLM_MODEL.fullmatch(self.llm_model):
            raise ValueError("The narration model provider requires a model name")
        if self.llm_provider in {"openai_compatible", "anthropic"}:
            if self.llm_api_key is None:
                raise ValueError("The hosted narration model provider requires an API key")
            if not LLM_KEY.fullmatch(self.llm_api_key.get_secret_value()):
                raise ValueError("The narration model API key is malformed")
        return self

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

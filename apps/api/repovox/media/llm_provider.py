"""Narration model adapters: one bounded JSON request per storyboard, fixed error codes only.

Used by `refiner.GroundedLLMRefiner`, outside the parser sandbox, on the verified storyboard
plan; never on repository files. Each adapter sends one request with no retries. Ollama always
sends a temperature (0 unless configured). Hosted adapters send one only when
`REPOVOX_LLM_TEMPERATURE` is set, because current Claude and OpenAI reasoning models reject a
sampling parameter with HTTP 400. Each adapter refuses redirects and ignores proxy,
certificate and netrc environment variables.
The connect, read and total time are bounded, and the response is read only up to
`RESPONSE_LIMIT` bytes. Timeouts, non-2xx answers and malformed bodies raise
`LLMProviderError` with a fixed code, so the caller can fall back to the deterministic
narration. The API key stays a `SecretStr` and is read only while one request header is built.
It never appears in a log, a repr, an error or an artifact.
"""

import json
import ssl
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import SecretStr

from repovox.core.config import Settings

RESPONSE_LIMIT = 1024 * 1024
CONNECT_SECONDS = 5.0
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 16000


class LLMProviderError(Exception):
    """Fixed code only; never response text, request text or a credential."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Provider(Protocol):
    """A chat model that answers one system and user message with text."""

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def complete(self, system: str, user: str) -> str: ...


@dataclass(frozen=True, repr=False)
class HTTPProvider:
    base_url: str
    model: str
    timeout: float
    api_key: SecretStr | None = None
    transport: httpx.BaseTransport | None = None  # Injected only by tests.
    temperature: float | None = None  # None: hosted adapters omit the parameter.

    name = "http"

    def __repr__(self) -> str:
        return f"{type(self).__name__}(model={self.model!r})"

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError

    def credential(self) -> str:
        if self.api_key is None:
            raise LLMProviderError("llm_not_configured")
        return self.api_key.get_secret_value()

    def post(self, path: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        """POST JSON and return the JSON object answered, within the time and size bounds."""
        deadline = time.monotonic() + self.timeout
        chunks: list[bytes] = []
        try:
            with (
                httpx.Client(
                    timeout=httpx.Timeout(self.timeout, connect=min(CONNECT_SECONDS, self.timeout)),
                    follow_redirects=False,
                    trust_env=False,
                    verify=ssl.create_default_context(),
                    transport=self.transport,
                ) as client,
                client.stream(
                    "POST",
                    self.base_url + path,
                    json=body,
                    headers={
                        **headers,
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                        "User-Agent": "RepoVox",
                    },
                ) as response,
            ):
                if not 200 <= response.status_code < 300:
                    raise LLMProviderError("llm_http_status")
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > RESPONSE_LIMIT:
                    raise LLMProviderError("llm_response_too_large")
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > RESPONSE_LIMIT:
                        raise LLMProviderError("llm_response_too_large")
                    if time.monotonic() > deadline:
                        raise LLMProviderError("llm_timeout")
                    chunks.append(chunk)
        except httpx.TimeoutException:
            raise LLMProviderError("llm_timeout") from None
        except httpx.HTTPError:
            raise LLMProviderError("llm_transport") from None
        if time.monotonic() > deadline:
            raise LLMProviderError("llm_timeout")
        try:
            data = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise LLMProviderError("llm_malformed_json") from None
        if not isinstance(data, dict):
            raise LLMProviderError("llm_malformed_json")
        return data

    def messages(self, system: str, user: str) -> list[dict[str, str]]:
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def sampling(self) -> dict[str, float]:
        """The sampling parameter for a hosted request: present only when configured."""
        return {} if self.temperature is None else {"temperature": self.temperature}


def text_of(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LLMProviderError("llm_malformed_response")
    return value


class OllamaProvider(HTTPProvider):
    """A local Ollama server: `POST /api/chat`, non-streaming, JSON format."""

    name = "ollama"

    def complete(self, system: str, user: str) -> str:
        data = self.post(
            "/api/chat",
            {},
            {
                "model": self.model,
                "messages": self.messages(system, user),
                "stream": False,
                "format": "json",
                "options": {"temperature": 0 if self.temperature is None else self.temperature},
            },
        )
        message = data.get("message")
        if data.get("done") is False or not isinstance(message, dict):
            raise LLMProviderError("llm_malformed_response")
        return text_of(message.get("content"))


class OpenAICompatibleProvider(HTTPProvider):
    """Any server implementing `POST /v1/chat/completions` with JSON object output."""

    name = "openai_compatible"

    def complete(self, system: str, user: str) -> str:
        data = self.post(
            "/v1/chat/completions",
            {"Authorization": f"Bearer {self.credential()}"},
            {
                "model": self.model,
                "messages": self.messages(system, user),
                **self.sampling(),
                "response_format": {"type": "json_object"},
            },
        )
        choices = data.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        if not isinstance(first, dict) or not isinstance(first.get("message"), dict):
            raise LLMProviderError("llm_malformed_response")
        if first.get("finish_reason") not in {None, "stop"}:
            raise LLMProviderError("llm_incomplete")
        return text_of(first["message"].get("content"))


class AnthropicProvider(HTTPProvider):
    """The Anthropic Messages API: `POST /v1/messages`; only text blocks are read."""

    name = "anthropic"

    def complete(self, system: str, user: str) -> str:
        data = self.post(
            "/v1/messages",
            {"x-api-key": self.credential(), "anthropic-version": ANTHROPIC_VERSION},
            {
                "model": self.model,
                "max_tokens": ANTHROPIC_MAX_TOKENS,
                **self.sampling(),
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        content = data.get("content")
        if not isinstance(content, list):
            raise LLMProviderError("llm_malformed_response")
        if data.get("stop_reason") not in {"end_turn", "stop_sequence"}:
            raise LLMProviderError("llm_incomplete")  # Truncated, refused or a tool call.
        texts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        return text_of("".join(texts))


PROVIDERS: dict[str, type[HTTPProvider]] = {
    "ollama": OllamaProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
}


def provider_from_settings(
    settings: Settings, transport: httpx.BaseTransport | None = None
) -> HTTPProvider | None:
    """The configured narration model, or None for deterministic narration."""
    endpoint = settings.llm_endpoint
    if endpoint is None:
        return None
    if settings.llm_model is None:
        raise LLMProviderError("llm_not_configured")  # Settings validation already refuses this.
    key = None if settings.llm_provider == "ollama" else settings.llm_api_key
    return PROVIDERS[settings.llm_provider](
        endpoint,
        settings.llm_model,
        settings.llm_timeout_seconds,
        key,
        transport,
        settings.llm_temperature,
    )


__all__ = [
    "AnthropicProvider",
    "HTTPProvider",
    "LLMProviderError",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "Provider",
    "provider_from_settings",
]

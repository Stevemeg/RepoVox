"""Production identity settings and the GitHub OAuth adapter, without a database or network.

GitHub is replaced by an httpx MockTransport; account lookup and session issue are replaced by
fakes. The real database path is covered by tests/integration/test_github_oauth.py.
"""

import base64
import hashlib
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from repovox.api import routes
from repovox.auth.github import (
    CALLBACK_PATH,
    STATE_COOKIE,
    VERIFIER_COOKIE,
    GitHubOAuth,
    owner_for,
)
from repovox.core.config import Settings, https_origin
from repovox.main import create_app

SECRET = "github-client-secret-" + "s" * 24
BASE: dict[str, Any] = {
    "database_url": "postgresql+psycopg://rv_app:p@localhost/repovox",
    "session_secret": "x" * 40,
    "storage_access_key": "a",
    "storage_secret_key": "s",
}
PRODUCTION: dict[str, Any] = {
    **BASE,
    "environment": "production",
    "dev_auth": False,
    "fixtures": False,
    "auth_provider": "github",
    "github_client_id": "Iv1.repovoxtest",
    "github_client_secret": SECRET,
    "origin": "https://repovox.example.test",
}
ORIGIN = PRODUCTION["origin"]


def test_production_accepts_github_oauth_on_an_https_origin() -> None:
    settings = Settings(**PRODUCTION)
    assert (settings.environment, settings.auth_provider, settings.github_configured) == (
        "production",
        "github",
        True,
    )
    assert Settings(**{**PRODUCTION, "origin": "https://repovox.example.test:8443"})


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"dev_auth": True}, "development identity adapter"),
        ({"fixtures": True}, "fixtures and synthetic sources"),
        ({"synthetic_source_dir": "/workspace/tests/fixtures"}, "fixtures and synthetic sources"),
        ({"auth_provider": "dev"}, "GitHub identity adapter"),
        ({"github_client_id": None}, "GitHub identity adapter"),
        ({"github_client_id": "   "}, "GitHub identity adapter"),
        ({"github_client_secret": None}, "GitHub identity adapter"),
        ({"github_client_secret": ""}, "GitHub identity adapter"),
        ({"origin": "http://repovox.example.test"}, "https:// browser origin"),
        ({"origin": "http://localhost:3000"}, "https:// browser origin"),
        ({"origin": "https://repovox.example.test/"}, "https:// browser origin"),
        ({"origin": "https://repovox.example.test/app"}, "https:// browser origin"),
        ({"origin": "https://repovox.example.test?next=/"}, "https:// browser origin"),
        ({"origin": "https://repovox.example.test#x"}, "https:// browser origin"),
        ({"origin": "https://*.example.test"}, "https:// browser origin"),
        ({"origin": "*"}, "https:// browser origin"),
        ({"origin": "https://user@repovox.example.test"}, "https:// browser origin"),
        ({"origin": "https://repovox.example.test:99999"}, "https:// browser origin"),
    ],
)
def test_production_fails_closed(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as failure:
        Settings(**{**PRODUCTION, **change})
    text = str(failure.value)
    assert message in text
    # Nothing secret reaches the error.
    assert SECRET not in text and "x" * 40 not in text and "rv_app:p" not in text


def test_production_loopback_origin_needs_an_explicit_switch() -> None:
    local = {**PRODUCTION, "origin": "http://127.0.0.1:3000"}
    with pytest.raises(ValidationError):
        Settings(**local)
    assert Settings(**local, allow_loopback_origin=True).origin == "http://127.0.0.1:3000"
    with pytest.raises(ValidationError):
        Settings(**{**local, "origin": "http://192.168.1.5:3000"}, allow_loopback_origin=True)


def test_development_keeps_its_invariants_and_can_exercise_github() -> None:
    dev = {**BASE, "environment": "development"}
    assert Settings(**dev, dev_auth=True).auth_provider == "dev"
    with pytest.raises(ValidationError, match="development identity adapter is required"):
        Settings(**dev)
    with pytest.raises(ValidationError, match="local browser origin"):
        Settings(**dev, dev_auth=True, origin="https://repovox.example.test")
    github = {
        **dev,
        "auth_provider": "github",
        "github_client_id": "Iv1.repovoxtest",
        "github_client_secret": SECRET,
    }
    assert Settings(**github).auth_provider == "github"
    assert Settings(**github, origin=ORIGIN).origin == ORIGIN
    with pytest.raises(ValidationError, match="excludes development identities"):
        Settings(**github, dev_auth=True)
    with pytest.raises(ValidationError, match="client id and secret"):
        Settings(**{**github, "github_client_secret": None})
    with pytest.raises(ValidationError, match="local or https origin"):
        Settings(**github, origin="http://repovox.example.test")


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("https://repovox.example.test", True),
        ("https://repovox.example.test:443", True),
        ("https://REPOVOX.example.test", False),  # Must be written exactly as browsers send it.
        ("https://repovox.example.test/", False),
        ("https://", False),
        ("ftp://repovox.example.test", False),
        ("https://repovox.example.test:abc", False),
    ],
)
def test_https_origin_is_exact(value: str, valid: bool) -> None:
    assert https_origin(value) is valid


def test_owner_ids_are_derived_from_the_numeric_github_id_only() -> None:
    assert owner_for(4242) == owner_for(4242) != owner_for(4243)
    assert isinstance(owner_for(1), UUID)
    for bad in (0, -1, True):
        with pytest.raises(ValueError):
            owner_for(bad)


class FakeSessions:
    def __init__(self) -> None:
        self.engine = object()
        self.issued: list[UUID] = []

    def issue(self, owner: UUID) -> tuple[str, str]:
        self.issued.append(owner)
        return "signed-session-cookie", "csrf-token"


class FakeGitHub:
    """GitHub's token and user endpoints, recording every request it receives."""

    def __init__(self, token: dict[str, Any] | None = None, user: dict[str, Any] | None = None):
        self.requests: list[httpx.Request] = []
        self.token = token if token is not None else {"access_token": "gho_secret_token"}
        self.user = user if user is not None else {"id": 4242, "login": "octocat"}
        self.fail = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise httpx.ConnectError("unreachable", request=request)
        if request.url == "https://github.com/login/oauth/access_token":
            return httpx.Response(200, json=self.token)
        if request.url == "https://api.github.com/user":
            return httpx.Response(200, json=self.user)
        return httpx.Response(404)


def github_app(
    monkeypatch: pytest.MonkeyPatch, fake: FakeGitHub, provisioned: bool = True
) -> tuple[TestClient, FakeSessions]:
    settings = Settings(**PRODUCTION)
    app = create_app(settings)  # Not entered, so nothing connects.
    sessions = FakeSessions()
    oauth = GitHubOAuth(settings, transport=httpx.MockTransport(fake))
    app.state.services = replace(app.state.services, sessions=sessions, github=oauth)
    monkeypatch.setattr(
        routes,
        "provisioned",
        lambda engine, github_id: owner_for(github_id) if provisioned else None,
    )
    return TestClient(app), sessions


def cookies(response: httpx.Response) -> dict[str, str]:
    """Set-Cookie headers by cookie name, attributes included."""
    return {value.split("=", 1)[0]: value for value in response.headers.get_list("set-cookie")}


def callback(
    client: TestClient, query: str, state_cookie: str | None, verifier: str | None = "v" * 86
) -> httpx.Response:
    sent = [f"{STATE_COOKIE}={state_cookie}"] if state_cookie else []
    sent += [f"{VERIFIER_COOKIE}={verifier}"] if verifier else []
    headers = {"cookie": "; ".join(sent)} if sent else {}
    return client.get(f"/v1/auth/github/callback?{query}", headers=headers, follow_redirects=False)


def test_login_redirects_to_github_with_a_state_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = github_app(monkeypatch, FakeGitHub())
    response = client.get("/v1/auth/github/login", follow_redirects=False)
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert (location.scheme, location.netloc, location.path) == (
        "https",
        "github.com",
        "/login/oauth/authorize",
    )
    query = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert query["client_id"] == "Iv1.repovoxtest"
    assert query["redirect_uri"] == ORIGIN + CALLBACK_PATH
    assert query["scope"] == "read:user"
    # PKCE: the S256 challenge of a verifier kept only in an HttpOnly cookie.
    verifier = cookies(response)[VERIFIER_COOKIE].split(";", 1)[0].split("=", 1)[1]
    digest = hashlib.sha256(verifier.encode()).digest()
    assert query["code_challenge"] == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert query["code_challenge_method"] == "S256" and 43 <= len(verifier) <= 128
    assert "httponly" in cookies(response)[VERIFIER_COOKIE].lower()
    assert verifier not in response.headers["location"]
    assert SECRET not in response.headers["location"]
    state = cookies(response)[STATE_COOKIE]
    assert state.startswith(f"{STATE_COOKIE}={query['state']};") and len(query["state"]) >= 43
    lowered = state.lower()
    assert "httponly" in lowered and "samesite=lax" in lowered and "secure" in lowered
    assert "max-age=600" in lowered
    # Each login gets its own state.
    second = client.get("/v1/auth/github/login", follow_redirects=False)
    assert cookies(second)[STATE_COOKIE] != state


def test_callback_rejects_a_missing_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGitHub()
    client, sessions = github_app(monkeypatch, fake)
    response = callback(client, "code=c&state=s1", "s1", verifier=None)
    assert (response.status_code, response.json()["error"]["code"]) == (
        400,
        "oauth_state_rejected",
    )
    assert fake.requests == [] and sessions.issued == []


@pytest.mark.parametrize(
    ("query", "state_cookie"),
    [
        ("code=c&state=attacker-state", "browser-state"),
        ("code=c&state=browser-state", None),
        ("code=c", "browser-state"),
        ("code=c&state=", "browser-state"),
    ],
)
def test_callback_rejects_a_missing_or_mismatched_state(
    monkeypatch: pytest.MonkeyPatch, query: str, state_cookie: str | None
) -> None:
    fake = FakeGitHub()
    client, sessions = github_app(monkeypatch, fake)
    response = callback(client, query, state_cookie)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "oauth_state_rejected"
    assert 'rv_oauth_state=""' in cookies(response)[STATE_COOKIE]  # Cleared.
    assert "rv_session" not in cookies(response)
    assert fake.requests == [] and sessions.issued == []  # GitHub is never contacted.


def test_callback_signs_in_a_provisioned_account(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGitHub()
    client, sessions = github_app(monkeypatch, fake)
    response = callback(client, "code=one-time-code&state=s1", "s1")
    assert response.status_code == 302 and response.headers["location"] == "/"
    assert sessions.issued == [owner_for(4242)]
    set_cookies = cookies(response)
    session = set_cookies["rv_session"].lower()
    assert "httponly" in session and "secure" in session and "samesite=strict" in session
    assert "secure" in set_cookies["rv_csrf"].lower()
    assert 'rv_oauth_state=""' in set_cookies[STATE_COOKIE]
    # The GitHub access token is used once and never handed to the browser.
    assert (
        "gho_secret_token" not in str(response.headers) and "gho_secret_token" not in response.text
    )
    exchange, profile = fake.requests
    form = parse_qs(exchange.content.decode())
    assert exchange.method == "POST" and exchange.headers["accept"] == "application/json"
    assert form["code"] == ["one-time-code"] and form["client_id"] == ["Iv1.repovoxtest"]
    assert form["redirect_uri"] == [ORIGIN + CALLBACK_PATH]
    assert form["code_verifier"] == ["v" * 86]
    assert 'rv_oauth_verifier=""' in set_cookies[VERIFIER_COOKIE]  # Cleared too.
    assert profile.headers["authorization"] == "Bearer gho_secret_token"


def test_callback_refuses_an_account_nobody_provisioned(monkeypatch: pytest.MonkeyPatch) -> None:
    client, sessions = github_app(monkeypatch, FakeGitHub(), provisioned=False)
    response = callback(client, "code=c&state=s1", "s1")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_not_provisioned"
    assert sessions.issued == [] and "rv_session" not in cookies(response)


@pytest.mark.parametrize(
    ("fake", "status", "code"),
    [
        (FakeGitHub(token={"error": "bad_verification_code"}), 401, "oauth_rejected"),
        (FakeGitHub(token={"access_token": ""}), 401, "oauth_rejected"),
        (FakeGitHub(user={"id": "4242", "login": "octocat"}), 401, "oauth_rejected"),
        (FakeGitHub(user={"id": True, "login": "octocat"}), 401, "oauth_rejected"),
        (FakeGitHub(user={"login": "octocat"}), 401, "oauth_rejected"),
    ],
)
def test_callback_fails_closed_on_unexpected_github_answers(
    monkeypatch: pytest.MonkeyPatch, fake: FakeGitHub, status: int, code: str
) -> None:
    client, sessions = github_app(monkeypatch, fake)
    response = callback(client, "code=c&state=s1", "s1")
    assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert sessions.issued == []


def test_callback_reports_github_unavailable_and_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGitHub()
    fake.fail = True
    client, sessions = github_app(monkeypatch, fake)
    response = callback(client, "code=c&state=s1", "s1")
    assert (response.status_code, response.json()["error"]["code"]) == (502, "oauth_unavailable")
    denied = callback(client, "error=access_denied&state=s1", "s1")
    assert (denied.status_code, denied.json()["error"]["code"]) == (401, "oauth_denied")
    assert sessions.issued == []


def test_auth_config_is_public_and_names_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = github_app(monkeypatch, FakeGitHub())
    body = client.get("/v1/auth/config").json()
    assert body == {
        "auth_provider": "github",
        "github_oauth_enabled": True,
        "environment": "production",
    }
    assert SECRET not in client.get("/v1/auth/config").text
    # The real session service refuses development sign-in whenever GitHub is the adapter,
    # before it touches the database.
    real = TestClient(create_app(Settings(**PRODUCTION)))
    refused = real.post(
        "/v1/auth/development/sign-in", json={"subject": "alex"}, headers={"origin": ORIGIN}
    )
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "development_auth_disabled"


def test_development_configuration_offers_no_github_routes() -> None:
    settings = Settings(**{**BASE, "environment": "test", "dev_auth": True})
    client = TestClient(create_app(settings))
    assert client.get("/v1/auth/config").json() == {
        "auth_provider": "dev",
        "github_oauth_enabled": False,
        "environment": "test",
    }
    for path in ("/v1/auth/github/login", "/v1/auth/github/callback?code=c&state=s"):
        assert client.get(path, follow_redirects=False).status_code == 404

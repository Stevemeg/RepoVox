"""GitHub sign-in against the real database roles: provisioning, RLS lookup, sessions.

GitHub itself is an httpx MockTransport; everything else is the real API on rv_app, with
accounts provisioned through the migration role exactly as an operator would.
"""

import os
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from repovox.auth.accounts import disable, listing, provision
from repovox.auth.github import STATE_COOKIE, GitHubOAuth, owner_for
from repovox.core.config import Settings
from repovox.main import create_app
from sqlalchemy import Engine, create_engine, text

PROVISIONED, STRANGER = 910000001, 910000002


def github(user_id: int) -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "gho_integration_only"})
        return httpx.Response(200, json={"id": user_id, "login": f"user{user_id}"})

    return httpx.MockTransport(answer)


@pytest.fixture
def migration() -> Iterator[Engine]:
    engine = create_engine(os.environ["REPOVOX_TEST_MIGRATION_URL"])
    yield engine
    engine.dispose()


@pytest.fixture
def cleanup(admin: Engine) -> Iterator[None]:
    yield
    owners = [owner_for(PROVISIONED), owner_for(STRANGER)]
    with admin.begin() as c:
        # Runs even after a failed assertion, so nothing references these users afterwards.
        c.execute(text("TRUNCATE projects CASCADE"))
        for table in ("auth_sessions", "quota_accounts"):
            c.execute(text(f"DELETE FROM {table} WHERE owner_id = ANY(:o)"), {"o": owners})
        c.execute(text("DELETE FROM users WHERE id = ANY(:o)"), {"o": owners})


def app_for(user_id: int) -> Any:
    settings = Settings(
        environment="test",
        dev_auth=False,
        fixtures=False,
        synthetic_source_dir=None,
        auth_provider="github",
        github_client_id="Iv1.integration",
        github_client_secret="integration-secret-" + "s" * 24,
    )
    app = create_app(settings)
    oauth = GitHubOAuth(settings, transport=github(user_id))
    app.state.services = replace(app.state.services, github=oauth)
    return app


def sign_in(client: TestClient) -> httpx.Response:
    login = client.get("/v1/auth/github/login", follow_redirects=False)
    assert login.status_code == 302
    state = client.cookies[STATE_COOKIE]
    return client.get(
        f"/v1/auth/github/callback?code=integration-code&state={state}", follow_redirects=False
    )


def test_provisioned_github_account_signs_in_with_tenant_isolation(
    admin: Engine, migration: Engine, cleanup: None
) -> None:
    owner = provision(migration, PROVISIONED, "Grace Hopper", "grace@example.test")
    assert owner == owner_for(PROVISIONED)
    # Provisioning twice reactivates and updates; it never creates a second account.
    assert provision(migration, PROVISIONED, "Grace B. Hopper", "grace@example.test") == owner
    assert {row["github_id"] for row in listing(migration)} >= {str(PROVISIONED)}
    with admin.connect() as c:
        assert (
            c.scalar(text("SELECT count(*) FROM quota_accounts WHERE owner_id=:o"), {"o": owner})
            == 1
        )
        assert (
            c.scalar(text("SELECT issuer FROM users WHERE id=:o"), {"o": owner})
            == "https://github.com"
        )
    with TestClient(app_for(PROVISIONED)) as client:
        callback = sign_in(client)
        assert callback.status_code == 302 and callback.headers["location"] == "/"
        assert STATE_COOKIE not in client.cookies  # Single use.
        session = client.get("/v1/auth/session").json()
        assert (session["display_name"], session["auth_provider"]) == ("Grace B. Hopper", "github")
        assert client.get("/v1/projects").json() == []  # Only this owner's rows are visible.
        client.headers.update(
            {"origin": "http://localhost:3000", "x-csrf-token": client.cookies["rv_csrf"]}
        )
        created = client.post(
            "/v1/projects",
            json={"title": "Mine", "repository_url": "https://github.com/example/demo"},
        )
        assert created.status_code == 201, created.text
        with admin.connect() as c:
            assert (
                c.scalar(
                    text("SELECT owner_id FROM projects WHERE id=:id"), {"id": created.json()["id"]}
                )
                == owner
            )
            # The GitHub access token is not kept anywhere in the database.
            dumped = c.scalar(
                text("SELECT string_agg(t::text, ' ') FROM auth_sessions t WHERE owner_id=:o"),
                {"o": owner},
            )
            assert "gho_integration_only" not in (dumped or "")
        # Disabling stops new sign-ins and revokes the open session.
        assert disable(migration, PROVISIONED)
        assert client.get("/v1/auth/session").status_code == 401
        assert sign_in(client).status_code == 403


def test_unprovisioned_github_account_is_refused(admin: Engine, cleanup: None) -> None:
    with TestClient(app_for(STRANGER)) as client:
        refused = sign_in(client)
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "account_not_provisioned"
        assert "rv_session" not in client.cookies
    with admin.connect() as c:
        assert (
            c.scalar(text("SELECT count(*) FROM users WHERE id=:o"), {"o": owner_for(STRANGER)})
            == 0
        )

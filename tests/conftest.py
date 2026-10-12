import os
from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from repovox.core.config import Settings
from repovox.db.database import make_engine
from repovox.main import create_app
from repovox.storage import S3Storage
from repovox.workers.runtime import Orchestrator
from sqlalchemy import Engine, create_engine, text

A = UUID("11111111-1111-4111-8111-111111111111")
B = UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def admin() -> Iterator[Engine]:
    # Explicitly disposable test administration. Never injected into the HTTP application.
    engine = create_engine(os.environ["REPOVOX_TEST_ADMIN_URL"])
    with engine.begin() as c:
        c.execute(text("TRUNCATE projects,auth_sessions CASCADE"))
        c.execute(text("TRUNCATE rv.auth_rate_buckets"))
        c.execute(text("UPDATE quota_accounts SET month_limit=10,queued_limit=10,active_limit=1"))
    yield engine
    engine.dispose()


@pytest.fixture
def app_engine(settings: Settings, admin: Engine) -> Iterator[Engine]:
    engine = make_engine(settings.database_url.get_secret_value())
    yield engine
    engine.dispose()


@pytest.fixture
def orchestrator(settings: Settings, admin: Engine) -> Iterator[Orchestrator]:
    assert settings.worker_database_url is not None
    engine = make_engine(settings.worker_database_url.get_secret_value())
    yield Orchestrator(engine, S3Storage(settings))
    engine.dispose()


@pytest.fixture
def clients(settings: Settings, admin: Engine) -> Iterator[tuple[TestClient, TestClient]]:
    app = create_app(settings)
    with TestClient(app) as alex, TestClient(app) as sam:
        for client, subject in [(alex, "alex"), (sam, "sam")]:
            response = client.post(
                "/v1/auth/development/sign-in",
                json={"subject": subject},
                headers={"origin": settings.origin},
            )
            assert response.status_code == 200, response.text
            client.headers.update(
                {"origin": settings.origin, "x-csrf-token": client.cookies["rv_csrf"]}
            )
        yield alex, sam


def project(client: TestClient, name: str = "Fixture") -> str:
    response = client.post(
        "/v1/projects",
        json={"title": name, "repository_url": "https://github.com/Example/Demo.git/"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def admit(client: TestClient, pid: str, key: str = "fixture-1", fixture: str = "normal") -> dict:
    response = client.post(
        f"/v1/development/projects/{pid}/fixture-jobs",
        json={"fixture": fixture},
        headers={"idempotency-key": key},
    )
    assert response.status_code == 202, response.text
    return response.json()

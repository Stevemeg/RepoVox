from uuid import UUID

from conftest import admit, project
from fastapi.testclient import TestClient
from repovox.core.config import Settings
from repovox.main import create_app
from repovox.workers.runtime import Orchestrator
from sqlalchemy import Engine, text


def test_bounded_lease_retries_and_new_job_retry(
    clients: tuple[TestClient, TestClient], admin: Engine, orchestrator: Orchestrator
) -> None:
    a, _ = clients
    pid = project(a)
    job = admit(a, pid)
    sid = UUID(job["stages"][1]["id"])
    for attempt in range(1, 4):
        lease = orchestrator.claim(sid, f"dead-worker-{attempt}")
        assert lease and lease["attempt_no"] == attempt
        with admin.begin() as c:
            c.execute(
                text(
                    "UPDATE job_stages SET lease_expires_at=now()-interval '1 second' WHERE id=:id"
                ),
                {"id": sid},
            )
        orchestrator.reconcile()
        if attempt < 3:
            with admin.begin() as c:
                c.execute(
                    text(
                        "UPDATE job_stages SET next_attempt_at=now()-interval '1 second' "
                        "WHERE id=:id"
                    ),
                    {"id": sid},
                )
            orchestrator.reconcile()
    assert a.get(f"/v1/jobs/{job['id']}").json()["error_code"] == "attempt_limit"
    assert orchestrator.claim(sid, "fourth") is None
    retried = a.post(
        f"/v1/development/jobs/{job['id']}/retry", headers={"idempotency-key": "new-retry"}
    )
    assert retried.status_code == 202, retried.text
    assert retried.json()["id"] != job["id"] and retried.json()["prior_job_id"] == job["id"]
    assert a.get(f"/v1/jobs/{job['id']}").json()["state"] == "failed"
    assert len(a.get(f"/v1/jobs/{job['id']}").json()["attempts"]) == 3


def test_fixture_environment_gate_and_request_limits(settings: Settings, admin: Engine) -> None:
    disabled = settings.model_copy(update={"fixtures": False})
    with TestClient(create_app(disabled)) as client:
        response = client.post(
            "/v1/auth/development/sign-in",
            json={"subject": "alex"},
            headers={"origin": settings.origin},
        )
        assert "HttpOnly" in response.headers.get_list("set-cookie")[0]
        assert "SameSite=strict" in response.headers.get_list("set-cookie")[0]
        client.headers.update(
            {"origin": settings.origin, "x-csrf-token": client.cookies["rv_csrf"]}
        )
        pid = project(client)
        result = client.post(
            f"/v1/development/projects/{pid}/fixture-jobs",
            json={"fixture": "normal"},
            headers={"idempotency-key": "disabled"},
        )
        assert result.status_code == 503
        assert client.post("/v1/projects", content=b"x" * 17000).status_code == 413
        assert (
            client.post(
                "/v1/projects",
                json={"title": "Bad", "repository_url": "https://github.com/a/b"},
                headers={"origin": "https://evil.test"},
            ).status_code
            == 403
        )
        for _ in range(4):
            assert (
                client.post("/v1/auth/development/sign-in", json={"subject": "sam"}).status_code
                == 200
            )
        assert (
            client.post("/v1/auth/development/sign-in", json={"subject": "sam"}).status_code == 429
        )


def test_invalid_nonterminal_transition(
    clients: tuple[TestClient, TestClient], admin: Engine
) -> None:
    import pytest
    from sqlalchemy.exc import DBAPIError

    a, _ = clients
    job = admit(a, project(a))
    with pytest.raises(DBAPIError, match="invalid_transition"):
        with admin.begin() as c:
            c.execute(
                text("UPDATE generation_jobs SET state='succeeded' WHERE id=:id"), {"id": job["id"]}
            )
    assert a.get(f"/v1/jobs/{job['id']}").json()["state"] == "queued"

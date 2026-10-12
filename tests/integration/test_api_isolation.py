from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from conftest import A, B, admit, project
from fastapi.testclient import TestClient
from repovox.db.database import tenant, verify_role
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError


def test_crud_csrf_session_and_cross_tenant(
    clients: tuple[TestClient, TestClient], admin: Engine
) -> None:
    a, b = clients
    pid = project(a)
    assert (
        a.get(f"/v1/projects/{pid}").json()["repository_url"] == "https://github.com/example/demo"
    )
    assert b.get("/v1/projects").json() == []
    assert b.get(f"/v1/projects/{pid}").status_code == 404
    assert b.patch(f"/v1/projects/{pid}", json={"title": "Stolen"}).status_code == 404
    assert b.delete(f"/v1/projects/{pid}").status_code == 404
    assert a.patch(f"/v1/projects/{pid}", json={"title": "Renamed"}).json()["title"] == "Renamed"
    assert (
        a.post(
            "/v1/projects",
            json={"title": "Bad", "repository_url": "http://169.254.169.254"},
            headers={"x-csrf-token": ""},
        ).status_code
        == 403
    )
    assert (
        a.post(
            "/v1/projects",
            json={"title": "Bad", "repository_url": "https://github.com/a/b", "owner_id": str(B)},
        ).status_code
        == 422
    )
    job = admit(a, pid)
    assert b.get(f"/v1/jobs/{job['id']}").status_code == 404
    assert b.post(f"/v1/jobs/{job['id']}/cancel").status_code == 404
    assert b.get(f"/v1/projects/{pid}/jobs").status_code == 404
    response = b.get("/v1/jobs")
    assert response.status_code == 200, response.text
    assert response.json() == []
    response = a.post(f"/v1/projects/{pid}/jobs", json={"commit_sha": "a" * 40, "synthetic": True})
    assert (
        response.status_code == 503
        and response.json()["error"]["code"] == "secure_acquisition_unavailable"
    )
    assert (
        a.post(
            f"/v1/development/projects/{pid}/fixture-jobs",
            json={"fixture": "normal", "commit_sha": "b" * 40},
            headers={"idempotency-key": "fake"},
        ).status_code
        == 422
    )
    assert a.delete(f"/v1/projects/{pid}").status_code == 202
    assert a.get(f"/v1/projects/{pid}").status_code == 404
    assert a.get(f"/v1/jobs/{job['id']}").status_code == 404
    replay = a.post(
        f"/v1/development/projects/{pid}/fixture-jobs",
        json={"fixture": "normal"},
        headers={"idempotency-key": "fixture-1"},
    )
    assert replay.status_code == 404
    with admin.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM deletion_requests")) == 1


def test_sessions_expiration_logout_tampering(
    clients: tuple[TestClient, TestClient], admin: Engine
) -> None:
    a, b = clients
    old = a.cookies.get("rv_session")
    assert a.post("/v1/auth/sign-out").status_code == 204
    assert a.get("/v1/projects").status_code == 401
    a.cookies.set("rv_session", old)
    assert a.get("/v1/projects").status_code == 401
    a.cookies.set("rv_session", "forged-cookie")
    assert a.get("/v1/projects").status_code == 401
    with admin.begin() as c:
        c.execute(
            text(
                "UPDATE auth_sessions SET expires_at=now()-interval '1 second' "
                "WHERE owner_id=:owner"
            ),
            {"owner": B},
        )
    assert b.get("/v1/projects").status_code == 401
    response = b.get("/v1/projects", headers={"x-request-id": "invalid\nvalue"})
    assert response.status_code == 401 and "\n" not in response.headers["x-request-id"]
    assert set(response.json()["error"]) == {"code", "request_id"}


def test_rls_missing_owner_pool_and_composite_fk(
    clients: tuple[TestClient, TestClient], app_engine: Engine, admin: Engine
) -> None:
    a, b = clients
    pa, pb = project(a, "A"), project(b, "B")
    ja, jb = admit(a, pa), admit(b, pb)
    with admin.connect() as c:
        foreign_snapshot = c.scalar(
            text("SELECT snapshot_id FROM generation_jobs WHERE id=:id"), {"id": jb["id"]}
        )
    verify_role(app_engine, "rv_app")
    with app_engine.connect() as c:
        assert (
            c.scalar(
                text("SELECT has_function_privilege(current_user,'rv.claim(uuid,text)','EXECUTE')")
            )
            is False
        )
        assert c.scalar(text("SELECT pg_has_role(current_user,'rv_executor','MEMBER')")) is False
        assert c.scalar(text("SELECT count(*) FROM projects")) == 0
        assert c.scalar(text("SELECT count(*) FROM generation_jobs")) == 0
    for _ in range(12):
        with tenant(app_engine, A) as c:
            assert c.scalar(text("SELECT count(*) FROM projects")) == 1
            assert c.scalar(text("SELECT count(*) FROM generation_jobs")) == 1
            assert (
                c.execute(
                    text("UPDATE projects SET title='Stolen' WHERE id=:id"), {"id": pb}
                ).rowcount
                == 0
            )
            assert c.scalar(text("SELECT id FROM users WHERE id=:id"), {"id": B}) is None
            assert (
                c.scalar(
                    text("SELECT id FROM repository_snapshots WHERE id=:id"),
                    {"id": foreign_snapshot},
                )
                is None
            )
            assert (
                c.scalar(
                    text("SELECT id FROM job_stages WHERE id=:id"), {"id": jb["stages"][1]["id"]}
                )
                is None
            )
        with app_engine.connect() as c:
            assert c.scalar(text("SELECT count(*) FROM projects")) == 0
    with pytest.raises(DBAPIError) as failed:
        with tenant(app_engine, A) as c:
            c.execute(
                text(
                    "INSERT INTO repository_snapshots(owner_id,project_id,commit_sha,synthetic,"
                    "acquisition_version,pipeline_version) "
                    "VALUES(:owner,:project,:sha,true,'test','test')"
                ),
                {"owner": A, "project": pb, "sha": "b" * 40},
            )
    assert failed.value.orig.sqlstate == "23503"
    with pytest.raises(DBAPIError) as rejected:
        with tenant(app_engine, A) as c:
            c.execute(
                text(
                    "INSERT INTO projects(owner_id,repository_url,title) VALUES(:owner,'https://github.com/a/b','Forbidden')"
                ),
                {"owner": B},
            )
    assert rejected.value.orig.sqlstate == "42501"
    with pytest.raises(DBAPIError):
        with app_engine.begin() as c:
            c.execute(text("SELECT * FROM rv.claim(:id,'intruder')"), {"id": ja["stages"][1]["id"]})
    with pytest.raises(DBAPIError, match="not_found"):
        with tenant(app_engine, A) as c:
            c.execute(text("SELECT rv.delete_project(:id)"), {"id": pb})


def test_migration_rls_and_worker_grants(admin: Engine, orchestrator) -> None:
    with admin.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0002"
        unsafe = c.execute(
            text(
                "SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace "
                "AND relkind='r' AND relname<>'alembic_version' "
                "AND (NOT relrowsecurity OR NOT relforcerowsecurity)"
            )
        ).all()
        assert unsafe == []
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM pg_roles WHERE rolname IN "
                    "('rv_app','rv_worker','rv_migrator','rv_executor') "
                    "AND (rolsuper OR rolbypassrls)"
                )
            )
            == 0
        )
    with orchestrator.engine.connect() as c:
        assert c.scalar(text("SELECT current_user")) == "rv_worker"
        assert (
            c.scalar(text("SELECT has_table_privilege(current_user,'generation_jobs','SELECT')"))
            is False
        )
        assert (
            c.scalar(
                text(
                    "SELECT has_function_privilege(current_user,"
                    "'rv.admit(uuid,text,text,text,uuid)','EXECUTE')"
                )
            )
            is False
        )
        assert c.scalar(text("SELECT pg_has_role(current_user,'rv_executor','MEMBER')")) is False


def test_concurrent_projects_and_owner_context(clients: tuple[TestClient, TestClient]) -> None:
    a, b = clients
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda i: project(a if i % 2 == 0 else b, f"Project {i}"), range(12))
        )
    assert len(set(results)) == 12
    assert len(a.get("/v1/projects").json()) == len(b.get("/v1/projects").json()) == 6


def test_idempotency_quota_races(clients: tuple[TestClient, TestClient], admin: Engine) -> None:
    a, _ = clients
    pid = project(a)

    def submit(key: str, fixture: str = "normal"):
        return a.post(
            f"/v1/development/projects/{pid}/fixture-jobs",
            json={"fixture": fixture},
            headers={"idempotency-key": key},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: submit("same-key"), range(8)))
    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["id"] for r in responses}) == 1
    assert submit("same-key", "transient_once").status_code == 409
    with admin.begin() as c:
        c.execute(
            text("UPDATE quota_accounts SET month_limit=2 WHERE owner_id=:owner"), {"owner": A}
        )
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: submit(str(uuid4())), range(8)))
    assert sum(r.status_code == 202 for r in results) == 1
    assert all(r.status_code in (202, 429) for r in results)
    with admin.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM generation_jobs")) == 2
        assert c.scalar(text("SELECT count(*) FROM quota_reservations")) == 2
        assert c.scalar(text("SELECT count(*) FROM usage_cost_records")) == 2

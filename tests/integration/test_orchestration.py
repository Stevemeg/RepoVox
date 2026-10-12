import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import httpx
import pytest
from botocore.exceptions import ClientError
from celery import Celery
from conftest import A, B, admit, project
from fastapi.testclient import TestClient
from repovox.core.errors import DomainError
from repovox.storage import ObjectRef
from repovox.workers.dispatcher import dispatch
from repovox.workers.runtime import Orchestrator
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError


def test_duplicate_claims_fencing_and_terminal(
    clients: tuple[TestClient, TestClient], admin: Engine, orchestrator: Orchestrator
) -> None:
    a, _ = clients
    job = admit(a, project(a))
    sid = UUID(job["stages"][1]["id"])
    with ThreadPoolExecutor(max_workers=8) as pool:
        leases = list(pool.map(lambda i: orchestrator.claim(sid, str(i)), range(8)))
    valid = [lease for lease in leases if lease]
    assert len(valid) == 1
    old = valid[0]
    assert orchestrator.heartbeat(sid, old["fence"])
    with admin.begin() as c:
        c.execute(
            text("UPDATE job_stages SET lease_expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": sid},
        )
    assert not orchestrator.heartbeat(sid, old["fence"])
    orchestrator.reconcile()
    with admin.begin() as c:
        c.execute(
            text("UPDATE job_stages SET next_attempt_at=now()-interval '1 second' WHERE id=:id"),
            {"id": sid},
        )
    orchestrator.reconcile()
    new = orchestrator.claim(sid, "restarted-worker")
    assert new and new["fence"] > old["fence"] and new["attempt_no"] == 2
    body = b'{"synthetic":true}'
    ref = ObjectRef(A, new["snapshot_id"], new["job_id"], uuid4(), hashlib.sha256(body).hexdigest())
    orchestrator.storage.write(ref, body)
    assert not orchestrator.finish(old, ref)
    assert orchestrator.finish(new, ref)
    assert not orchestrator.finish(new, ref)
    assert not orchestrator.run(sid, "duplicate")
    assert orchestrator.run(UUID(job["stages"][2]["id"]), "fixture-boundary")
    result = a.get(f"/v1/jobs/{job['id']}").json()
    assert result["state"] == "failed" and result["error_code"] == "phase1_fixture_boundary"
    assert result["stages"][1]["state"] == "succeeded"
    assert len(result["history"]) == 5
    with admin.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM knowledge_artifacts")) == 1
        assert (
            c.scalar(text("SELECT count(*) FROM usage_cost_records WHERE event_type='settled'"))
            == 1
        )
    with pytest.raises(DBAPIError, match="terminal_immutable"):
        with admin.begin() as c:
            c.execute(
                text("UPDATE generation_jobs SET state='running' WHERE id=:id"), {"id": job["id"]}
            )
    orchestrator.storage.delete(A, ref)


def test_retry_cancellation_deadline_and_attempt_limits(
    clients: tuple[TestClient, TestClient], admin: Engine, orchestrator: Orchestrator
) -> None:
    a, _ = clients
    pid = project(a)
    job = admit(a, pid, fixture="transient_once")
    sid = UUID(job["stages"][1]["id"])
    assert orchestrator.run(sid, "first")
    result = a.get(f"/v1/jobs/{job['id']}").json()
    assert result["state"] == "retry_wait" and result["stages"][1]["next_attempt_at"]
    orchestrator.reconcile()
    assert not orchestrator.claim(sid, "too-early")
    assert a.post(f"/v1/jobs/{job['id']}/cancel").json()["state"] == "cancelled"
    assert not orchestrator.claim(sid, "cancelled")
    assert a.post(f"/v1/jobs/{job['id']}/cancel").status_code == 409
    second = admit(a, pid, "second")
    with admin.begin() as c:
        c.execute(
            text("UPDATE generation_jobs SET deadline=now()-interval '1 second' WHERE id=:id"),
            {"id": second["id"]},
        )
    orchestrator.reconcile()
    assert a.get(f"/v1/jobs/{second['id']}").json()["error_code"] == "job_deadline"
    with pytest.raises(DBAPIError, match="terminal_immutable"):
        with admin.begin() as c:
            # Trigger protects nonterminal state transitions even under test admin access.
            c.execute(
                text("UPDATE generation_jobs SET state='succeeded' WHERE id=:id"), {"id": job["id"]}
            )


def test_active_limit_and_cancel_publication_race(
    clients: tuple[TestClient, TestClient], admin: Engine, orchestrator: Orchestrator
) -> None:
    a, _ = clients
    pid = project(a)
    first, second = admit(a, pid), admit(a, pid, "second")
    lease = orchestrator.claim(UUID(first["stages"][1]["id"]), "one")
    assert lease
    assert orchestrator.claim(UUID(second["stages"][1]["id"]), "two") is None
    body = b"{}"
    ref = ObjectRef(
        A, lease["snapshot_id"], lease["job_id"], uuid4(), hashlib.sha256(body).hexdigest()
    )
    assert a.post(f"/v1/jobs/{first['id']}/cancel").status_code == 200
    assert not orchestrator.finish(lease, ref)
    assert orchestrator.claim(UUID(second["stages"][1]["id"]), "two")


def test_outbox_redis_interruption_rebuild(
    clients: tuple[TestClient, TestClient], admin: Engine, orchestrator: Orchestrator, settings
) -> None:
    import redis

    a, _ = clients
    job = admit(a, project(a))
    broken = Celery("failure-injection", broker="redis://redis:1/0")
    broken.conf.broker_connection_timeout = 1
    assert dispatch(orchestrator.engine, broken) == 0
    with admin.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM outbox_events WHERE published_at IS NULL")) == 1
    broker = Celery("delivery", broker=settings.redis_url)
    client = redis.Redis.from_url(settings.redis_url)
    client.flushdb()
    assert dispatch(orchestrator.engine, broker) == 1
    assert client.llen("celery") == 1
    client.flushdb()  # Real Redis data loss, not mocked queue methods.
    with admin.begin() as c:
        c.execute(text("UPDATE outbox_events SET published_at=now()-interval '31 seconds'"))
    assert orchestrator.reconcile() == 1
    assert dispatch(orchestrator.engine, broker) == 1
    assert client.llen("celery") == 1
    assert orchestrator.run(UUID(job["stages"][1]["id"]), "rebuilt")
    assert not orchestrator.run(UUID(job["stages"][1]["id"]), "duplicate-delivery")
    assert a.get(f"/v1/jobs/{job['id']}").json()["stages"][1]["state"] == "succeeded"
    client.flushdb()


def test_private_storage_and_durable_cleanup(
    clients: tuple[TestClient, TestClient], orchestrator: Orchestrator, settings
) -> None:
    a, _ = clients
    pid = project(a)
    job = admit(a, pid)
    lease = orchestrator.claim(UUID(job["stages"][1]["id"]), "object-test")
    body = b'{"synthetic":true}'
    ref = ObjectRef(
        A, lease["snapshot_id"], lease["job_id"], uuid4(), hashlib.sha256(body).hexdigest()
    )
    orchestrator.storage.write(ref, body)
    assert orchestrator.storage.read(A, ref) == body
    with pytest.raises(DomainError):
        orchestrator.storage.read(B, ref)
    with pytest.raises(DomainError):
        orchestrator.storage.delete(B, ref)
    with pytest.raises(ClientError):
        orchestrator.storage.write(ref, body)  # Immutable key, conditional create.
    assert httpx.get(
        f"{settings.storage_endpoint}/{settings.storage_bucket}/{ref.key}"
    ).status_code in (401, 403)
    assert orchestrator.finish(lease, ref)
    deletion = a.delete(f"/v1/projects/{pid}").json()["deletion_id"]
    assert a.get(f"/v1/jobs/{job['id']}").status_code == 404
    orchestrator.cleanup(UUID(deletion))
    orchestrator.cleanup(UUID(deletion))
    with pytest.raises(ClientError):
        orchestrator.storage.read(A, ref)


def test_celery_real_delivery(
    clients: tuple[TestClient, TestClient], orchestrator: Orchestrator, settings
) -> None:
    import os
    import subprocess
    import sys

    import redis

    a, _ = clients
    redis.Redis.from_url(settings.redis_url).flushdb()
    job = admit(a, project(a))
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "repovox.workers.tasks:celery",
            "worker",
            "--pool=solo",
            "--loglevel=ERROR",
            "--hostname=test-worker",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
    )
    try:
        broker = Celery("real-test", broker=settings.redis_url)
        assert dispatch(orchestrator.engine, broker) == 1
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = a.get(f"/v1/jobs/{job['id']}").json()
            if status["stages"][1]["state"] == "succeeded":
                break
            time.sleep(0.2)
        assert status["stages"][1]["state"] == "succeeded"
        dispatch(orchestrator.engine, broker)
        while time.monotonic() < deadline:
            status = a.get(f"/v1/jobs/{job['id']}").json()
            if status["state"] == "failed":
                break
            time.sleep(0.2)
        assert status["error_code"] == "phase1_fixture_boundary"
    finally:
        worker.terminate()
        worker.wait(timeout=10)
        redis.Redis.from_url(settings.redis_url).flushdb()

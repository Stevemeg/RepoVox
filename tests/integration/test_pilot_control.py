"""Real PostgreSQL fencing plus synthetic source/broker faults; no evaluation packets."""

import io
import json
import secrets
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import repovox.analysis
from conftest import A, B, admit, project
from repovox.analysis.common import AnalysisError, digest
from repovox.analysis.github import Snapshot
from repovox.analysis.runner import AnalysisRunner
from repovox.analysis.transport import GitHubHTTP
from repovox.db.database import tenant
from repovox.pilot.contracts import Family, File, Manifest
from repovox.pilot.control import Controller
from repovox.pilot.execution import Executor
from repovox.storage import ObjectRef, S3Storage
from repovox.workers.runtime import Orchestrator
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError


class SyntheticHub(GitHubHTTP):
    def __init__(self, language="python"):
        super().__init__()
        self.bodies = {
            "app.py": b"def approved():\n    return 3\n",
            "README.md": b"Synthetic source context.\n",
            "tests/extra.py": b"def excluded_sentinel():\n    return 9\n",
        }
        if language != "python":
            del self.bodies["app.py"]
            self.bodies["app." + ("js" if language == "javascript" else "ts")] = (
                b"export function approved() { return 3; }\n"
            )
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for path, body in self.bodies.items():
                member = tarfile.TarInfo("synthetic/" + path)
                member.size = len(body)
                archive.addfile(member, io.BytesIO(body))
        self.body = stream.getvalue()
        self.calls = 0
        self.timeout = False
        self.entered = None
        self.release = None

    def download(self, path, target, limit, checkpoint):
        assert path == "/example/demo/tar.gz/" + "a" * 40
        self.calls += 1
        if self.entered:
            self.entered.set()
            assert self.release.wait(10)
        if self.timeout:
            raise AnalysisError("github_timeout", True)
        checkpoint()
        target.write(self.body)


@pytest.fixture
def cp(clients, admin, settings, request):
    # New nonprivileged login credentials exist only in this disposable test cluster.
    engines = []
    for name, group in [
        ("rv_cp_controller", "rv_pilot_controller"),
        ("rv_cp_executor", "rv_pilot_executor"),
    ]:
        password = secrets.token_hex(24)
        with admin.begin() as c:
            if not c.scalar(text("SELECT 1 FROM pg_roles WHERE rolname=:name"), {"name": name}):
                c.execute(text(f"CREATE ROLE {name} LOGIN NOSUPERUSER NOBYPASSRLS"))
            c.execute(text(f"ALTER ROLE {name} PASSWORD '{password}'"))
            c.execute(text(f"GRANT {group} TO {name}"))
        engines.append(create_engine(admin.url.set(username=name, password=password)))
    control = Controller(engines[0])
    parameters = getattr(request, "param", "python")
    deferred = isinstance(parameters, dict) and parameters.get("defer", False)
    hub = SyntheticHub(parameters["language"] if isinstance(parameters, dict) else parameters)
    engine_root = Path(repovox.analysis.__file__).parent
    family = Family(
        id="sample",
        repository="example/demo",
        commit="a" * 40,
        files=tuple(
            File(
                path=p,
                sha256=digest(hub.bodies[p]),
                size=len(hub.bodies[p]),
                role="context" if p == "README.md" else "source",
            )
            for p in hub.bodies
            if not p.startswith("tests/")
        ),
    )
    manifest = Manifest(
        owner=A,
        approval_sha256="b" * 64,
        families=(family,),
        engine_files={
            "analysis/" + p.relative_to(engine_root).as_posix(): digest(p.read_bytes())
            for p in engine_root.rglob("*.py")
        },
    )
    attempt = uuid4()
    control.register(A, attempt, manifest)
    pid = UUID(project(clients[0], "Synthetic control-plane fixture"))
    snapshot = Snapshot(
        "example/demo",
        "https://github.com/example/demo",
        1,
        "example",
        "demo",
        True,
        "main",
        "a" * 40,
        datetime.now(UTC).isoformat(),
    )
    job = None
    if not deferred:
        jid = control.admit(A, attempt, 1, "sample", pid, snapshot)
        assert jid
        job = clients[0].get(f"/v1/jobs/{jid}").json()
    worker = Executor(engines[1], A, S3Storage(settings), hub)
    with worker.engine.connect() as c:
        assert c.scalar(text("SHOW transaction_isolation")) == "read committed"
    fixture = SimpleNamespace(
        control=control,
        worker=worker,
        manifest=manifest,
        attempt=attempt,
        job=job,
        stage=UUID(job["stages"][1]["id"]) if job else None,
        hub=hub,
        admin=admin,
        clients=clients,
        engines=engines,
        pid=pid,
        snapshot=snapshot,
    )
    try:
        yield fixture
    finally:
        worker.dispose()
        for engine in engines:
            engine.dispose()


def run(cp, stage=None):
    return cp.worker.run(stage or cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample")


def test_timeout_then_restoration_and_stale_outbox(cp, orchestrator):
    cp.hub.timeout = True
    assert not run(cp)
    assert cp.control.status(A, cp.attempt)["state"] == "INVALIDATED"
    # Restore/reconcile an ordinary worker and deliver the old admission notification.
    orchestrator.reconcile()
    assert not Orchestrator(orchestrator.engine, orchestrator.storage).run(cp.stage, "restored")
    assert not run(cp)
    assert cp.hub.calls == 1
    with cp.admin.connect() as c:
        assert (
            c.scalar(text("SELECT count(*) FROM job_attempts WHERE stage_id=:id"), {"id": cp.stage})
            == 1
        )
        assert (
            c.scalar(
                text("SELECT count(*) FROM knowledge_artifacts WHERE job_id=:id"),
                {"id": cp.job["id"]},
            )
            == 0
        )


def test_legacy_retry_wait_cannot_survive_reconciliation(cp, orchestrator):
    lease = cp.worker.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample")
    assert lease
    # Fault injection reproduces the pre-fix durable state, without network/source execution.
    with cp.admin.begin() as c:
        c.execute(text("SELECT set_config('repovox.owner_id',:owner,true)"), {"owner": str(A)})
        c.execute(
            text("SELECT rv.cp_original_fail_analysis(:id,:fence,'github_timeout',true)"),
            {"id": cp.stage, "fence": lease["fence"]},
        )
        c.execute(
            text("UPDATE job_stages SET next_attempt_at=now()-interval '1 second' WHERE id=:id"),
            {"id": cp.stage},
        )
        assert (
            c.scalar(text("SELECT state FROM job_stages WHERE id=:id"), {"id": cp.stage})
            == "retry_wait"
        )
    orchestrator.reconcile()
    assert cp.control.status(A, cp.attempt)["state"] == "INVALIDATED"
    assert not orchestrator.run(cp.stage, "stale-outbox") and not run(cp)
    assert cp.hub.calls == 0


def test_pending_and_already_published_events_after_abort(cp, orchestrator):
    events = cp.worker.deliveries(cp.attempt, 1)
    assert len(events) == 1
    cp.control.invalidate(A, cp.attempt, 1)
    with cp.worker.engine.begin() as c:
        assert not c.scalar(
            text("SELECT rv.pilot_published(:event,:id,1)"),
            {"event": events[0]["event_id"], "id": cp.attempt},
        )
    assert not cp.worker.deliver(
        events[0]["event_id"], cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample"
    )
    with orchestrator.engine.connect() as c:
        assert all(
            r.stage_id != cp.stage for r in c.execute(text("SELECT * FROM rv.dispatch_batch()"))
        )
    assert not orchestrator.run(cp.stage, "broker-redelivery")
    assert cp.hub.calls == 0


@pytest.mark.parametrize(
    "ineligible",
    [
        "future",
        "published",
        "running",
        "pending",
        "expired",
        "canceled",
        "cross_attempt",
        "mismatched_stage",
        "terminal_job",
    ],
)
def test_publication_rechecks_event_eligibility(cp, ineligible):
    notification = cp.worker.deliveries(cp.attempt, 1)[0]
    eid = notification["event_id"]
    if ineligible == "running":
        assert cp.worker.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample")
    elif ineligible in {"future", "published"}:
        column = "due_at" if ineligible == "future" else "published_at"
        value = "clock_timestamp()+interval '1 hour'" if ineligible == "future" else "now()"
        with cp.admin.begin() as c:
            c.execute(text(f"UPDATE outbox_events SET {column}={value} WHERE id=:id"), {"id": eid})
    elif ineligible == "expired":
        # Disposable-admin clock fixture only. Runtime logins cannot bypass the
        # immutable-attempt trigger; SET LOCAL is rolled back/reset on exit.
        with cp.admin.begin() as c:
            c.execute(text("SET LOCAL session_replication_role=replica"))
            c.execute(
                text("UPDATE pilot_attempts SET expires_at=now()-interval '1 second' WHERE id=:id"),
                {"id": cp.attempt},
            )
        assert cp.control.status(A, cp.attempt)["state"] == "ACTIVE"
    elif ineligible == "canceled":
        cp.control.invalidate(A, cp.attempt, 1)
    elif ineligible == "cross_attempt":
        other = uuid4()
        cp.control.register(A, other, cp.manifest)
        pid = UUID(project(cp.clients[0], "Synthetic cross-attempt notification"))
        assert cp.control.admit(A, other, 1, "sample", pid, cp.snapshot)
    elif ineligible in {"pending", "mismatched_stage"}:
        sid = cp.job["stages"][2]["id"]
        if ineligible == "mismatched_stage":
            other_job = admit(cp.clients[0], project(cp.clients[0], "Synthetic other stage"))
            sid = other_job["stages"][1]["id"]
        with cp.admin.begin() as c:
            c.execute(
                text("UPDATE outbox_events SET stage_id=:sid WHERE id=:id"), {"sid": sid, "id": eid}
            )
    elif ineligible == "terminal_job":
        with cp.admin.begin() as c:
            c.execute(
                text("SELECT rv.end_job(:id,'failed','synthetic_terminal')"),
                {"id": cp.job["id"]},
            )
        assert cp.control.status(A, cp.attempt)["state"] == "ACTIVE"
    with cp.admin.connect() as c:
        before = c.scalar(text("SELECT published_at FROM outbox_events WHERE id=:id"), {"id": eid})
    with cp.worker.engine.begin() as c:
        published = c.scalar(
            text("SELECT rv.pilot_published(:event,:attempt,1)"),
            {"event": eid, "attempt": other if ineligible == "cross_attempt" else cp.attempt},
        )
    with cp.admin.connect() as c:
        after = c.scalar(text("SELECT published_at FROM outbox_events WHERE id=:id"), {"id": eid})
    assert (published, after) == (False, before)
    assert cp.hub.calls == 0


def test_concurrent_publication_marks_event_once(cp):
    eid = cp.worker.deliveries(cp.attempt, 1)[0]["event_id"]
    barrier = threading.Barrier(2)

    def publish():
        with cp.worker.engine.begin() as c:
            pid = c.scalar(text("SELECT pg_backend_pid()"))
            barrier.wait(timeout=5)
            result = c.scalar(
                text("SELECT rv.pilot_published(:event,:attempt,1)"),
                {"event": eid, "attempt": cp.attempt},
            )
            return pid, result

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: publish(), range(2)))
    assert len({pid for pid, _ in results}) == 2
    assert sum(result for _, result in results) == 1
    with cp.admin.connect() as c:
        assert c.scalar(
            text("SELECT published_at IS NOT NULL FROM outbox_events WHERE id=:id"), {"id": eid}
        )
        assert (
            c.scalar(text("SELECT count(*) FROM job_attempts WHERE stage_id=:id"), {"id": cp.stage})
            == 0
        )


def test_concurrent_publication_delivery_executes_one_stage(cp):
    notification = cp.worker.deliveries(cp.attempt, 1)[0]
    barrier = threading.Barrier(2)

    def before_publish(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT rv.pilot_published("):
            barrier.wait(timeout=5)  # Both observed the same eligible notification.

    def deliver():
        return cp.worker.deliver(
            notification["event_id"], cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample"
        )

    event.listen(cp.worker.engine, "before_cursor_execute", before_publish)
    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: deliver(), range(2)))
    finally:
        event.remove(cp.worker.engine, "before_cursor_execute", before_publish)
    assert sum(results) == 1 and cp.hub.calls == 1
    with cp.admin.connect() as c:
        assert (
            c.scalar(text("SELECT attempt_count FROM job_stages WHERE id=:id"), {"id": cp.stage})
            == 1
        )
        assert (
            c.scalar(
                text("SELECT count(*) FROM knowledge_artifacts WHERE job_id=:id"),
                {"id": cp.job["id"]},
            )
            == 1
        )


@pytest.mark.parametrize("changed", ["due_at", "published_at", "attempt_expiry"])
def test_publication_rechecks_after_event_lock_wait(cp, changed):
    import time

    eid = cp.worker.deliveries(cp.attempt, 1)[0]["event_id"]
    entered = threading.Event()
    backend = []
    if changed == "attempt_expiry":
        # Shorten only the synthetic fixture's clock, not runtime authorization.
        with cp.admin.begin() as c:
            c.execute(text("SET LOCAL session_replication_role=replica"))
            c.execute(
                text(
                    "UPDATE pilot_attempts SET expires_at=clock_timestamp()+interval '3 seconds' "
                    "WHERE id=:id"
                ),
                {"id": cp.attempt},
            )

    def publish():
        with cp.worker.engine.begin() as c:
            backend.append(c.scalar(text("SELECT pg_backend_pid()")))
            entered.set()
            return c.scalar(
                text("SELECT rv.pilot_published(:event,:attempt,1)"),
                {"event": eid, "attempt": cp.attempt},
            )

    # An independent transaction changes the event after listing, holds its row,
    # and commits only after PostgreSQL reports the publication is waiting on a lock.
    with cp.admin.connect() as blocker, ThreadPoolExecutor(1) as pool:
        transaction = blocker.begin()
        try:
            if changed == "attempt_expiry":
                # No new tuple: time must be rechecked even without EvalPlanQual.
                blocker.execute(
                    text("SELECT id FROM outbox_events WHERE id=:id FOR UPDATE"), {"id": eid}
                )
            else:
                value = "clock_timestamp()+interval '1 hour'" if changed == "due_at" else "now()"
                blocker.execute(
                    text(f"UPDATE outbox_events SET {changed}={value} WHERE id=:id"), {"id": eid}
                )
            pending = pool.submit(publish)
            assert entered.wait(5)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with cp.admin.connect() as observer:
                    waiting = observer.scalar(
                        text("SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=:pid"),
                        {"pid": backend[0]},
                    )
                if waiting:
                    break
                time.sleep(0.01)
            assert waiting, "Publication must reach the held event row"
            if changed == "attempt_expiry":
                blocker.execute(
                    text(
                        "SELECT pg_sleep(greatest(0,extract(epoch FROM "
                        "(expires_at-clock_timestamp()))+0.02)) FROM pilot_attempts WHERE id=:id"
                    ),
                    {"id": cp.attempt},
                )
            expected = blocker.scalar(
                text("SELECT published_at FROM outbox_events WHERE id=:id"), {"id": eid}
            )
            transaction.commit()
            assert pending.result(timeout=5) is False
        finally:
            if transaction.is_active:
                transaction.rollback()
    with cp.admin.connect() as c:
        assert (
            c.scalar(text("SELECT published_at FROM outbox_events WHERE id=:id"), {"id": eid})
            == expected
        )
    assert cp.hub.calls == 0


def test_two_workers_only_one_claim(cp):
    barrier = threading.Barrier(2)

    def claim():
        barrier.wait()
        return cp.worker.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample")

    with ThreadPoolExecutor(2) as pool:
        values = list(pool.map(lambda _: claim(), range(2)))
    assert sum(v is not None for v in values) == 1
    cp.control.invalidate(A, cp.attempt, 1)
    assert not run(cp)


@pytest.mark.parametrize("wrong", ["generation", "hash", "family", "attempt", "owner"])
def test_forged_or_cross_tenant_execution(cp, wrong):
    worker = cp.worker
    if wrong == "owner":
        worker = Executor(cp.engines[1], B, cp.worker.storage, cp.hub)
    try:
        assert (
            worker.claim(
                cp.stage,
                uuid4() if wrong == "attempt" else cp.attempt,
                999 if wrong == "generation" else 1,
                "f" * 64 if wrong == "hash" else cp.manifest.sha256,
                "other" if wrong == "family" else "sample",
            )
            is None
        )
        assert cp.hub.calls == 0
    finally:
        if worker is not cp.worker:
            worker.dispose()


def test_stale_fence_blocks_scope_writes_and_publication(cp):
    lease = cp.worker.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample")
    assert lease
    cp.control.invalidate(A, cp.attempt, 1)
    with cp.worker.engine.begin() as c:
        params = {"id": cp.stage, "f": lease["fence"], "sha": cp.manifest.sha256}
        assert not c.scalar(text("SELECT rv.heartbeat(:id,:f)"), params)
        assert c.scalar(text("SELECT rv.pilot_scope(:id,:f)"), params) is None
        assert not c.scalar(text("SELECT rv.pilot_verified(:id,:f,:sha)"), params)
        assert not c.scalar(
            text("SELECT rv.finish_analysis_v23(:id,:f,:a,:sha,'invalid',0,:sha,'{}')"),
            dict(params, a=uuid4()),
        )
    with cp.admin.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM pilot_validations")) == 0


def test_inflight_request_finishes_after_cancel(cp):
    cp.hub.entered = threading.Event()
    cp.hub.release = threading.Event()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(run, cp)
        assert cp.hub.entered.wait(10)
        cp.control.invalidate(A, cp.attempt, 1)
        cp.hub.release.set()
        assert not future.result(timeout=15)
    with cp.admin.connect() as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM knowledge_artifacts WHERE job_id=:id"),
                {"id": cp.job["id"]},
            )
            == 0
        )
    assert cp.hub.calls == 1


def test_generic_runner_without_scope_guard_cannot_publish(cp):
    lease = cp.worker.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample")
    assert lease
    ordinary = AnalysisRunner(cp.worker.engine, cp.worker.storage, cp.hub)
    runtime = Orchestrator(cp.worker.engine, cp.worker.storage)
    assert not ordinary.run(lease, lambda: runtime.heartbeat(cp.stage, lease["fence"]))
    assert cp.control.status(A, cp.attempt)["state"] == "INVALIDATED"
    with cp.admin.connect() as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM knowledge_artifacts WHERE job_id=:id"),
                {"id": cp.job["id"]},
            )
            == 0
        )


def test_actual_pipeline_never_parses_excluded_test(cp):
    for stage in cp.job["stages"][1:9]:
        assert run(cp, UUID(stage["id"]))
    assert cp.hub.calls == 1
    with cp.admin.connect() as c:
        a = (
            c.execute(
                text("SELECT * FROM knowledge_artifacts WHERE job_id=:id AND kind='structure'"),
                {"id": cp.job["id"]},
            )
            .mappings()
            .one()
        )
    ref = ObjectRef(A, a["snapshot_id"], UUID(cp.job["id"]), a["id"], a["checksum"], "analysis")
    envelope = json.loads(cp.worker.storage.read(A, ref))
    assert envelope["payload"]["structure"]["symbols"]
    assert all(s["path"] == "app.py" for s in envelope["payload"]["structure"]["symbols"])
    assert b"excluded_sentinel" not in json.dumps(envelope["payload"]["structure"]).encode()
    assert cp.control.close(A, cp.attempt, 1) == "EXECUTION_CLOSED"
    with cp.admin.connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT generation FROM pilot_audit WHERE attempt_id=:id "
                    "AND event='execution_closed'"
                ),
                {"id": cp.attempt},
            )
            == cp.control.status(A, cp.attempt)["generation"]
        )
    assert not run(cp)


def test_retry_missing_adapter_rejected_at_filter(cp, monkeypatch):
    assert run(cp)
    from repovox.pilot.execution import ScopedRunner

    monkeypatch.setattr(ScopedRunner, "preparation_filter", AnalysisRunner.preparation_filter)
    assert not run(cp, UUID(cp.job["stages"][2]["id"]))
    assert cp.control.status(A, cp.attempt)["state"] == "INVALIDATED"
    with cp.admin.connect() as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM knowledge_artifacts WHERE job_id=:id"),
                {"id": cp.job["id"]},
            )
            == 1
        )


def test_cancellation_races_admission(cp):
    attempt = uuid4()
    cp.control.register(A, attempt, cp.manifest)
    pid = UUID(project(cp.clients[0], "Synthetic initial admission race"))
    barrier = threading.Barrier(2)

    def admit_again():
        barrier.wait()
        return cp.control.admit(A, attempt, 1, "sample", pid, cp.snapshot)

    def cancel():
        barrier.wait()
        return cp.control.invalidate(A, attempt, 1)

    with ThreadPoolExecutor(2) as pool:
        left = pool.submit(admit_again)
        right = pool.submit(cancel)
        assert right.result() == "INVALIDATED"
        admitted = left.result()
    assert cp.control.admit(A, attempt, 1, "sample", pid, cp.snapshot) is None
    assert cp.hub.calls == 0
    with cp.admin.connect() as c:
        jobs = c.execute(
            text("SELECT id,state FROM generation_jobs WHERE project_id=:id"), {"id": pid}
        ).all()
        assert len(jobs) == (1 if admitted else 0)
        if admitted:
            assert jobs == [(admitted, "failed")]
            assert (
                c.scalar(
                    text(
                        "SELECT count(*) FROM pilot_bindings WHERE attempt_id=:id AND job_id=:job"
                    ),
                    {"id": attempt, "job": admitted},
                )
                == 1
            )


def test_terminal_generation_and_idempotent_invalidation(cp):
    cp.control.invalidate(A, cp.attempt, 1, "first_failure")
    before = cp.control.status(A, cp.attempt)
    assert cp.control.invalidate(A, cp.attempt, 1, "replacement") == "INVALIDATED"
    assert cp.control.status(A, cp.attempt) == before
    assert before["generation"] == 2 and before["reason"] == "first_failure"
    with pytest.raises(DBAPIError, match="pilot_terminal_immutable"):
        with cp.admin.begin() as c:
            c.execute(text("UPDATE pilot_attempts SET state='ACTIVE'"))


def test_controller_abort_precedes_restoration(cp):
    observed = []
    cp.control.abort_before_restore(
        A, cp.attempt, 1, lambda: observed.append(cp.control.status(A, cp.attempt)["state"])
    )
    assert observed == ["INVALIDATED"]
    assert not run(cp)


def test_ordinary_work_continues_after_pilot_abort(cp, orchestrator):
    cp.control.invalidate(A, cp.attempt, 1)
    ordinary = admit(cp.clients[0], project(cp.clients[0]), "ordinary", "transient_once")
    sid = UUID(ordinary["stages"][1]["id"])
    assert orchestrator.run(sid, "ordinary")
    assert cp.clients[0].get(f"/v1/jobs/{ordinary['id']}").json()["state"] == "retry_wait"
    with cp.admin.begin() as c:
        c.execute(
            text("UPDATE job_stages SET next_attempt_at=now()-interval '1 second' WHERE id=:id"),
            {"id": sid},
        )
    orchestrator.reconcile()
    assert orchestrator.run(sid, "ordinary-restarted")
    assert not orchestrator.run(cp.stage, "pilot-redelivery")


def test_role_grants_and_tenant_control(cp, app_engine):
    for engine in [app_engine, *cp.engines]:
        with engine.connect() as c:
            assert not c.scalar(
                text("SELECT has_schema_privilege(current_user,'evaluation','USAGE')")
            )
            assert not c.scalar(
                text(
                    "SELECT has_function_privilege(current_user,"
                    "'rv.cp_original_claim(uuid,text)','EXECUTE')"
                )
            )
    with pytest.raises(DBAPIError, match="permission denied"):
        with app_engine.begin() as c:
            c.execute(
                text("SELECT rv.pilot_register(:id,'{}',:sha)"), {"id": uuid4(), "sha": "a" * 64}
            )
    with pytest.raises(DBAPIError, match="pilot_not_found"):
        cp.control.invalidate(B, cp.attempt, 1)
    with pytest.raises(ValueError, match="pilot_executor_identity"):
        Executor(app_engine, A, cp.worker.storage)


def test_bound_project_rejects_generic_retry(cp):
    with pytest.raises(DBAPIError, match="pilot_admission_route_required"):
        with tenant(cp.clients[0].app.state.engine, A) as c:
            c.execute(
                text("SELECT rv.admit(:pid,'bypass','digest','normal',NULL)"), {"pid": cp.pid}
            )


def test_expired_lease_recovery_invalidates(cp, orchestrator):
    lease = cp.worker.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample")
    assert lease
    with cp.admin.begin() as c:
        c.execute(
            text("UPDATE job_stages SET lease_expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": cp.stage},
        )
    orchestrator.reconcile()
    assert cp.control.status(A, cp.attempt)["state"] == "INVALIDATED"
    assert not run(cp)


def test_publication_races_cancellation(cp):
    assert run(cp)
    stage = UUID(cp.job["stages"][2]["id"])
    lease = cp.worker.claim(stage, cp.attempt, 1, cp.manifest.sha256, "sample")
    assert lease
    # Pause the actual stage transition before the scope receipt/publication transaction.
    barrier = threading.Barrier(2)

    def receipt():
        barrier.wait()
        with cp.worker.engine.begin() as c:
            return c.scalar(
                text("SELECT rv.pilot_verified(:id,:fence,:sha)"),
                {"id": stage, "fence": lease["fence"], "sha": cp.manifest.sha256},
            )

    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(receipt)
        barrier.wait()
        cp.control.invalidate(A, cp.attempt, 1)
        assert future.result() in [True, False]
    assert cp.control.status(A, cp.attempt)["state"] == "INVALIDATED"
    with cp.worker.engine.begin() as c:
        assert not c.scalar(
            text("SELECT rv.pilot_verified(:id,:fence,:sha)"),
            {"id": stage, "fence": lease["fence"], "sha": cp.manifest.sha256},
        )


def test_cancellation_commits_before_actual_stage_publication(cp):
    assert run(cp)
    stage = UUID(cp.job["stages"][2]["id"])
    ready, release = threading.Event(), threading.Event()

    def before_finish(connection, cursor, statement, parameters, context, executemany):
        if "SELECT rv.finish_analysis_v23" in statement:
            ready.set()
            assert release.wait(10)

    event.listen(cp.worker.engine, "before_cursor_execute", before_finish)
    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(run, cp, stage)
            try:
                assert ready.wait(10)
                cp.control.invalidate(A, cp.attempt, 1)
            finally:
                release.set()
            assert not future.result(timeout=15)
    finally:
        event.remove(cp.worker.engine, "before_cursor_execute", before_finish)
    with cp.admin.connect() as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM knowledge_artifacts WHERE job_id=:id"),
                {"id": cp.job["id"]},
            )
            == 1
        )


def test_restore_callback_never_runs_when_abort_outcome_unknown(cp, monkeypatch):
    restored = []

    def unavailable(*args):
        raise ConnectionError("synthetic persistence failure")

    monkeypatch.setattr(cp.control, "invalidate", unavailable)
    with pytest.raises(ConnectionError):
        cp.control.abort_before_restore(A, cp.attempt, 1, lambda: restored.append(True))
    assert restored == []


def test_unauthenticated_route_and_fake_worker_name(cp, orchestrator):
    assert orchestrator.claim(cp.stage, "authenticated-pilot") is None
    with pytest.raises(DBAPIError, match="permission denied"):
        with orchestrator.engine.begin() as c:
            c.execute(
                text("SELECT * FROM rv.pilot_claim(:sid,:aid,1,:sha,'sample')"),
                {"sid": cp.stage, "aid": cp.attempt, "sha": cp.manifest.sha256},
            )
    assert cp.hub.calls == 0


def test_stage_receipt_does_not_survive_new_generation(cp):
    lease = cp.worker.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample")
    assert lease
    with cp.worker.engine.begin() as c:
        assert c.scalar(
            text("SELECT rv.pilot_verified(:id,:f,:sha)"),
            {"id": cp.stage, "f": lease["fence"], "sha": cp.manifest.sha256},
        )
    cp.control.invalidate(A, cp.attempt, 1)
    assert cp.worker.claim(cp.stage, cp.attempt, 2, cp.manifest.sha256, "sample") is None


def test_selected_hash_tampering_fails_before_archive_publication(cp):
    family = cp.manifest.families[0]
    changed = family.model_copy(
        update={"files": (family.files[0].model_copy(update={"sha256": "d" * 64}), family.files[1])}
    )
    manifest = cp.manifest.model_copy(update={"families": (changed,)})
    attempt = uuid4()
    cp.control.register(A, attempt, manifest)
    pid = UUID(project(cp.clients[0], "Synthetic changed-source approval"))
    jid = cp.control.admit(A, attempt, 1, "sample", pid, cp.snapshot)
    job = cp.clients[0].get(f"/v1/jobs/{jid}").json()
    assert not cp.worker.run(UUID(job["stages"][1]["id"]), attempt, 1, manifest.sha256, "sample")
    assert cp.control.status(A, attempt)["state"] == "INVALIDATED"
    with cp.admin.connect() as c:
        assert (
            c.scalar(text("SELECT count(*) FROM knowledge_artifacts WHERE job_id=:id"), {"id": jid})
            == 0
        )


def test_manifest_commitment_and_engine_missing_fail_closed(cp):
    manifest = cp.manifest.model_copy(update={"engine_files": {}})
    attempt = uuid4()
    cp.control.register(A, attempt, manifest)
    pid = UUID(project(cp.clients[0], "Synthetic missing engine attestation"))
    jid = cp.control.admit(A, attempt, 1, "sample", pid, cp.snapshot)
    job = cp.clients[0].get(f"/v1/jobs/{jid}").json()
    assert not cp.worker.run(UUID(job["stages"][1]["id"]), attempt, 1, manifest.sha256, "sample")
    assert cp.hub.calls == 0
    assert cp.control.status(A, attempt)["state"] == "INVALIDATED"


def test_real_celery_restart_redelivery_cannot_revive_invalidated_pilot(cp, settings):
    import os
    import subprocess
    import sys
    import time

    import redis
    from celery import Celery

    # Reproduce the incident's *old* durable retry state, then the controller timeout,
    # service restoration, original outbox delivery and stale claim in one scenario.
    # Only this disposable admin fault injection can bypass the new fail-closed route.
    notification = cp.worker.deliveries(cp.attempt, 1)[0]
    lease = cp.worker.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample")
    assert lease
    cp.hub.timeout = True
    with pytest.raises(AnalysisError, match="github_timeout"):
        cp.hub.download("/example/demo/tar.gz/" + "a" * 40, io.BytesIO(), 1024, lambda: None)
    with cp.admin.begin() as c:
        c.execute(text("SELECT set_config('repovox.owner_id',:owner,true)"), {"owner": str(A)})
        c.execute(
            text("SELECT rv.cp_original_fail_analysis(:id,:fence,'github_timeout',true)"),
            {"id": cp.stage, "fence": lease["fence"]},
        )
        assert (
            c.scalar(text("SELECT state FROM job_stages WHERE id=:id"), {"id": cp.stage})
            == "retry_wait"
        )
    restored = []
    cp.control.abort_before_restore(A, cp.attempt, 1, lambda: restored.append(True))
    assert restored == [True]
    assert cp.control.status(A, cp.attempt)["state"] == "INVALIDATED"
    broker = Celery("synthetic-cp-replay", broker=settings.redis_url)
    queue = redis.Redis.from_url(settings.redis_url)
    queue.flushdb()  # This fixture runs only in the newly isolated disposable test cluster.
    task_id = str(notification["event_id"])
    broker.send_task("repovox.stage", args=[str(cp.stage)], task_id=task_id, retry=False)
    assert queue.llen("celery") == 1
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
            "--hostname=cp-restarted",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with cp.admin.connect() as c:
                denied = c.scalar(
                    text(
                        "SELECT count(*) FROM pilot_audit WHERE attempt_id=:id "
                        "AND event='routine_claim_denied'"
                    ),
                    {"id": cp.attempt},
                )
            if denied and queue.llen("celery") == 0:
                break
            time.sleep(0.1)
        assert denied and queue.llen("celery") == 0
        with cp.admin.connect() as c:
            assert (
                c.scalar(
                    text("SELECT attempt_count FROM job_stages WHERE id=:id"), {"id": cp.stage}
                )
                == 1
            )
            assert (
                c.scalar(
                    text("SELECT count(*) FROM knowledge_artifacts WHERE job_id=:id"),
                    {"id": cp.job["id"]},
                )
                == 0
            )
        assert cp.hub.calls == 1
    finally:
        worker.terminate()
        worker.wait(timeout=10)
        queue.flushdb()

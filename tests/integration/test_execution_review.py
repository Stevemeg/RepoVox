"""Actual PG/S3/scoped analyzer -> offline review under restricted UID 10002.

Only transport is synthetic. SQL claims, roles, closure, static analysis, projection,
filesystem durability, signatures, chronology and frozen scoring are real. The
reference is an explicitly empty/partial synthetic response, never proposed gold.
"""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

pytest.importorskip("fcntl")

from conftest import A
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from repovox.evaluation.custody_v2 import source_packet
from repovox.evaluation.v2 import (
    Policy,
    Provenance,
    Reference,
    Scope,
    SourceFile,
    Window,
    serialize,
)
from sqlalchemy import text
from test_custodian_lifecycle import available_tick
from test_custodian_review import grant_for, start_watchdog
from test_pilot_control import cp as cp
from test_pilot_control import run

from tools.phase2_custodian_adapter import (
    CustodianStore,
    ExecutionEvidenceStorage,
    LeaseBoundExecutor,
    PilotLeaseAdmission,
)
from tools.phase2_custodian_lifecycle import Lifecycle, canonical, digest
from tools.phase2_custodian_review import ReviewSession

pytestmark = pytest.mark.skipif(os.geteuid() != 10002, reason="restricted custodian integration")


@pytest.mark.parametrize(
    "cp",
    [
        pytest.param(dict(language=k, defer=True), id=k)
        for k in ["python", "javascript", "typescript"]
    ],
    indirect=True,
)
def test_real_execution_closure_and_independently_authorized_review(cp, tmp_path):
    before = datetime.now(UTC)
    family = cp.manifest.families[0]
    secret = "synthetic-local-authority"
    plan = dict(
        version="custodian-lifecycle-1.1",
        namespace="synthetic-integration",
        tenant="tenant-a",
        attempt=str(cp.attempt),
        manifest_sha256=cp.manifest.sha256,
        created_at=before.isoformat(),
        expires_at=(before + timedelta(seconds=45)).isoformat(),
        authorization_expires_at=(before + timedelta(seconds=45)).isoformat(),
        authorization_sha256=digest(secret.encode()),
    )
    root = tmp_path / "custody"
    receipt = Lifecycle.create(root, plan)
    life = Lifecycle(root, plan, receipt)
    token = dict(
        tenant="tenant-a",
        namespace=plan["namespace"],
        attempt=plan["attempt"],
        generation=1,
        secret=secret,
    )
    process, probe = start_watchdog(life, tmp_path)
    life.activate(token, probe.proof(plan))
    restart_dir = os.environ.get("RV_PROTOCOL_RESTART_DIR")
    if restart_dir and "app.py" in cp.hub.bodies:
        # The host coordinator must use this already fixed namespace deadline,
        # rather than charging Python/container startup to custody's lifetime.
        checkpoint = Path(restart_dir)
        marker = checkpoint / "namespace-ready.json"
        with marker.open("xb") as target:
            target.write(
                canonical(
                    dict(
                        namespace=plan["namespace"],
                        attempt=str(cp.attempt),
                        created_at=plan["created_at"],
                        expires_at=plan["expires_at"],
                    )
                )
            )
            target.flush()
            os.fsync(target.fileno())
        marker.chmod(0o600)
    admitted = cp.control.admit(A, cp.attempt, 1, "sample", cp.pid, cp.snapshot)
    assert admitted
    cp.job = cp.clients[0].get(f"/v1/jobs/{admitted}").json()
    cp.stage = UUID(cp.job["stages"][1]["id"])
    leases = []
    records = []
    try:
        # No closure receipt can exist while execution is merely ACTIVE.
        with pytest.raises(ValueError, match="successful_execution_closure_required"):
            ReviewSession.establish(
                life,
                token,
                cp.control,
                A,
                1,
                cp.manifest,
                family,
                b"",
                b"",
                [],
                b"",
                {},
                tmp_path,
                probe,
            )
        proof_bodies = [
            b"SYNTHETIC RIGHTS",
            b"SYNTHETIC SNAPSHOT PIN",
            b"SYNTHETIC RESPONSE: annotations intentionally partial and empty.",
            b"SYNTHETIC SOURCE ONLY ATTESTATION",
        ]
        proofs = {digest(b): b for b in proof_bodies}
        scope = Scope(
            policy=Policy(),
            usage="SYNTHETIC_FIXTURE",
            tenant_id="tenant-a",
            analysis_owner_id=str(A),
            family_id=family.id,
            repository=family.repository,
            commit_sha=family.commit,
            rights_decision="PERMITTED_INTERNAL_EXPLORATORY",
            rights_evidence_sha256=digest(proof_bodies[0]),
            snapshot_verification_sha256=digest(proof_bodies[1]),
            files=[
                SourceFile(
                    path=f.path,
                    file_sha256=f.sha256,
                    size=f.size,
                    language=(
                        {"py": "python", "js": "javascript", "ts": "typescript"}.get(
                            f.path.rsplit(".", 1)[-1], "documentation"
                        )
                    ),
                    windows=[
                        Window(
                            path=f.path,
                            file_sha256=f.sha256,
                            start_line=1,
                            end_line=cp.hub.bodies[f.path][:-1].count(b"\n") + 1,
                            start_byte=0,
                            end_byte=f.size,
                        )
                    ],
                )
                for f in family.files
            ],
            limitations=["Synthetic partial fixture only; no independent accuracy claim."],
        )
        source = tmp_path / "source-for-initial-validation"
        source.mkdir(mode=0o700)
        for f in family.files:
            path = source / f.path
            path.write_bytes(cp.hub.bodies[f.path])
            path.chmod(0o600)
        scope_body = serialize(scope)
        packet = serialize(source_packet(scope_body, digest(scope_body), source, proofs))
        metadata = dict(
            tenant_id="tenant-a",
            session_id="synthetic-execution-review",
            scope_sha256=digest(scope_body),
            engineering_commit=cp.manifest.engine,
            scorer_commit=cp.manifest.scorer,
            trusted_context="SYNTHETIC PROTOCOL",
            identity_basis="synthetic_fixture",
        )
        for stage in cp.job["stages"][1:9]:
            stage_id = UUID(stage["id"])
            gate = PilotLeaseAdmission(
                cp.worker, cp.attempt, 1, cp.manifest.sha256, "sample", stage_id, "tenant-a"
            )
            leases.append(gate.lease)
            store = CustodianStore(life, token, gate, probe)
            if len(leases) == 1:
                for body in [
                    scope_body,
                    packet,
                    *[b for i, b in enumerate(proof_bodies) if i != 2],
                    *[cp.hub.bodies[f.path] for f in family.files],
                ]:
                    store.write("tenant-a", body)
                records.append(
                    store.append_event(records, **metadata, payload_sha256=digest(packet))
                )

            collector = (
                ExecutionEvidenceStorage(cp.worker.storage, store, scope_body, records)
                if len(leases) == 8
                else None
            )
            executor = LeaseBoundExecutor(cp.worker, gate, collector)
            assert executor.run(stage_id, cp.attempt, 1, cp.manifest.sha256, "sample")
            assert not LeaseBoundExecutor(cp.worker, gate).run(
                stage_id, cp.attempt, 1, cp.manifest.sha256, "sample"
            )
        assert len(leases) == 8 and cp.hub.calls == 1
        assert collector is not None
        envelope_body, pred, records = (
            collector.analysis_body,
            collector.prediction,
            collector.records,
        )
        assert b"excluded_sentinel" not in envelope_body and len(records) == 2
        # Disposable clock fixture: close successfully before an intentionally short
        # execution authorization expires, then conduct review after it has expired.
        # Runtime roles cannot edit this field; no real deadline is changed/extended.
        with cp.admin.begin() as c:
            c.execute(text("SET LOCAL session_replication_role=replica"))
            c.execute(
                text(
                    "UPDATE pilot_attempts SET expires_at=clock_timestamp()+"
                    "interval '0.75 seconds' WHERE id=:id"
                ),
                {"id": cp.attempt},
            )
        assert cp.control.close(A, cp.attempt, 1) == "EXECUTION_CLOSED"
        time.sleep(0.8)
        with cp.admin.connect() as c:
            assert c.scalar(
                text("SELECT expires_at<clock_timestamp() FROM pilot_attempts WHERE id=:id"),
                {"id": cp.attempt},
            )
        with cp.worker.engine.begin() as c:
            for lease in leases:
                assert (
                    c.scalar(
                        text("SELECT rv.pilot_scope(:stage,:fence)"),
                        {"stage": lease["stage_id"], "fence": lease["fence"]},
                    )
                    is None
                )
        cp.worker.engine.dispose()
        assert not run(cp)
        assert not cp.worker.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample")
        key = Ed25519PrivateKey.generate()  # Explicitly synthetic, not an owner signature.
        session = ReviewSession.establish(
            life,
            token,
            cp.control,
            A,
            1,
            cp.manifest,
            family,
            scope_body,
            envelope_body,
            records,
            key.public_key().public_bytes_raw(),
            {digest(b): b for i, b in enumerate(proof_bodies) if i != 2},
            source,
            probe,
        )
        # A real controller process exits after observing durable closure. Reopening
        # the offline session must neither claim work nor replace the binding.
        crash_code = """
import json,os,sys
import psycopg
from tools.phase2_custodian_lifecycle import identity
identity()
data=json.load(sys.stdin)
with psycopg.connect(data['url'].replace('postgresql+psycopg:','postgresql:',1),
                    connect_timeout=2,options='-c statement_timeout=2000') as connection:
 with connection.cursor() as cursor:
  cursor.execute("SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles "
                 "WHERE rolname=current_user")
  assert not any(cursor.fetchone())
  cursor.execute("SELECT pg_has_role(session_user,'rv_pilot_controller','member'),"
                 "pg_has_role(session_user,'rv_executor','member')")
  assert cursor.fetchone()==(True,False)
  cursor.execute("SELECT version_num FROM alembic_version")
  assert cursor.fetchone()[0]=='0004'
  cursor.execute("SELECT set_config('repovox.owner_id',%s,true)",(data['owner'],))
  cursor.execute("SELECT rv.pilot_status(%s)->>'state'",(data['attempt'],))
  assert cursor.fetchone()[0]=='EXECUTION_CLOSED'
os._exit(79)
"""
        crashed = subprocess.run(
            [sys.executable, "-c", crash_code],
            input=canonical(
                dict(
                    url=cp.engines[0].url.render_as_string(hide_password=False),
                    owner=str(A),
                    attempt=str(cp.attempt),
                )
            ),
            capture_output=True,
            timeout=5,
        )
        assert crashed.returncode == 79, crashed.stderr
        session = ReviewSession(
            life,
            token,
            session.session,
            key.public_key().public_bytes_raw(),
            session.binding_sha,
            probe,
        )
        if restart_dir and "app.py" in cp.hub.bodies:
            checkpoint = Path(restart_dir)
            marker = checkpoint / "restart-ready.json"
            with marker.open("xb") as target:
                target.write(
                    canonical(
                        dict(
                            attempt=str(cp.attempt),
                            state="EXECUTION_CLOSED",
                            expires_at=plan["expires_at"],
                        )
                    )
                )
            marker.chmod(0o600)
            until = time.monotonic() + 15
            while not (checkpoint / "restart-complete").exists() and time.monotonic() < until:
                time.sleep(0.05)
            assert (
                checkpoint / "restart-complete"
            ).read_bytes() == b"verified-new-environment-only"
            for engine in [cp.control.engine, cp.worker.engine, cp.admin, *cp.engines]:
                engine.dispose()
            assert cp.control.status(A, cp.attempt)["state"] == "EXECUTION_CLOSED"
            assert not run(cp)
        ref = Reference(
            policy=Policy(),
            tenant_id="tenant-a",
            family_id=family.id,
            repository=family.repository,
            commit_sha=family.commit,
            scope_sha256=digest(scope_body),
            blind_source_sha256=digest(packet),
            prediction_commitment_sha256=digest(serialize(pred)),
            annotation_scope="partial",
            scope_description="Empty synthetic protocol response, not gold.",
            limitations=["No annotated facts; protocol test only."],
            provenance=Provenance(
                author_role="SYNTHETIC_TEST_AUTHOR",
                response_capture_sha256=digest(proof_bodies[2]),
                source_only_attestation_sha256=digest(proof_bodies[3]),
                identity_basis="synthetic_fixture",
            ),
            assertions=[],
            observations=[],
            revision=1,
            supersedes_sha256=None,
            correction_reason=None,
            correction_citations=[],
        )
        outputs = {}
        for operation, payload in [
            ("handoff", packet),
            ("capture", proof_bodies[2]),
            ("seal_reference", serialize(ref)),
            ("reveal", serialize(pred)),
            ("compare", serialize(ref)),
        ]:
            signed, approval = grant_for(session, key, operation, payload)
            outputs[operation] = session.perform(signed, approval, payload)[0]
        assert outputs["handoff"] == packet and serialize(pred) not in outputs["handoff"]
        assert json.loads(outputs["compare"])["completeness"]["acceptance_status"] == "INCOMPLETE"
        assert session.records()[:2] == records
        head = session.records()[-1][0]
        signed, approval = grant_for(session, key, "close", head)
        session.perform(signed, approval, head)
        assert available_tick(life)["state"] == "SEALED"
        # Close does not modify the initial immutable receipt/deadline or SQL terminal state.
        assert (life.control / "identity.json").read_bytes() == canonical(receipt)
        assert cp.control.status(A, cp.attempt)["state"] == "EXECUTION_CLOSED"
        result = dict(
            language=scope.files[0].language,
            attempt=str(cp.attempt),
            closure=cp.control.status(A, cp.attempt),
            analysis_sha256=digest(envelope_body),
            prediction_sha256=digest(serialize(pred)),
            source_sha256=digest(packet),
            event_sha256=[sha for _, sha in session.records()],
            receipt_sha256=digest(canonical(receipt)),
            deadline=plan["expires_at"],
            elapsed_seconds=(datetime.now(UTC) - before).total_seconds(),
            controller_process_crash_exit=crashed.returncode,
            real_database_worker_restart=bool(restart_dir and "app.py" in cp.hub.bodies),
        )
        from test_custodian_lifecycle import record

        record("genuine-execution-review", result)
        # Explicit withdrawal cleans synthetic bytes without shortening any real deadline.
        life.transition(token, "WITHDRAWN")
        assert available_tick(life)["state"] == "EXPIRED"
        assert not list(life.data.iterdir())
        # The independent synthetic coordinator also removes its exact execution
        # spool. Review capabilities themselves contain no S3 or worker credentials.
        job_id = UUID(cp.job["id"])
        snapshot_id = leases[0]["snapshot_id"]
        cp.worker.storage.delete_prefix(A, snapshot_id, job_id)
        remaining = cp.worker.storage.client.list_objects_v2(
            Bucket=cp.worker.storage.bucket,
            Prefix=f"development/{A}/{snapshot_id}/{job_id}/",
        )
        assert remaining["KeyCount"] == 0
        for f in family.files:
            (source / f.path).unlink()
        assert not list(source.iterdir())
        record(
            "genuine-execution-cleanup",
            dict(
                attempt=str(cp.attempt),
                custody_remaining=0,
                spool_remaining=remaining["KeyCount"],
                source_validation_remaining=0,
                synthetic_only=True,
            ),
        )
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize("terminal", ["cancelled", "expired"])
def test_failed_attempt_cannot_bootstrap_offline_authority(cp, tmp_path, terminal):
    now = datetime.now(UTC)
    plan = dict(
        version="custodian-lifecycle-1.1",
        namespace="synthetic-rejected",
        tenant="tenant-a",
        attempt=str(cp.attempt),
        manifest_sha256=cp.manifest.sha256,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=10)).isoformat(),
        authorization_expires_at=(now + timedelta(seconds=10)).isoformat(),
        authorization_sha256=digest(b"synthetic-only"),
    )
    receipt = Lifecycle.create(tmp_path / "rejected", plan)
    life = Lifecycle(tmp_path / "rejected", plan, receipt)
    token = dict(
        tenant="tenant-a",
        namespace=plan["namespace"],
        attempt=plan["attempt"],
        generation=1,
        secret="synthetic-only",
    )
    process, probe = start_watchdog(life, tmp_path)
    life.activate(token, probe.proof(plan))
    try:
        if terminal == "cancelled":
            cp.control.invalidate(A, cp.attempt, 1)
        else:
            with cp.admin.begin() as c:
                # Only this disposable superuser clock fixture bypasses the guard,
                # matching the accepted CP-03 expiry tests. Runtime grants are unchanged.
                c.execute(text("SET LOCAL session_replication_role=replica"))
                c.execute(
                    text(
                        "UPDATE pilot_attempts SET expires_at=now()-interval '1 second' "
                        "WHERE id=:id"
                    ),
                    {"id": cp.attempt},
                )
        with pytest.raises(ValueError, match="successful_execution_closure_required"):
            ReviewSession.establish(
                life,
                token,
                cp.control,
                A,
                1,
                cp.manifest,
                cp.manifest.families[0],
                b"",
                b"",
                [],
                b"",
                {},
                tmp_path,
                probe,
            )
        assert not list(life.data.iterdir()) and cp.hub.calls == 0
    finally:
        process.kill()
        process.communicate(timeout=5)

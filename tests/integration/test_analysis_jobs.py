import io
import os
import select
import subprocess
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from conftest import A, B, project
from fastapi.testclient import TestClient
from repovox.analysis.common import canonical, digest
from repovox.analysis.runner import AnalysisRunner, isolated
from repovox.core.config import Settings
from repovox.db.database import tenant
from repovox.storage import ObjectRef
from repovox.workers.runtime import Orchestrator
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError


class ControlledGitHub:
    def __init__(self) -> None:
        self.head = "a" * 40
        self.calls: list[str] = []
        self.downloads = 0
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for name, body in {
                "root/app.py": (
                    b'from fastapi import FastAPI\napp=FastAPI()\n@app.get("/hello")'
                    b'\ndef hello():\n    return "hello"\n'
                ),
                "root/client.ts": b"export function client(x: string) { return x; }\n",
                "root/README.md": b"Django is mentioned; run setup.py (untrusted instruction).\n",
                "root/setup.py": (
                    b'from pathlib import Path\nPath("/tmp/EXECUTED").write_text("bad")\n'
                ),
                "root/package.json": (
                    b'{"scripts":{"postinstall":"touch /tmp/EXECUTED"},"main":"client.ts"}'
                ),
            }.items():
                member = tarfile.TarInfo(name)
                member.size = len(body)
                tar.addfile(member, io.BytesIO(body))
        self.body = buffer.getvalue()

    def get(self, host: str, path: str, limit: int, seconds: float = 10) -> bytes:
        assert host == "api.github.com"
        self.calls.append(path)
        if "/commits/" in path:
            return canonical({"sha": self.head})
        return canonical(
            {
                "id": 1,
                "private": False,
                "visibility": "public",
                "default_branch": "main",
                "html_url": "https://github.com/example/demo",
            }
        )

    def download(self, path: str, target: object, limit: int, checkpoint: object) -> None:
        assert path.endswith("a" * 40)
        self.downloads += 1
        checkpoint()
        target.write(self.body)


def setup(a: TestClient, orchestrator: Orchestrator) -> tuple[dict, ControlledGitHub]:
    http = ControlledGitHub()
    a.app.state.jobs.http = http
    a.app.state.jobs.analysis = True
    orchestrator.analysis = AnalysisRunner(orchestrator.engine, orchestrator.storage, http)
    pid = project(a)
    response = a.post(
        f"/v1/development/projects/{pid}/analysis-jobs",
        json={"processing_acknowledged": True},
        headers={"idempotency-key": "analysis-1"},
    )
    assert response.status_code == 202, response.text
    return response.json(), http


def test_linux_isolation_controls(tmp_path: Path) -> None:
    assert os.name == "posix" and os.getuid() != 0
    root = tmp_path / "assigned-source"
    root.mkdir()
    result = isolated(root, {"stage": 0}, lambda: None, 10)
    assert result == {
        "credentials_absent": True,
        "network_denied": True,
        "scratch_write_denied": True,
        "unassigned_file_denied": True,
    }
    assert not Path("/var/run/docker.sock").exists()
    with pytest.raises(OSError):
        Path("/workspace/base-write-tripwire").write_text("denied")


def test_real_stages_owner_artifacts_and_boundary(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
    admin: Engine,
    settings: Settings,
) -> None:
    a, b = clients
    job, http = setup(a, orchestrator)
    sid = UUID(job["stages"][1]["id"])
    assert orchestrator.run(sid, "acquisition")
    assert not orchestrator.run(sid, "duplicate")
    # A new process/runner consumes persisted results without downloading again.
    restarted = Orchestrator(
        orchestrator.engine,
        orchestrator.storage,
        AnalysisRunner(orchestrator.engine, orchestrator.storage, http),
    )
    for stage in job["stages"][2:9]:
        assert restarted.run(UUID(stage["id"]), "restarted"), a.get(f"/v1/jobs/{job['id']}").text
    state = a.get(f"/v1/jobs/{job['id']}").json()
    assert state["state"] == "failed" and state["error_code"] == "phase2_pipeline_boundary"
    assert all(s["state"] == "succeeded" for s in state["stages"][:9])
    assert all(s["state"] == "failed" for s in state["stages"][9:])
    assert http.downloads == 1 and len(http.calls) == 2
    result = a.get(f"/v1/development/jobs/{job['id']}/analysis")
    assert result.status_code == 200, result.text
    payload = result.json()["payload"]
    assert result.json()["schema_version"] == "2.3"
    assert payload["knowledge"]["canonical_facts"]
    assert payload["verification"]["counts"]["verified"] > 0
    assert payload["verification"]["counts"]["documentation_only"] == 1
    assert all(e["validation_status"] == "valid" for e in payload["evidence"]["items"])
    assert b.get(f"/v1/development/jobs/{job['id']}/analysis").status_code == 404
    assert not Path("/tmp/EXECUTED").exists()
    with tenant(a.app.state.engine, B) as c:
        assert c.scalar(text("SELECT count(*) FROM analysis_results")) == 0
        assert c.scalar(text("SELECT count(*) FROM repository_snapshots")) == 0
    with admin.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM video_artifacts")) == 0
        assert c.scalar(text("SELECT count(*) FROM knowledge_artifacts WHERE NOT synthetic")) == 8
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM knowledge_artifacts WHERE NOT synthetic "
                    "AND schema_version='2.3' AND versions->>'rules'='static-rules-v2'"
                )
            )
            == 8
        )
    with pytest.raises(DBAPIError, match="terminal_immutable"):
        with admin.begin() as c:
            c.execute(
                text("UPDATE generation_jobs SET state='running' WHERE id=:id"), {"id": job["id"]}
            )
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant(a.app.state.engine, A) as c:
            c.execute(text("SELECT * FROM evaluation.manifests"))


@pytest.mark.parametrize(
    "first,second",
    [("finish_analysis", "finish_analysis_v23"), ("finish_analysis_v23", "finish_analysis")],
)
def test_mixed_artifact_versions_rejected(clients, orchestrator, admin, first, second) -> None:
    a, _ = clients
    job, _ = setup(a, orchestrator)
    first_lease = orchestrator.claim(UUID(job["stages"][1]["id"]), "version-test")
    assert first_lease

    def completion(lease, function):
        with orchestrator.engine.begin() as c:
            scope = c.scalar(
                text("SELECT rv.analysis_scope(:id,:fence)"),
                {"id": lease["stage_id"], "fence": lease["fence"]},
            )
        hashes = [scope["validate_digest"], *[o["checksum"] for o in scope["outputs"]]]
        input_hash = digest(
            (scope["snapshot"]["commit_sha"] + "|phase2-static-v1|" + "|".join(hashes)).encode()
        )
        ref = ObjectRef(A, lease["snapshot_id"], lease["job_id"], uuid4(), "c" * 64, "analysis")
        with orchestrator.engine.begin() as c:
            return c.scalar(
                text(f"SELECT rv.{function}(:id,:fence,:artifact,:hash,:key,0,:input,'{{}}')"),
                {
                    "id": lease["stage_id"],
                    "fence": lease["fence"],
                    "artifact": ref.artifact,
                    "hash": ref.checksum,
                    "key": ref.key,
                    "input": input_hash,
                },
            )

    assert completion(first_lease, first)
    second_lease = orchestrator.claim(UUID(job["stages"][2]["id"]), "version-test")
    assert second_lease
    with pytest.raises(DBAPIError, match="analysis_version_mismatch"):
        completion(second_lease, second)
    with admin.connect() as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM knowledge_artifacts WHERE job_id=:job"),
                {"job": job["id"]},
            )
            == 1
        )
    if first == "finish_analysis":
        # Reject before attempting to read the intentionally absent synthetic object.
        assert not orchestrator.analysis.run(second_lease, lambda: True)
        assert a.get(f"/v1/jobs/{job['id']}").json()["error_code"] == "artifact_corrupt"


def test_versioned_completion_permissions(admin: Engine) -> None:
    with admin.connect() as c:
        for name in [
            "finish_analysis_v23(uuid,bigint,uuid,text,text,bigint,text,jsonb)",
            "analysis_scope_v23(uuid,bigint)",
        ]:
            for role, expected in [("rv_app", False), ("rv_worker", True)]:
                assert (
                    c.scalar(
                        text("SELECT has_function_privilege(:role,:function,'EXECUTE')"),
                        {"role": role, "function": "rv." + name},
                    )
                    is expected
                )


def test_analysis_stale_upload_cancel_and_deadline(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
    admin: Engine,
) -> None:
    a, _ = clients
    job, _ = setup(a, orchestrator)
    sid = UUID(job["stages"][1]["id"])
    lease = orchestrator.claim(sid, "will-die-after-upload")
    assert lease
    ref = ObjectRef(
        A, lease["snapshot_id"], lease["job_id"], uuid4(), digest(b"orphan"), "analysis"
    )
    orchestrator.storage.write(ref, b"orphan")
    assert a.post(f"/v1/jobs/{job['id']}/cancel").status_code == 200
    with orchestrator.engine.begin() as c:
        assert not c.scalar(
            text("SELECT rv.finish_analysis(:id,:fence,:artifact,:hash,:key,6,:input,'{}')"),
            {
                "id": sid,
                "fence": lease["fence"],
                "artifact": ref.artifact,
                "hash": ref.checksum,
                "key": ref.key,
                "input": "a" * 64,
            },
        )
    deletion = a.delete(f"/v1/projects/{job['project_id']}").json()
    orchestrator.cleanup(UUID(deletion["deletion_id"]))
    assert a.get(f"/v1/jobs/{job['id']}").status_code == 404
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError):
        orchestrator.storage.read(A, ref)


def test_idempotency_and_retry_preserve_head(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
) -> None:
    a, _ = clients
    job, http = setup(a, orchestrator)
    http.head = "b" * 40
    repeated = a.post(
        f"/v1/development/projects/{job['project_id']}/analysis-jobs",
        json={"processing_acknowledged": True},
        headers={"idempotency-key": "analysis-1"},
    )
    assert repeated.json()["id"] == job["id"] and len(http.calls) == 2
    a.post(f"/v1/jobs/{job['id']}/cancel")
    retry = a.post(
        f"/v1/development/jobs/{job['id']}/retry", headers={"idempotency-key": "analysis-retry"}
    )
    assert retry.status_code == 202, retry.text
    assert orchestrator.run(UUID(retry.json()["stages"][1]["id"]), "retry-pinned")
    assert len(http.calls) == 2 and http.downloads == 1


def test_cross_job_artifact_fk(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
    admin: Engine,
) -> None:
    a, _ = clients
    job, _ = setup(a, orchestrator)
    with pytest.raises(DBAPIError):
        with admin.begin() as c:
            c.execute(
                text(
                    "INSERT INTO analysis_results(owner_id,job_id,snapshot_id,art"
                    "ifact_id,state,summary) VALUES(:owner,:job,:snapshot,:artifa"
                    "ct,'verified_static_analysis','{}')"
                ),
                {"owner": B, "job": job["id"], "snapshot": uuid4(), "artifact": uuid4()},
            )


@pytest.mark.parametrize("mode", ["acquire", "uploaded"])
def test_actual_worker_death_and_recovery(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
    admin: Engine,
    mode: str,
) -> None:
    import json

    a, _ = clients
    job, http = setup(a, orchestrator)
    sid = UUID(job["stages"][1]["id"])
    process = subprocess.Popen(
        [sys.executable, "tools/phase2_worker_fault.py", str(sid), "--mode", mode],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    try:
        assert select.select([process.stdout], [], [], 10)[0], (
            "Fault process did not reach checkpoint"
        )
        marker = json.loads(process.stdout.readline())
        assert marker["ready"] and marker["pid"] == process.pid
        process.kill()
        assert process.wait(timeout=5) < 0
        with admin.begin() as c:
            c.execute(
                text(
                    "UPDATE job_stages SET lease_expires_at=now()-interval '1 second' WHERE id=:id"
                ),
                {"id": sid},
            )
        orchestrator.reconcile()
        with admin.begin() as c:
            c.execute(
                text(
                    "UPDATE job_stages SET next_attempt_at=now()-interval '1 second' WHERE id=:id"
                ),
                {"id": sid},
            )
        orchestrator.reconcile()
        http.head = "b" * 40
        assert orchestrator.run(sid, "replacement-after-actual-kill")
        state = a.get(f"/v1/jobs/{job['id']}").json()
        assert state["stages"][1]["attempt_count"] == 2
        assert state["attempts"][1]["outcome"] == "lease_expired"
        assert state["commit_sha"] == "a" * 40
        assert http.downloads == 1
        deletion = a.delete(f"/v1/projects/{job['project_id']}").json()
        orchestrator.cleanup(UUID(deletion["deletion_id"]))
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_concurrent_analysis_admission_reuses_immutable_snapshot(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
    admin: Engine,
) -> None:
    a, _ = clients
    http = ControlledGitHub()
    a.app.state.jobs.http = http
    a.app.state.jobs.analysis = True
    pid = project(a)

    def submit(index: int):
        return a.post(
            f"/v1/development/projects/{pid}/analysis-jobs",
            json={"processing_acknowledged": True},
            headers={"idempotency-key": f"distinct-{index}"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [1, 2]))
    assert [r.status_code for r in results] == [202, 202], [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 2
    with admin.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM repository_snapshots WHERE NOT synthetic")) == 1


def test_secret_canary_never_reaches_objects_logs_or_http(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
    admin: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, _ = clients
    job, http = setup(a, orchestrator)
    canary = "ghp_" + "a" * 36
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        data = canary.encode()
        member = tarfile.TarInfo("root/canary.txt")
        member.size = len(data)
        tar.addfile(member, io.BytesIO(data))
    http.body = buffer.getvalue()
    assert not orchestrator.run(UUID(job["stages"][1]["id"]), "secret-screening")
    response = a.get(f"/v1/jobs/{job['id']}")
    assert response.json()["error_code"] == "secret_detected"
    assert canary not in response.text and canary not in caplog.text
    assert a.get(f"/v1/development/jobs/{job['id']}/analysis").status_code == 404
    with admin.connect() as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM knowledge_artifacts WHERE job_id=:id"), {"id": job["id"]}
            )
            == 0
        )
        snapshot_id = c.scalar(
            text("SELECT snapshot_id FROM generation_jobs WHERE id=:id"), {"id": job["id"]}
        )
    response = orchestrator.storage.client.list_objects_v2(
        Bucket=orchestrator.storage.bucket, Prefix=f"development/{A}/{snapshot_id}/{job['id']}/"
    )
    assert response.get("KeyCount", 0) == 0

"""Media database integration: separate schema track, lifecycle, isolation, recovery, playback.

Runs only against the disposable Compose databases and object store with synthetic source.
The core database must stay at revision 0004 with its accepted functions unchanged.
"""

import hashlib
import io
import json
import os
import subprocess
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from conftest import A, B, project
from fastapi.testclient import TestClient
from repovox.analysis.runner import AnalysisRunner
from repovox.core.config import Settings
from repovox.db.database import tenant
from repovox.media.store import MediaStorage, media_key
from repovox.media.worker import MediaWorker, make_media_engine
from repovox.workers.runtime import Orchestrator
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from test_analysis_jobs import ControlledGitHub

FIXTURE = Path(__file__).parents[1] / "fixtures" / "architectures" / "custom_unnamed"
TABLES = "media_videos,media_artifacts,media_history,media_attempts,media_stages,media_jobs"


class SyntheticRepository(ControlledGitHub):
    """Serves a locally authored fixture as the pinned archive; no network is used."""

    def __init__(self) -> None:
        super().__init__()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for path in sorted(FIXTURE.glob("*.py")):
                body = path.read_bytes()
                member = tarfile.TarInfo(f"root/{path.name}")
                member.size = len(body)
                tar.addfile(member, io.BytesIO(body))
        self.body = buffer.getvalue()


@pytest.fixture
def media_admin() -> Iterator[Engine]:
    engine = create_engine(os.environ["REPOVOX_TEST_MEDIA_ADMIN_URL"])
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {TABLES}"))
    yield engine
    engine.dispose()


@pytest.fixture
def worker(settings: Settings, media_admin: Engine) -> Iterator[MediaWorker]:
    assert settings.media_worker_database_url is not None
    engine = make_media_engine(settings.media_worker_database_url.get_secret_value(), "rvm_worker")
    yield MediaWorker(engine, MediaStorage(settings), "integration-worker")
    engine.dispose()


def submit(a: TestClient, orchestrator: Orchestrator, key: str = "video-1") -> dict[str, Any]:
    http = SyntheticRepository()
    a.app.state.jobs.http = http
    a.app.state.jobs.analysis = True
    orchestrator.analysis = AnalysisRunner(orchestrator.engine, orchestrator.storage, http)
    response = a.post(
        f"/v1/projects/{project(a)}/video-jobs",
        json={"processing_acknowledged": True},
        headers={"idempotency-key": key},
    )
    assert response.status_code == 202, response.text
    return response.json()


def analyse(a: TestClient, orchestrator: Orchestrator, job: dict[str, Any]) -> None:
    core = a.get(f"/v1/jobs/{job['analysis_job_id']}").json()
    for stage in core["stages"][1:9]:
        assert orchestrator.run(UUID(stage["id"]), "analysis"), a.get(f"/v1/jobs/{core['id']}").text
    settled = a.get(f"/v1/jobs/{core['id']}").json()
    assert (settled["state"], settled["error_code"]) == ("failed", "phase2_pipeline_boundary")


def status(client: TestClient, job: dict[str, Any]) -> dict[str, Any]:
    response = client.get(f"/v1/video-jobs/{job['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def expire_lease(media_admin: Engine, job: dict[str, Any]) -> None:
    with media_admin.begin() as c:
        c.execute(
            text(
                "UPDATE media_stages SET lease_expires_at=clock_timestamp()-interval '1 second' "
                "WHERE job_id=:id AND state='running'"
            ),
            {"id": job["id"]},
        )


def make_due(media_admin: Engine, job: dict[str, Any]) -> None:
    with media_admin.begin() as c:
        c.execute(
            text(
                "UPDATE media_stages SET next_attempt_at=clock_timestamp()-interval '1 second' "
                "WHERE job_id=:id AND state='retry_wait'"
            ),
            {"id": job["id"]},
        )


def test_media_database_is_separate_and_core_is_unchanged(
    admin: Engine, media_admin: Engine, settings: Settings
) -> None:
    with admin.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0004"
        assert c.scalar(text("SELECT to_regclass('public.media_jobs')")) is None
        assert c.scalar(text("SELECT to_regnamespace('mv')")) is None
        guard = c.scalar(text("SELECT pg_get_functiondef('rv.job_guard()'::regprocedure)"))
        disabled = c.scalar(text("SELECT pg_get_functiondef('rv.video_disabled()'::regprocedure)"))
        assert "video_generation_disabled" in guard and "fixture='video'" not in guard
        assert "media" not in disabled.lower().replace("video_generation_disabled", "")
        assert c.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname='no_video'")) == 1
        for role in ("rvm_app", "rvm_worker", "rvm_migrator"):
            assert not c.scalar(
                text("SELECT has_database_privilege(:role,'repovox','CONNECT')"), {"role": role}
            )
        for role in ("rv_app", "rv_worker", "rv_pilot_controller", "rv_pilot_executor"):
            assert not c.scalar(
                text("SELECT has_database_privilege(:role,'repovox_media','CONNECT')"),
                {"role": role},
            )
    with media_admin.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "m001"
        assert c.scalar(text("SELECT to_regclass('public.generation_jobs')")) is None
        assert c.scalar(text("SELECT to_regclass('public.pilot_attempts')")) is None
        unsafe = c.execute(
            text(
                "SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace AND "
                "relkind='r' AND relname LIKE 'media_%' AND "
                "(NOT relrowsecurity OR NOT relforcerowsecurity)"
            )
        ).all()
        assert unsafe == []
        roles = c.execute(
            text(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'rvm_%' AND "
                "(rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb)"
            )
        ).all()
        assert roles == []
    assert settings.media_database_url is not None
    wrong = settings.media_database_url.get_secret_value().replace("/repovox_media", "/repovox")
    with pytest.raises(OperationalError):
        create_engine(wrong).connect()


def test_media_migration_refuses_the_core_database_and_guards_rollback(
    media_admin: Engine,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    database = "repovox_media_test_" + uuid4().hex
    with media_admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f'CREATE DATABASE "{database}" OWNER rvm_migrator'))
    previous = os.environ.get("REPOVOX_MEDIA_MIGRATION_DATABASE_URL")
    url = make_url(os.environ["REPOVOX_TEST_MEDIA_MIGRATION_URL"]).set(database=database)
    check = create_engine(
        make_url(os.environ["REPOVOX_TEST_MEDIA_ADMIN_URL"]).set(database=database)
    )
    config = Config("apps/api/alembic_media.ini")
    try:
        os.environ["REPOVOX_MEDIA_MIGRATION_DATABASE_URL"] = url.render_as_string(
            hide_password=False
        )
        command.upgrade(config, "head")
        with check.begin() as c:
            assert c.scalar(text("SELECT version_num FROM alembic_version")) == "m001"
            c.execute(text("SELECT set_config('repovox.owner_id',:o,true)"), {"o": str(A)})
            c.execute(text("SET LOCAL ROLE rvm_app"))
            job = c.scalar(
                text("SELECT mv.admit(:p,:a,'rollback-guard',repeat('a',64))"),
                {"p": uuid4(), "a": uuid4()},
            )
            assert job is not None
        with pytest.raises(DBAPIError, match="media_rollback_requires_empty_database"):
            command.downgrade(config, "base")
        with check.begin() as c:
            assert c.scalar(text("SELECT count(*) FROM media_jobs")) == 1
            c.execute(text(f"TRUNCATE {TABLES}"))
        command.downgrade(config, "base")
        with check.connect() as c:
            assert c.scalar(text("SELECT to_regclass('public.media_jobs')")) is None
            assert c.scalar(text("SELECT to_regnamespace('mv')")) is None
        # Pointing the media migration at the core database is refused before any change.
        os.environ["REPOVOX_MEDIA_MIGRATION_DATABASE_URL"] = os.environ["REPOVOX_TEST_ADMIN_URL"]
        with pytest.raises(RuntimeError, match="media_migration_refuses_core_database"):
            command.upgrade(config, "head")
    finally:
        check.dispose()
        if previous is None:
            os.environ.pop("REPOVOX_MEDIA_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["REPOVOX_MEDIA_MIGRATION_DATABASE_URL"] = previous
        with media_admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))


def test_submission_to_playback_publishes_both_video_categories(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
    worker: MediaWorker,
    media_admin: Engine,
    admin: Engine,
    tmp_path: Path,
) -> None:
    a, b = clients
    job = submit(a, orchestrator)
    assert job["state"] == "awaiting_analysis" and job["videos"] == []
    assert [s["stage_key"] for s in job["stages"]] == [
        "storyboard",
        "narration",
        "tts",
        "render",
        "encode",
        "architecture",
    ]
    assert not worker.run_once()  # Nothing runs before verified analysis is attached.
    analyse(a, orchestrator, job)
    attached = status(a, job)
    assert attached["state"] == "queued" and attached["commit_sha"] == "a" * 40
    assert status(a, job)["version"] == attached["version"]  # Attaching twice changes nothing.
    again = a.post(
        f"/v1/projects/{job['project_id']}/video-jobs",
        json={"processing_acknowledged": True},
        headers={"idempotency-key": "video-1"},
    )
    assert again.status_code == 202 and again.json()["id"] == job["id"]

    seen = []
    while worker.run_once():
        current = status(a, job)
        seen.append(current["state"])
        if current["state"] != "succeeded":
            assert current["videos"] == []  # Nothing is offered before the job succeeds.
    done = status(a, job)
    assert done["state"] == "succeeded", done
    assert done["architecture"] == "supported" and done["error_code"] is None
    assert all(s["state"] == "succeeded" for s in done["stages"])
    categories = [v["category"] for v in done["videos"]]
    assert categories.count("walkthrough") == 1 and categories.count("architecture") >= 1
    explainer = next(v for v in done["videos"] if v["category"] == "architecture")
    assert explainer["title"] == "cycle() in cycle.py"
    assert explainer["metadata"]["type"] == "component_graph"
    assert explainer["metadata"]["status"] == "VERIFIED"

    for video in done["videos"]:
        base = f"/v1/video-jobs/{job['id']}/videos/{video['id']}"
        full = a.get(base)
        assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
        assert full.headers["accept-ranges"] == "bytes"
        assert len(full.content) == video["byte_count"]
        assert hashlib.sha256(full.content).hexdigest() == video["checksum"]
        assert full.content[4:8] == b"ftyp"
        part = a.get(base, headers={"range": "bytes=0-99"})
        assert part.status_code == 206 and part.content == full.content[:100]
        assert part.headers["content-range"] == f"bytes 0-99/{video['byte_count']}"
        captions = a.get(f"{base}/captions")
        assert captions.status_code == 200 and captions.text.startswith("WEBVTT")
        assert "-->" in captions.text
        download = a.get(f"{base}/download")
        assert "attachment" in download.headers["content-disposition"]
        assert download.content == full.content
        path = tmp_path / f"{video['id']}.mp4"
        path.write_bytes(full.content)
        probed = json.loads(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-count_frames",
                    "-show_streams",
                    "-of",
                    "json",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        codecs = {s["codec_type"]: s["codec_name"] for s in probed["streams"]}
        assert codecs == {"video": "h264", "audio": "aac"}
        subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], check=True
        )
        # Another tenant can see none of it.
        for route in (base, f"{base}/captions", f"{base}/download"):
            assert b.get(route).status_code == 404
    assert b.get(f"/v1/video-jobs/{job['id']}").status_code == 404
    assert b.post(f"/v1/video-jobs/{job['id']}/cancel").status_code == 404
    assert a.get(f"/v1/video-jobs/{job['id']}/videos/{uuid4()}").status_code == 404
    assert a.get(f"/v1/video-jobs/{uuid4()}/videos/{done['videos'][0]['id']}").status_code == 404
    assert a.post(f"/v1/video-jobs/{job['id']}/cancel").status_code == 409

    with tenant(a.app.state.media_engine, B) as c:
        assert c.scalar(text("SELECT count(*) FROM media_jobs")) == 0
        assert c.scalar(text("SELECT count(*) FROM media_videos")) == 0
    with tenant(a.app.state.media_engine, A) as c:
        assert c.scalar(text("SELECT count(*) FROM media_videos")) == len(done["videos"])
    for statement, error in [
        ("UPDATE media_jobs SET state='running' WHERE id=:id", "terminal_immutable"),
        ("UPDATE media_videos SET title='x' WHERE job_id=:id", "published_immutable"),
        ("DELETE FROM media_videos WHERE job_id=:id", "published_immutable"),
        ("UPDATE media_stages SET state='ready' WHERE job_id=:id", "terminal_stage_immutable"),
    ]:
        with pytest.raises(DBAPIError, match=error):
            with media_admin.begin() as c:
                c.execute(text(statement), {"id": job["id"]})
    with media_admin.connect() as c:
        history = (
            c.execute(
                text("SELECT state FROM media_history WHERE job_id=:id ORDER BY version"),
                {"id": job["id"]},
            )
            .scalars()
            .all()
        )
    assert history[0] == "awaiting_analysis" and history[-1] == "succeeded"
    assert "queued" in history and "running" in history
    # The core database still records no video and no successful generation job.
    with admin.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM video_artifacts")) == 0
        assert c.scalar(text("SELECT count(*) FROM generation_jobs WHERE state='succeeded'")) == 0


def test_fencing_retry_recovery_and_cancellation(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
    worker: MediaWorker,
    media_admin: Engine,
) -> None:
    a, _ = clients
    job = submit(a, orchestrator)
    analyse(a, orchestrator, job)
    assert status(a, job)["state"] == "queued"
    first = worker.claim()
    assert first is not None and first["o_ordinal"] == 10 and first["o_attempt"] == 1
    assert worker.claim() is None  # One active stage per job.
    assert status(a, job)["state"] == "running"

    # The worker dies without reporting. Its lease expires and the stage is fenced off.
    expire_lease(media_admin, job)
    assert worker.reconcile() >= 1
    assert status(a, job)["state"] == "retry_wait"
    assert worker.claim() is None  # Backoff has not elapsed.
    make_due(media_admin, job)
    assert worker.reconcile() >= 1
    second = worker.claim()
    assert second is not None and second["o_fence"] > first["o_fence"] and second["o_attempt"] == 2

    def finish(lease: dict[str, Any], owner: UUID = A) -> Any:
        body = b"stale"
        checksum = hashlib.sha256(body).hexdigest()
        artifact = uuid4()
        key = media_key(owner, lease["o_job"], lease["o_ordinal"], artifact, checksum)
        with worker.engine.begin() as c:
            return c.scalar(
                text("SELECT mv.finish(:s,:f,:a,:c,:k,5,'{}'::jsonb)"),
                {
                    "s": lease["o_stage"],
                    "f": lease["o_fence"],
                    "a": artifact,
                    "c": checksum,
                    "k": key,
                },
            )

    assert finish(first) is False  # The dead worker's late result is rejected by its fence.
    with worker.engine.begin() as c:
        assert not c.scalar(
            text("SELECT mv.heartbeat(:s,:f)"), {"s": first["o_stage"], "f": first["o_fence"]}
        )
        assert c.scalar(
            text("SELECT mv.heartbeat(:s,:f)"), {"s": second["o_stage"], "f": second["o_fence"]}
        )
    with pytest.raises(DBAPIError, match="invalid_artifact"):
        finish(second, B)  # A key under another tenant's prefix is refused.
    with media_admin.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM media_artifacts")) == 0

    cancelled = a.post(f"/v1/video-jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["error_code"] == "owner_cancelled"
    assert all(s["state"] == "cancelled" for s in cancelled.json()["stages"])
    assert finish(second) is False and worker.claim() is None
    assert a.post(f"/v1/video-jobs/{job['id']}/cancel").status_code == 409
    assert worker.reconcile() == 0


def test_attempt_limit_and_transient_failure_end_the_job_explicitly(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
    worker: MediaWorker,
    media_admin: Engine,
) -> None:
    a, _ = clients
    job = submit(a, orchestrator)
    analyse(a, orchestrator, job)
    status(a, job)
    lease = worker.claim()
    assert lease is not None
    with worker.engine.begin() as c:
        assert c.scalar(
            text("SELECT mv.fail(:s,:f,'object_unavailable',true)"),
            {"s": lease["o_stage"], "f": lease["o_fence"]},
        )
    waiting = status(a, job)
    assert waiting["state"] == "retry_wait"
    assert waiting["stages"][0]["error_code"] == "object_unavailable"
    make_due(media_admin, job)
    worker.reconcile()
    lease = worker.claim()
    assert lease is not None and lease["o_attempt"] == 2
    expire_lease(media_admin, job)
    worker.reconcile()
    ended = status(a, job)
    assert (ended["state"], ended["error_code"]) == ("failed", "attempt_limit")
    assert ended["videos"] == [] and worker.claim() is None
    with media_admin.connect() as c:
        outcomes = (
            c.execute(
                text("SELECT outcome FROM media_attempts WHERE job_id=:id ORDER BY attempt_no"),
                {"id": job["id"]},
            )
            .scalars()
            .all()
        )
    assert outcomes == ["retry_wait", "lease_expired"]


def test_failed_analysis_ends_the_media_job(
    clients: tuple[TestClient, TestClient], orchestrator: Orchestrator, worker: MediaWorker
) -> None:
    a, _ = clients
    job = submit(a, orchestrator)
    assert a.post(f"/v1/jobs/{job['analysis_job_id']}/cancel").status_code == 200
    ended = status(a, job)
    assert (ended["state"], ended["error_code"]) == ("failed", "analysis_failed")
    assert not worker.run_once()


def test_idempotency_quota_and_role_boundaries(
    clients: tuple[TestClient, TestClient],
    orchestrator: Orchestrator,
    worker: MediaWorker,
    media_admin: Engine,
) -> None:
    a, _ = clients
    job = submit(a, orchestrator, "same-key")
    other = project(a, "Second")
    conflict = a.post(
        f"/v1/projects/{other}/video-jobs",
        json={"processing_acknowledged": True},
        headers={"idempotency-key": "same-key"},
    )
    assert conflict.status_code == 409
    missing = a.post(
        f"/v1/projects/{uuid4()}/video-jobs",
        json={"processing_acknowledged": True},
        headers={"idempotency-key": "nowhere"},
    )
    assert missing.status_code == 404
    unacknowledged = a.post(
        f"/v1/projects/{job['project_id']}/video-jobs", json={}, headers={"idempotency-key": "x"}
    )
    assert unacknowledged.status_code == 422
    app_engine = a.app.state.media_engine
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant(app_engine, A) as c:
            c.execute(text("SELECT * FROM mv.claim('intruder')"))
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant(app_engine, A) as c:
            c.execute(text("UPDATE media_jobs SET state='succeeded'"))
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant(app_engine, A) as c:
            c.execute(
                text(
                    "INSERT INTO media_videos(id,owner_id,job_id,category,position,title,"
                    "object_key,checksum,byte_count,captions,metadata,expires_at) VALUES("
                    "gen_random_uuid(),:o,:j,'walkthrough',0,'x','k',repeat('a',64),1,'c','{}',now())"
                ),
                {"o": A, "j": job["id"]},
            )
    with pytest.raises(DBAPIError, match="permission denied"):
        with worker.engine.begin() as c:
            c.execute(text("SELECT * FROM media_jobs"))
    with pytest.raises(DBAPIError, match="permission denied"):
        with worker.engine.begin() as c:
            c.execute(
                text("SELECT mv.admit(:p,:a,'k',repeat('a',64))"), {"p": uuid4(), "a": uuid4()}
            )
    with pytest.raises(DBAPIError, match="analysis_reference_conflict|invalid_analysis_reference"):
        with tenant(app_engine, A) as c:
            c.execute(
                text('SELECT mv.attach(:id,\'{"analysis_job_id":"forged"}\'::jsonb)'),
                {"id": job["id"]},
            )
    with pytest.raises(DBAPIError, match="not_found"):
        with tenant(app_engine, B) as c:
            c.execute(text("SELECT mv.cancel(:id)"), {"id": job["id"]})
    with media_admin.connect() as c:
        assert c.scalar(text("SELECT state FROM media_jobs WHERE id=:id"), {"id": job["id"]}) == (
            "awaiting_analysis"
        )

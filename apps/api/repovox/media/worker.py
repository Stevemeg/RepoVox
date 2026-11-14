"""Media worker: claims one fenced stage at a time from the media database and runs it.

Stages 10-14 produce the repository walkthrough; stage 15 produces architecture explainers
when the evidence supports them. Every stage re-validates its inputs, publishes its output to
object storage, then commits the pointer under its lease. A worker that loses its lease stops
and commits nothing; the reconciler retries the stage under a new fence.
"""

import hashlib
import json
import logging
import os
import signal
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, text

from repovox.analysis.archive import extract
from repovox.analysis.contracts import validate_envelope
from repovox.core.config import Settings
from repovox.core.errors import DomainError
from repovox.db.database import make_engine, rows
from repovox.media import stages
from repovox.media.architecture import check
from repovox.media.explainer import render_architecture
from repovox.media.narration import Engine as SpeechEngine
from repovox.media.narration import detect
from repovox.media.sandbox import discover_isolated, sources_from
from repovox.media.store import MediaStorage, media_key

logger = logging.getLogger("repovox.media")
TRANSIENT = {"object_unavailable", "dependency_unavailable"}


class Lost(Exception):
    """The lease is gone: stop without committing or reporting anything."""


class MediaWorker:
    def __init__(
        self,
        engine: Engine,
        storage: MediaStorage,
        name: str,
        speech: SpeechEngine | None = None,
    ) -> None:
        self.engine, self.storage, self.name, self.speech = engine, storage, name, speech

    def reconcile(self) -> int:
        with self.engine.begin() as c:
            count = int(c.scalar(text("SELECT mv.reconcile()")) or 0)
            expired = rows(c, "SELECT * FROM mv.expired()")
        for item in expired:
            self.storage.delete_job(item["o_owner"], item["o_job"])
            with self.engine.begin() as c:
                c.execute(text("SELECT mv.mark_deleted(:id)"), {"id": item["o_job"]})
        return count

    def claim(self) -> dict[str, Any] | None:
        with self.engine.begin() as c:
            found = rows(c, "SELECT * FROM mv.claim(:worker)", worker=self.name)
        return found[0] if found else None

    def run_once(self) -> bool:
        lease = self.claim()
        if lease is None:
            return False
        self.execute(lease)
        return True

    def execute(self, lease: dict[str, Any]) -> None:
        stage, fence = lease["o_stage"], lease["o_fence"]
        last = time.monotonic()

        def checkpoint() -> None:
            nonlocal last
            if time.monotonic() - last > 5:
                with self.engine.begin() as c:
                    alive = c.scalar(
                        text("SELECT mv.heartbeat(:id,:fence)"), {"id": stage, "fence": fence}
                    )
                if not alive:
                    raise Lost
                last = time.monotonic()

        uploaded: list[str] = []
        try:
            with self.engine.begin() as c:
                scope = c.scalar(text("SELECT mv.scope(:id,:fence)"), {"id": stage, "fence": fence})
            if scope is None:
                return
            with tempfile.TemporaryDirectory(
                prefix=f"repovox-media-{scope['job_id']}-"
            ) as temporary:
                body, summary = self.stage(scope, Path(temporary), checkpoint, uploaded)
            artifact = uuid4()
            checksum = hashlib.sha256(body).hexdigest()
            key = media_key(
                scope["owner_id"], scope["job_id"], scope["ordinal"], artifact, checksum
            )
            self.storage.write(
                key, body, "video/mp4" if scope["ordinal"] == 14 else "application/octet-stream"
            )
            uploaded.append(key)
            if self.storage.read(scope["owner_id"], key) != body:
                raise DomainError("object_corrupt", 503)
            checkpoint()
            with self.engine.begin() as c:
                committed = c.scalar(
                    text(
                        "SELECT mv.finish(:id,:fence,:artifact,:checksum,:key,:bytes,"
                        "CAST(:summary AS jsonb))"
                    ),
                    {
                        "id": stage,
                        "fence": fence,
                        "artifact": artifact,
                        "checksum": checksum,
                        "key": key,
                        "bytes": len(body),
                        "summary": json.dumps(summary),
                    },
                )
            if not committed:
                self.discard(uploaded)  # Fenced out: nothing uncommitted is left published.
        except Lost:
            self.discard(uploaded)
        except Exception as error:
            self.discard(uploaded)
            code = getattr(error, "code", None)
            transient = not isinstance(code, str) or code in TRANSIENT
            logger.warning(
                json.dumps({"event": "media_stage_failed", "code": code or "media_failure"})
            )
            try:
                with self.engine.begin() as c:
                    c.scalar(
                        text("SELECT mv.fail(:id,:fence,:code,:transient)"),
                        {
                            "id": stage,
                            "fence": fence,
                            "code": code if isinstance(code, str) else "media_failure",
                            "transient": transient,
                        },
                    )
            except Exception:
                logger.warning('{"event":"media_failure_not_recorded"}')  # Reconciler will retry.

    def discard(self, keys: list[str]) -> None:
        for key in keys:
            try:
                self.storage.delete(key)
            except Exception:
                logger.warning('{"event":"media_object_cleanup_deferred"}')

    def payload(self, reference: dict[str, Any]) -> dict[str, Any]:
        envelope = json.loads(self.storage.analysis(reference, "verify"))
        validate_envelope(envelope)
        if (
            envelope["owner_id"] != reference["owner_id"]
            or envelope["snapshot_id"] != reference["snapshot_id"]
            or envelope["commit_sha"] != reference["commit_sha"]
            or envelope["kind"] != "verify"
        ):
            raise DomainError("artifact_corrupt", 503)
        value: dict[str, Any] = envelope["payload"]
        return value

    def stage(
        self,
        scope: dict[str, Any],
        scratch: Path,
        checkpoint: stages.Checkpoint,
        uploaded: list[str],
    ) -> tuple[bytes, dict[str, Any]]:
        ordinal, owner, reference = scope["ordinal"], scope["owner_id"], scope["analysis"]
        outputs = {item["ordinal"]: item for item in scope["outputs"]}

        def prior(number: int) -> bytes:
            item = outputs.get(number)
            if item is None:
                raise DomainError("artifact_corrupt", 503)
            body = self.storage.read(owner, item["key"])
            if len(body) != item["bytes"]:
                raise DomainError("artifact_corrupt", 503)
            return body

        if ordinal == 10:
            return stages.storyboard_stage(self.payload(reference)), {}
        if ordinal == 11:
            return stages.narration_stage(self.payload(reference), prior(10)), {}
        speech = self.speech or detect()
        if ordinal == 12:
            return stages.tts_stage(prior(10), prior(11), speech, scratch, checkpoint), {}
        if ordinal == 13:
            return stages.render_stage(prior(10), prior(11), prior(12), checkpoint), {}
        if ordinal == 14:
            video, media = stages.encode_stage(prior(12), prior(13), scratch, checkpoint)
            return video, {"video": media}
        return self.architecture(scope, scratch, checkpoint, uploaded, speech)

    def architecture(
        self,
        scope: dict[str, Any],
        scratch: Path,
        checkpoint: stages.Checkpoint,
        uploaded: list[str],
        speech: SpeechEngine,
    ) -> tuple[bytes, dict[str, Any]]:
        reference = scope["analysis"]
        payload = self.payload(reference)
        archive = scratch / "source.tar.gz"
        archive.write_bytes(self.storage.analysis(reference, "archive"))
        root = scratch / "source"
        extract(archive, root, checkpoint=checkpoint)
        report = discover_isolated(root, payload, checkpoint)
        # The subprocess result is untrusted: re-check every citation against the source bytes.
        check(report, payload, sources_from(root, payload))
        videos: list[dict[str, Any]] = []
        for architecture in report.architectures[:3]:
            checkpoint()
            work = scratch / f"render-{len(videos)}"
            work.mkdir(mode=0o700)
            item = render_architecture(report, architecture, work, speech, checkpoint)
            body = (work / "video.mp4").read_bytes()
            artifact, checksum = uuid4(), hashlib.sha256(body).hexdigest()
            key = media_key(scope["owner_id"], scope["job_id"], 15, artifact, checksum)
            self.storage.write(key, body, "video/mp4")
            uploaded.append(key)
            videos.append(
                {
                    "artifact": str(artifact),
                    "checksum": checksum,
                    "key": key,
                    "bytes": len(body),
                    "title": architecture.title[:80],
                    "captions": (work / "captions.vtt").read_text(encoding="utf-8"),
                    "metadata": {
                        "id": architecture.id,
                        "type": architecture.type,
                        "status": architecture.status,
                        "components": item["components"],
                        "connections": item["connections"],
                        "narration_lines": item["narration_lines"],
                        "citations": item["citations"],
                        "unresolved": item["unresolved"],
                        "media": item["media"],
                        "architecture_sha256": item["artifacts"]["architecture.json"]["sha256"],
                        "citations_sha256": item["artifacts"]["citations.json"]["sha256"],
                    },
                }
            )
        summary = {"architecture": report.explanation, "videos": videos}
        return stages.encoded(report.model_dump(mode="json")), summary


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    if settings.media_worker_database_url is None:
        raise RuntimeError("Media worker database URL required")
    engine = make_media_engine(settings.media_worker_database_url.get_secret_value(), "rvm_worker")
    worker = MediaWorker(engine, MediaStorage(settings), f"media-{os.getpid()}")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        while not stop.is_set():
            try:
                worker.reconcile()
                while not stop.is_set() and worker.run_once():
                    pass
            except Exception:
                logger.warning('{"event":"media_dependency_unavailable"}')
            stop.wait(2)
    finally:
        engine.dispose()


def make_media_engine(url: str, expected: str) -> Engine:
    """Connect to the media database and refuse anything that is not it."""
    engine = make_engine(url)
    with engine.connect() as c:
        role = c.execute(
            text("SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        if role.rolname != expected or role.rolsuper or role.rolbypassrls:
            raise RuntimeError("Unsafe media database role")
        if c.scalar(text("SELECT to_regclass('public.generation_jobs')")) is not None:
            raise RuntimeError("Media role connected to the core database")
        if c.scalar(text("SELECT version_num FROM alembic_version")) != "m001":
            raise RuntimeError("Media database migration required")
    return engine


if __name__ == "__main__":
    main()


__all__ = ["Lost", "MediaWorker", "make_media_engine"]

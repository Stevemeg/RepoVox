"""Scoped adapter around the unchanged 2.3 analyzer; authenticated direct delivery only."""

import json
import tempfile
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Engine, create_engine, text

from repovox.analysis.archive import extract
from repovox.analysis.common import AnalysisError, digest
from repovox.analysis.contracts import validate_envelope
from repovox.analysis.filtering import filter_sources
from repovox.analysis.runner import AnalysisRunner
from repovox.analysis.transport import GitHubHTTP
from repovox.evaluation.exploratory import restrict_source_scope
from repovox.pilot.contracts import Family, Manifest, decode
from repovox.pilot.control import verify_identity
from repovox.storage import ObjectRef, ObjectStorage, S3Storage
from repovox.workers.runtime import Orchestrator


def scoped(value: dict[str, Any], family: Family, *, apply: bool = False) -> dict[str, Any]:
    if value["repository"] != family.repository or value["commit_sha"] != family.commit:
        raise ValueError("pilot_source_identity")
    inventory = {f["path"]: f for f in value["files"]}
    if len(inventory) != len(value["files"]):
        raise ValueError("pilot_duplicate_inventory")
    for selected in family.files:
        actual = inventory.get(selected.path)
        if (
            actual is None
            or actual["file_sha256"] != selected.sha256
            or actual["bytes"] != selected.size
        ):
            raise ValueError("pilot_original_source_changed")
        if actual["status"] != ("eligible" if selected.role == "source" else "context"):
            raise ValueError("pilot_file_role")
    if apply:
        value = restrict_source_scope(value, frozenset(f.path for f in family.files))
    if {f["path"] for f in value["files"] if f["status"] in {"eligible", "context"}} != {
        f.path for f in family.files
    }:
        raise ValueError("pilot_unapproved_source")
    return value


class ScopedRunner(AnalysisRunner):
    family: Family

    def preparation_filter(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return scoped(manifest, self.family, apply=True)


class GuardedStorage:
    def __init__(
        self,
        engine: Engine,
        delegate: ObjectStorage,
        lease: dict[str, Any],
        manifest: Manifest,
        family: Family,
        filter_ids: set[UUID],
    ) -> None:
        self.engine, self.delegate, self.lease = engine, delegate, lease
        self.manifest, self.family, self.filter_ids = manifest, family, filter_ids

    def check(self) -> None:
        with self.engine.begin() as c:
            body = c.scalar(
                text("SELECT rv.pilot_scope(:id,:fence)"),
                {"id": self.lease["stage_id"], "fence": self.lease["fence"]},
            )
        if body is None or digest(body.encode()) != self.manifest.sha256:
            raise AnalysisError("analysis_timeout")

    def read(self, owner: UUID, ref: ObjectRef) -> bytes:
        self.check()
        body = self.delegate.read(owner, ref)
        if ref.artifact in self.filter_ids:
            scoped(json.loads(body)["payload"], self.family)
        return body

    def write(self, ref: ObjectRef, body: bytes) -> None:
        self.check()
        if self.lease["ordinal"] == 2:
            with tempfile.TemporaryDirectory() as directory:
                archive, source = Path(directory) / "archive", Path(directory) / "source"
                archive.write_bytes(body)
                extract(archive, source)
                scoped(
                    filter_sources(
                        source, self.family.repository, self.family.commit, digest(body)
                    ),
                    self.family,
                    apply=True,
                )
        else:
            envelope = json.loads(body)
            validate_envelope(envelope)
            if self.lease["ordinal"] == 3:
                scoped(envelope["payload"], self.family)
        with self.engine.begin() as c:
            verified = c.scalar(
                text("SELECT rv.pilot_verified(:id,:fence,:sha)"),
                {
                    "id": self.lease["stage_id"],
                    "fence": self.lease["fence"],
                    "sha": self.manifest.sha256,
                },
            )
        if not verified:
            raise AnalysisError("analysis_timeout")
        self.delegate.write(ref, body)
        self.check()  # Upload races may leave an orphan, never an accepted publication.

    def delete(self, owner: UUID, ref: ObjectRef) -> None:
        self.delegate.delete(owner, ref)


class Executor:
    """No broker task registration. Credentials authorize only this pilot route."""

    def __init__(
        self, engine: Engine, owner: UUID, storage: ObjectStorage, http: GitHubHTTP | None = None
    ) -> None:
        # Each executor owns a tenant-bound pool. Do not mutate a shared SaaS engine.
        self.engine = create_engine(
            engine.url,
            connect_args={
                "connect_timeout": 5,
                "options": f"-c repovox.owner_id={owner} -c statement_timeout=5000 "
                "-c idle_in_transaction_session_timeout=10000",
            },
        )
        self.owner, self.storage, self.http = owner, storage, http
        try:
            verify_identity(self.engine, "executor")
        except Exception:
            self.engine.dispose()
            raise

    def claim(
        self, stage: UUID, attempt: UUID, generation: int, manifest_sha: str, family: str
    ) -> dict[str, Any] | None:
        with self.engine.begin() as c:
            row = (
                c.execute(
                    text("SELECT * FROM rv.pilot_claim(:sid,:aid,:gen,:sha,:family)"),
                    {
                        "sid": stage,
                        "aid": attempt,
                        "gen": generation,
                        "sha": manifest_sha,
                        "family": family,
                    },
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def run(
        self, stage: UUID, attempt: UUID, generation: int, manifest_sha: str, family_id: str
    ) -> bool:
        lease = self.claim(stage, attempt, generation, manifest_sha, family_id)
        if lease is None:
            return False
        try:
            with self.engine.begin() as c:
                body = c.scalar(
                    text("SELECT rv.pilot_scope(:id,:fence)"),
                    {"id": stage, "fence": lease["fence"]},
                )
                inputs = c.scalar(
                    text("SELECT rv.analysis_scope_v23(:id,:fence)"),
                    {"id": stage, "fence": lease["fence"]},
                )
            if body is None or inputs is None:
                raise ValueError("pilot_lease_lost")
            manifest = decode(body.encode(), manifest_sha)
            manifest.verify_engine()
            if manifest.owner != self.owner:
                raise ValueError("pilot_owner")
            family = next(f for f in manifest.families if f.id == family_id)
            if (inputs["snapshot"]["repository"], inputs["snapshot"]["commit_sha"]) != (
                family.repository,
                family.commit,
            ):
                raise ValueError("pilot_scope_binding")
            filter_ids = {UUID(i["id"]) for i in inputs["outputs"] if i["ordinal"] == 3}
            if lease["ordinal"] > 3 and not filter_ids:
                raise ValueError("pilot_scope_missing")
            guarded = GuardedStorage(self.engine, self.storage, lease, manifest, family, filter_ids)
            # The frozen engine annotates its read/write/delete dependency as S3Storage.
            # Keep that engine unchanged; this adapter implements its complete used protocol.
            storage = cast(S3Storage, guarded)
            runner = ScopedRunner(self.engine, storage, self.http)
            runner.family = family
            orchestrator = Orchestrator(self.engine, storage)
            succeeded = runner.run(lease, lambda: orchestrator.heartbeat(stage, lease["fence"]))
            if not succeeded:
                with self.engine.begin() as c:
                    c.execute(
                        text("SELECT rv.pilot_invalidate(:id,:gen,'pilot_execution_failed')"),
                        {"id": attempt, "gen": generation},
                    )
            return succeeded
        except Exception:
            with self.engine.begin() as c:
                c.execute(
                    text("SELECT rv.pilot_invalidate(:id,:gen,'pilot_scope_or_executor_failure')"),
                    {"id": attempt, "gen": generation},
                )
            return False

    def deliveries(self, attempt: UUID, generation: int) -> list[dict[str, Any]]:
        with self.engine.begin() as c:
            return [
                dict(r)
                for r in c.execute(
                    text("SELECT * FROM rv.pilot_delivery(:id,:gen)"),
                    {"id": attempt, "gen": generation},
                ).mappings()
            ]

    def deliver(
        self,
        event: UUID,
        stage: UUID,
        attempt: UUID,
        generation: int,
        manifest_sha: str,
        family: str,
    ) -> bool:
        if not any(
            r["event_id"] == event and r["stage_id"] == stage
            for r in self.deliveries(attempt, generation)
        ):
            return False
        with self.engine.begin() as c:
            if not c.scalar(
                text("SELECT rv.pilot_published(:event,:id,:gen)"),
                {"event": event, "id": attempt, "gen": generation},
            ):
                return False
        return self.run(stage, attempt, generation, manifest_sha, family)

    def dispose(self) -> None:
        self.engine.dispose()

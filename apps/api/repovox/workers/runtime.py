import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from repovox.db.database import rows
from repovox.storage import ObjectRef, S3Storage


class Orchestrator:
    """Worker has EXECUTE privileges only; PostgreSQL checks every claim and publication."""

    def __init__(self, engine: Engine, storage: S3Storage) -> None:
        self.engine, self.storage = engine, storage

    def claim(self, stage: UUID, worker: str) -> dict[str, Any] | None:
        with self.engine.begin() as connection:
            found = rows(connection, "SELECT * FROM rv.claim(:id,:worker)", id=stage, worker=worker)
            return found[0] if found else None

    def heartbeat(self, stage: UUID, fence: int) -> bool:
        with self.engine.begin() as connection:
            return bool(
                connection.scalar(
                    text("SELECT rv.heartbeat(:id,:fence)"), {"id": stage, "fence": fence}
                )
            )

    def fail(self, stage: UUID, fence: int, transient: bool = False) -> bool:
        with self.engine.begin() as connection:
            return bool(
                connection.scalar(
                    text("SELECT rv.fail(:id,:fence,:transient)"),
                    {"id": stage, "fence": fence, "transient": transient},
                )
            )

    def finish(self, lease: dict[str, Any], ref: ObjectRef) -> bool:
        with self.engine.begin() as connection:
            return bool(
                connection.scalar(
                    text("SELECT rv.finish(:stage,:fence,:artifact,:checksum,:key)"),
                    {
                        "stage": lease["stage_id"],
                        "fence": lease["fence"],
                        "artifact": ref.artifact,
                        "checksum": ref.checksum,
                        "key": ref.key,
                    },
                )
            )

    def run(self, stage: UUID, worker: str) -> bool:
        lease = self.claim(stage, worker)
        if lease is None:
            return False
        if lease["ordinal"] != 2 or lease["fixture"] == "permanent_failure":
            return self.fail(stage, lease["fence"])
        if lease["fixture"] == "transient_once" and lease["attempt_no"] == 1:
            return self.fail(stage, lease["fence"], transient=True)
        body = json.dumps(
            {
                "synthetic": True,
                "fixture_version": "trusted-fixture-v1",
                "message": "Harmless delivery fixture; no repository acquired.",
            },
            sort_keys=True,
        ).encode()
        ref = ObjectRef(
            lease["owner_id"],
            lease["snapshot_id"],
            lease["job_id"],
            uuid4(),
            hashlib.sha256(body).hexdigest(),
        )
        try:
            self.storage.write(ref, body)
            if self.storage.read(ref.owner, ref) != body:
                raise ValueError("fixture_checksum")
            committed = self.finish(lease, ref)
            if not committed:
                self.storage.delete(ref.owner, ref)
            return committed
        except Exception:
            # Known harmless local operation: no paid/unknown compute to replay.
            self.fail(stage, lease["fence"], transient=True)
            return False

    def reconcile(self) -> int:
        with self.engine.begin() as connection:
            return int(connection.scalar(text("SELECT rv.reconcile()")) or 0)

    def cleanup(self, deletion: UUID) -> None:
        with self.engine.begin() as connection:
            scope = rows(connection, "SELECT * FROM rv.cleanup_scope(:id)", id=deletion)
        for row in scope:
            if row["job_id"]:
                self.storage.delete_prefix(row["owner_id"], row["snapshot_id"], row["job_id"])
        with self.engine.begin() as connection:
            connection.execute(text("SELECT rv.cleanup_done(:id)"), {"id": deletion})

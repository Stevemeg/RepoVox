"""Trusted offline controller API. No HTTP/admin endpoint or worker lifecycle side effects."""

from collections.abc import Callable
from dataclasses import asdict
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from repovox.analysis.common import canonical
from repovox.analysis.github import Snapshot
from repovox.db.database import tenant
from repovox.pilot.contracts import Manifest


def verify_identity(engine: Engine, capability: str) -> None:
    if capability not in {"controller", "executor"}:
        raise ValueError("pilot_identity_kind")
    with engine.connect() as c:
        role = c.execute(
            text(
                "SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles "
                "WHERE rolname=current_user"
            )
        ).one()
        allowed = c.scalar(
            text("SELECT pg_has_role(session_user,:role,'member')"),
            {"role": "rv_pilot_" + capability},
        )
        internal = c.scalar(text("SELECT pg_has_role(session_user,'rv_executor','member')"))
        if any(role) or not allowed or internal:
            raise ValueError("pilot_" + capability + "_identity")
        if c.scalar(text("SELECT version_num FROM alembic_version")) != "0004":
            raise ValueError("pilot_migration_required")


class Controller:
    def __init__(self, engine: Engine) -> None:
        verify_identity(engine, "controller")
        self.engine = engine

    def register(self, owner: UUID, attempt: UUID, manifest: Manifest) -> None:
        if owner != manifest.owner:
            raise ValueError("pilot_owner")
        with tenant(self.engine, owner) as c:
            c.execute(
                text("SELECT rv.pilot_register(:id,:body,:sha)"),
                {"id": attempt, "body": manifest.body().decode(), "sha": manifest.sha256},
            )

    def admit(
        self,
        owner: UUID,
        attempt: UUID,
        generation: int,
        family: str,
        project: UUID,
        snapshot: Snapshot,
    ) -> UUID | None:
        with tenant(self.engine, owner) as c:
            value = c.scalar(
                text("SELECT rv.pilot_admit(:id,:gen,:family,:project,:body)"),
                {
                    "id": attempt,
                    "gen": generation,
                    "family": family,
                    "project": project,
                    "body": canonical(asdict(snapshot)).decode(),
                },
            )
            return UUID(str(value)) if value else None

    def status(self, owner: UUID, attempt: UUID) -> dict[str, Any]:
        with tenant(self.engine, owner) as c:
            return dict(c.scalar(text("SELECT rv.pilot_status(:id)"), {"id": attempt}))

    def invalidate(
        self, owner: UUID, attempt: UUID, generation: int, reason: str = "controller_stopped"
    ) -> str:
        with tenant(self.engine, owner) as c:
            return str(
                c.scalar(
                    text("SELECT rv.pilot_invalidate(:id,:gen,:reason)"),
                    {"id": attempt, "gen": generation, "reason": reason},
                )
            )

    def close(self, owner: UUID, attempt: UUID, generation: int) -> str:
        with tenant(self.engine, owner) as c:
            return str(
                c.scalar(
                    text("SELECT rv.pilot_close(:id,:gen)"), {"id": attempt, "gen": generation}
                )
            )

    def abort_before_restore(
        self, owner: UUID, attempt: UUID, generation: int, restore: Callable[[], None]
    ) -> None:
        """An uncertain/failed abort never calls restore. A retry here is NOT work replay."""
        self.invalidate(owner, attempt, generation)
        if self.status(owner, attempt)["state"] not in {"INVALIDATED", "EXECUTION_CLOSED"}:
            raise RuntimeError("pilot_abort_unconfirmed")
        restore()

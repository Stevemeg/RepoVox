from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from repovox.core.errors import DomainError
from repovox.db.database import rows, tenant
from repovox.schemas.requests import ProjectInput


class Projects:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self, owner: UUID) -> list[dict[str, Any]]:
        with tenant(self.engine, owner) as connection:
            return rows(
                connection,
                "SELECT id,title,repository_url,status,created_at FROM projects "
                "WHERE owner_id=:owner AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 100",
                owner=owner,
            )

    def get(self, owner: UUID, project: UUID) -> dict[str, Any]:
        with tenant(self.engine, owner) as connection:
            found = rows(
                connection,
                "SELECT id,title,repository_url,status,created_at FROM projects "
                "WHERE owner_id=:owner AND id=:id AND deleted_at IS NULL",
                owner=owner,
                id=project,
            )
        if not found:
            raise DomainError("not_found", 404)
        return found[0]

    def create(self, owner: UUID, body: ProjectInput) -> dict[str, Any]:
        with tenant(self.engine, owner) as connection:
            # Serialize per-account rate and record-count checks, independently of process count.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,0))"),
                {"owner": str(owner)},
            )
            recent = connection.scalar(
                text(
                    "SELECT count(*) FROM projects WHERE owner_id=:owner "
                    "AND created_at>now()-interval '1 minute'"
                ),
                {"owner": owner},
            )
            total = connection.scalar(
                text("SELECT count(*) FROM projects WHERE owner_id=:owner AND deleted_at IS NULL"),
                {"owner": owner},
            )
            if recent is not None and recent >= 30 or total is not None and total >= 100:
                raise DomainError("project_quota", 429)
            return rows(
                connection,
                "INSERT INTO projects(owner_id,repository_url,title) "
                "VALUES(:owner,:url,:title) RETURNING id,title,repository_url,status,created_at",
                owner=owner,
                url=body.repository_url,
                title=body.title,
            )[0]

    def update(self, owner: UUID, project: UUID, title: str) -> dict[str, Any]:
        with tenant(self.engine, owner) as connection:
            found = rows(
                connection,
                "UPDATE projects SET title=:title WHERE owner_id=:owner "
                "AND id=:id AND deleted_at IS NULL "
                "RETURNING id,title,repository_url,status,created_at",
                owner=owner,
                id=project,
                title=title,
            )
        if not found:
            raise DomainError("not_found", 404)
        return found[0]

    def delete(self, owner: UUID, project: UUID) -> UUID:
        with tenant(self.engine, owner) as connection:
            return UUID(
                str(connection.scalar(text("SELECT rv.delete_project(:id)"), {"id": project}))
            )

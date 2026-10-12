import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from repovox.core.errors import DomainError
from repovox.db.database import rows, tenant


class Jobs:
    def __init__(self, engine: Engine, fixtures: bool) -> None:
        self.engine, self.fixtures = engine, fixtures

    def list(self, owner: UUID, project: UUID | None = None) -> list[dict[str, Any]]:
        with tenant(self.engine, owner) as connection:
            return rows(
                connection,
                "SELECT j.id,j.project_id,j.state,j.version,j.synthetic,j.fixture,"
                "j.error_code,j.created_at,"
                "j.finished_at,j.deadline,p.title AS project_title FROM generation_jobs j "
                "JOIN projects p ON p.id=j.project_id AND p.owner_id=j.owner_id "
                "WHERE j.owner_id=:owner AND p.deleted_at IS NULL "
                "AND (:project IS NULL OR j.project_id=CAST(:project AS uuid)) "
                "ORDER BY j.created_at DESC LIMIT 100",
                owner=owner,
                project=project,
            )

    def get(self, owner: UUID, job: UUID) -> dict[str, Any]:
        with tenant(self.engine, owner) as connection:
            found = rows(
                connection,
                "SELECT j.id,j.project_id,j.state,j.version,j.synthetic,j.fixture,"
                "j.error_code,j.created_at,j.finished_at,j.deadline,j.prior_job_id "
                "FROM generation_jobs j JOIN projects p "
                "ON p.id=j.project_id AND p.owner_id=j.owner_id "
                "WHERE j.id=:id AND j.owner_id=:owner AND p.deleted_at IS NULL",
                id=job,
                owner=owner,
            )
            if not found:
                raise DomainError("not_found", 404)
            result = found[0]
            result["stages"] = rows(
                connection,
                "SELECT id,ordinal,stage_key,state,attempt_count,error_code,next_attempt_at "
                "FROM job_stages "
                "WHERE job_id=:id AND owner_id=:owner ORDER BY ordinal",
                id=job,
                owner=owner,
            )
            result["attempts"] = rows(
                connection,
                "SELECT stage_id,attempt_no,started_at,ended_at,outcome,error_code "
                "FROM job_attempts "
                "WHERE job_id=:id AND owner_id=:owner ORDER BY started_at",
                id=job,
                owner=owner,
            )
            result["history"] = rows(
                connection,
                "SELECT version,state,error_code,created_at FROM job_history "
                "WHERE job_id=:id AND owner_id=:owner ORDER BY version",
                id=job,
                owner=owner,
            )
            result["usage"] = rows(
                connection,
                "SELECT event_type,units,measurements,created_at FROM usage_cost_records "
                "WHERE job_id=:id AND owner_id=:owner ORDER BY created_at",
                id=job,
                owner=owner,
            )
            return result

    def admit(
        self, owner: UUID, project: UUID, key: str, fixture: str, prior: UUID | None = None
    ) -> dict[str, Any]:
        if not self.fixtures:
            raise DomainError("fixtures_disabled", 503)
        if not key or len(key) > 128 or not key.isascii() or not key.isprintable():
            raise DomainError("invalid_idempotency_key", 422)
        request = json.dumps(
            {
                "project": str(project),
                "fixture": fixture,
                "prior": str(prior),
                "version": "phase1-fixture-v1",
            },
            sort_keys=True,
        )
        request_digest = hashlib.sha256(request.encode()).hexdigest()
        with tenant(self.engine, owner) as connection:
            job = connection.scalar(
                text("SELECT rv.admit(:project,:key,:digest,:fixture,:prior)"),
                {
                    "project": project,
                    "key": key,
                    "digest": request_digest,
                    "fixture": fixture,
                    "prior": prior,
                },
            )
        return self.get(owner, UUID(str(job)))

    def cancel(self, owner: UUID, job: UUID) -> dict[str, Any]:
        with tenant(self.engine, owner) as connection:
            connection.execute(text("SELECT rv.cancel(:id)"), {"id": job})
        return self.get(owner, job)

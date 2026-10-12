import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from repovox.analysis.common import PIPELINE, AnalysisError, canonical, digest
from repovox.analysis.contracts import validate_envelope
from repovox.analysis.github import HTTP, repository_url, resolve
from repovox.analysis.transport import GitHubHTTP
from repovox.core.config import Settings
from repovox.core.errors import DomainError
from repovox.db.database import rows, tenant
from repovox.storage import ObjectRef, S3Storage


class Jobs:
    def __init__(
        self, engine: Engine, fixtures: bool, analysis: bool = False, http: HTTP | None = None
    ) -> None:
        self.engine, self.fixtures, self.analysis = engine, fixtures, analysis
        self.http = http or GitHubHTTP()

    def admit_analysis(
        self,
        owner: UUID,
        project: UUID,
        key: str,
        prior: UUID | None = None,
    ) -> dict[str, Any]:
        if not self.analysis:
            raise DomainError("analysis_disabled", 503)
        if not key or len(key) > 128 or not key.isascii() or not key.isprintable():
            raise DomainError("invalid_idempotency_key", 422)
        request_digest = digest(
            canonical({"project": str(project), "prior": str(prior), "version": PIPELINE})
        )
        with tenant(self.engine, owner) as c:
            projects = rows(
                c,
                "SELECT repository_url FROM projects WHERE owner_id=:owner AND id=:id AND "
                "deleted_at IS NULL",
                owner=owner,
                id=project,
            )
            if not projects:
                raise DomainError("not_found", 404)
            existing = rows(
                c,
                "SELECT id,request_digest FROM generation_jobs WHERE owner_id=:owner AND "
                "idempotency_key=:key",
                owner=owner,
                key=key,
            )
            if existing:
                if existing[0]["request_digest"] != request_digest:
                    raise DomainError("idempotency_conflict", 409)
                found = UUID(str(existing[0]["id"]))
            else:
                found = None
            if prior:
                previous = rows(
                    c,
                    "SELECT s.metadata FROM repository_snapshots s JOIN generation_jobs j ON "
                    "j.snapshot_id=s.id AND j.owner_id=s.owner_id WHERE j.id=:id AND "
                    "j.owner_id=:owner AND j.project_id=:project AND NOT j.synthetic AND j.state "
                    "IN ('failed','cancelled')",
                    id=prior,
                    owner=owner,
                    project=project,
                )
                if not previous:
                    raise DomainError("invalid_retry", 409)
                snapshot = previous[0]["metadata"]
        if found:
            return self.get(owner, found)
        if not prior:
            try:
                snapshot = resolve(repository_url(projects[0]["repository_url"]), self.http).data()
            except AnalysisError as exc:
                raise DomainError(
                    exc.code,
                    429 if exc.code == "github_rate_limited" else 422 if not exc.transient else 503,
                ) from None
        with tenant(self.engine, owner) as c:
            # Same admission lock/order as rv.admit: metadata reuse cannot race new snapshots.
            c.execute(text("SELECT pg_advisory_xact_lock(712031)"))
            reusable = rows(
                c,
                "SELECT metadata FROM repository_snapshots WHERE owner_id=:owner AND "
                "project_id=:project AND commit_sha=:sha AND "
                "acquisition_version='github-archive-v1'",
                owner=owner,
                project=project,
                sha=snapshot["commit_sha"],
            )
            if reusable:
                snapshot = reusable[0]["metadata"]
            job = c.scalar(
                text(
                    "SELECT rv.admit_analysis(:project,:key,:digest,:sha,CAST(:metadata AS "
                    "jsonb),:validation,:prior)"
                ),
                {
                    "project": project,
                    "key": key,
                    "digest": request_digest,
                    "sha": snapshot["commit_sha"],
                    "metadata": canonical(snapshot).decode(),
                    "validation": digest(canonical(snapshot)),
                    "prior": prior,
                },
            )
        return self.get(owner, UUID(str(job)))

    def analysis_result(self, owner: UUID, job: UUID, settings: Settings) -> dict[str, Any]:
        if not self.analysis:
            raise DomainError("analysis_disabled", 503)
        self.get(owner, job)
        with tenant(self.engine, owner) as c:
            found = rows(
                c,
                "SELECT a.id,a.snapshot_id,a.object_key,a.checksum FROM analysis_results r "
                "JOIN knowledge_artifacts a ON a.id=r.artifact_id AND a.owner_id=r.owner_id "
                "WHERE r.owner_id=:owner AND r.job_id=:job AND a.expires_at>clock_timestamp()",
                owner=owner,
                job=job,
            )
        if not found:
            raise DomainError("analysis_result_unavailable", 404)
        row = found[0]
        ref = ObjectRef(owner, row["snapshot_id"], job, row["id"], row["checksum"], "analysis")
        if ref.key != row["object_key"]:
            raise DomainError("object_corrupt", 503)
        value: dict[str, Any] = json.loads(S3Storage(settings).read(owner, ref))
        validate_envelope(value)
        if (
            value["owner_id"] != str(owner)
            or value["snapshot_id"] != str(ref.snapshot)
            or value["kind"] != "verify"
        ):
            raise DomainError("object_corrupt", 503)
        return value

    def list(self, owner: UUID, project: UUID | None = None) -> list[dict[str, Any]]:
        with tenant(self.engine, owner) as connection:
            return rows(
                connection,
                "SELECT j.id,j.project_id,j.state,j.version,j.synthetic,j.fixture,"
                "j.error_code,j.created_at,"
                "j.finished_at,j.deadline,j.pipeline_version,s.commit_sha,p.repository_url,"
                "p.title AS project_title FROM generation_jobs j "
                "JOIN projects p ON p.id=j.project_id AND p.owner_id=j.owner_id "
                "JOIN repository_snapshots s ON s.id=j.snapshot_id AND s.owner_id=j.owner_id "
                "WHERE j.owner_id=:owner AND p.deleted_at IS NULL "
                "AND (CAST(:project AS uuid) IS NULL OR j.project_id=CAST(:project AS uuid)) "
                "ORDER BY j.created_at DESC LIMIT 100",
                owner=owner,
                project=project,
            )

    def get(self, owner: UUID, job: UUID) -> dict[str, Any]:
        with tenant(self.engine, owner) as connection:
            found = rows(
                connection,
                "SELECT j.id,j.project_id,j.state,j.version,j.synthetic,j.fixture,"
                "j.error_code,j.created_at,j.finished_at,j.deadline,j.prior_job_id,"
                "j.pipeline_version,s.commit_sha,p.repository_url "
                "FROM generation_jobs j JOIN projects p "
                "ON p.id=j.project_id AND p.owner_id=j.owner_id "
                "JOIN repository_snapshots s ON s.id=j.snapshot_id AND s.owner_id=j.owner_id "
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

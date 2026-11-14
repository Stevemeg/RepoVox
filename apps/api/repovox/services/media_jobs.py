"""Video jobs in the separate media database, bridged to core analysis without shared transactions.

The API holds two independent database handles. Each step is idempotent and safe to repeat:

1. admit the core analysis job (existing, idempotent on its key);
2. admit the media job, recording only the analysis job id;
3. when the owner next reads the job and the analysis has finished, attach an immutable
   reference to its verified outputs. Until then the media job waits; if analysis fails or
   never arrives the media job ends with an explicit code.

Nothing here assumes the two databases commit together.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from repovox.analysis.common import canonical, digest
from repovox.core.config import Settings
from repovox.core.errors import DomainError
from repovox.db.database import rows, tenant
from repovox.media.store import MediaStorage
from repovox.services.jobs import Jobs
from repovox.storage import ObjectRef

TERMINAL = {"succeeded", "failed", "cancelled"}


class MediaJobs:
    def __init__(self, engine: Engine, core: Engine, jobs: Jobs, settings: Settings) -> None:
        self.engine, self.core, self.jobs, self.settings = engine, core, jobs, settings
        self._storage: MediaStorage | None = None

    @property
    def storage(self) -> MediaStorage:
        if self._storage is None:
            self._storage = MediaStorage(self.settings)
        return self._storage

    def admit(self, owner: UUID, project: UUID, key: str) -> dict[str, Any]:
        if not key or len(key) > 120 or not key.isascii() or not key.isprintable() or " " in key:
            raise DomainError("invalid_idempotency_key", 422)
        analysis = self.jobs.admit_analysis(owner, project, f"video:{key}")
        request = digest(canonical({"project": str(project), "analysis": str(analysis["id"])}))
        with tenant(self.engine, owner) as c:
            job = c.scalar(
                text("SELECT mv.admit(:project,:analysis,:key,:digest)"),
                {"project": project, "analysis": analysis["id"], "key": key, "digest": request},
            )
        return self.get(owner, UUID(str(job)))

    def reference(self, owner: UUID, analysis: UUID) -> dict[str, Any] | None:
        """Identity of the verified analysis outputs, or None while analysis is not finished.

        Read through the owner's own tenant scope in the core database. Raises analysis_failed
        if the analysis job ended any other way than the verified Stage 9 boundary.
        """
        with tenant(self.core, owner) as c:
            job = rows(
                c,
                "SELECT j.state,j.error_code,j.snapshot_id,s.commit_sha,s.metadata FROM "
                "generation_jobs j JOIN repository_snapshots s ON s.id=j.snapshot_id AND "
                "s.owner_id=j.owner_id WHERE j.id=:id AND j.owner_id=:owner AND NOT j.synthetic",
                id=analysis,
                owner=owner,
            )
            if not job:
                raise DomainError("analysis_failed", 409)
            state = job[0]
            if state["state"] not in {"failed", "cancelled", "succeeded"}:
                return None
            if state["state"] != "failed" or state["error_code"] != "phase2_pipeline_boundary":
                raise DomainError("analysis_failed", 409)
            artifacts = rows(
                c,
                "SELECT t.ordinal,a.id,a.checksum,a.object_key,a.byte_count FROM "
                "knowledge_artifacts a JOIN job_stages t ON t.id=a.stage_id AND "
                "t.owner_id=a.owner_id JOIN analysis_results r ON r.job_id=a.job_id AND "
                "r.owner_id=a.owner_id WHERE a.job_id=:id AND a.owner_id=:owner AND "
                "t.ordinal IN (2,9) AND a.expires_at>clock_timestamp() ORDER BY t.ordinal",
                id=analysis,
                owner=owner,
            )
        if [a["ordinal"] for a in artifacts] != [2, 9]:
            raise DomainError("analysis_failed", 409)
        found: dict[str, Any] = {
            "owner_id": str(owner),
            "analysis_job_id": str(analysis),
            "snapshot_id": str(state["snapshot_id"]),
            "commit_sha": state["commit_sha"],
            "repository": str(state["metadata"]["repository"]),
        }
        for name, item in zip(("archive", "verify"), artifacts, strict=True):
            ref = ObjectRef(
                owner, state["snapshot_id"], analysis, item["id"], item["checksum"], "analysis"
            )
            if ref.key != item["object_key"]:
                raise DomainError("analysis_failed", 409)
            found[name] = {
                "artifact": str(item["id"]),
                "checksum": item["checksum"],
                "bytes": int(item["byte_count"]),
            }
        return found

    def sync(self, owner: UUID, job: dict[str, Any]) -> bool:
        """Advance a waiting job if its analysis has settled. Safe to call any number of times."""
        if job["state"] != "awaiting_analysis":
            return False
        try:
            reference = self.reference(owner, job["analysis_job_id"])
        except DomainError as error:
            if error.code != "analysis_failed":
                raise
            with tenant(self.engine, owner) as c:
                c.execute(text("SELECT mv.analysis_failed(:id)"), {"id": job["id"]})
            return True
        if reference is None:
            return False
        with tenant(self.engine, owner) as c:
            c.execute(
                text("SELECT mv.attach(:id,CAST(:reference AS jsonb))"),
                {"id": job["id"], "reference": canonical(reference).decode()},
            )
        return True

    def _load(self, owner: UUID, job: UUID | None, project: UUID | None) -> list[dict[str, Any]]:
        with tenant(self.engine, owner) as c:
            found = rows(
                c,
                "SELECT id,project_id,analysis_job_id,state,version,repository,commit_sha,"
                "architecture,error_code,created_at,deadline,finished_at FROM media_jobs WHERE "
                "owner_id=:owner AND (CAST(:id AS uuid) IS NULL OR id=CAST(:id AS uuid)) AND "
                "(CAST(:project AS uuid) IS NULL OR project_id=CAST(:project AS uuid)) "
                "ORDER BY created_at DESC LIMIT 50",
                owner=owner,
                id=job,
                project=project,
            )
            for item in found:
                item["stages"] = rows(
                    c,
                    "SELECT ordinal,stage_key,state,attempt_count,error_code FROM media_stages "
                    "WHERE job_id=:id AND owner_id=:owner ORDER BY ordinal",
                    id=item["id"],
                    owner=owner,
                )
                item["videos"] = (
                    rows(
                        c,
                        "SELECT id,category,position,title,checksum,byte_count,metadata,"
                        "published_at,expires_at FROM media_videos WHERE job_id=:id AND "
                        "owner_id=:owner AND deleted_at IS NULL AND "
                        "expires_at>clock_timestamp() ORDER BY category DESC,position",
                        id=item["id"],
                        owner=owner,
                    )
                    if item["state"] == "succeeded"
                    else []  # Nothing is offered before the job has succeeded.
                )
        return found

    def list(self, owner: UUID, project: UUID | None = None) -> list[dict[str, Any]]:
        found = self._load(owner, None, project)
        if any(self.sync(owner, job) for job in found):
            found = self._load(owner, None, project)
        return found

    def get(self, owner: UUID, job: UUID) -> dict[str, Any]:
        found = self._load(owner, job, None)
        if not found:
            raise DomainError("not_found", 404)
        if self.sync(owner, found[0]):
            found = self._load(owner, job, None)
        return found[0]

    def cancel(self, owner: UUID, job: UUID) -> dict[str, Any]:
        with tenant(self.engine, owner) as c:
            c.execute(text("SELECT mv.cancel(:id)"), {"id": job})
        return self.get(owner, job)

    def video(self, owner: UUID, job: UUID, video: UUID) -> tuple[bytes, dict[str, Any]]:
        """Bytes of one published video. Only committed, validated, unexpired, owned videos."""
        with tenant(self.engine, owner) as c:
            found = rows(
                c,
                "SELECT v.id,v.category,v.title,v.object_key,v.checksum,v.byte_count,v.captions "
                "FROM media_videos v JOIN media_jobs j ON j.id=v.job_id AND j.owner_id=v.owner_id "
                "WHERE v.id=:video AND v.job_id=:job AND v.owner_id=:owner AND "
                "j.state='succeeded' AND v.deleted_at IS NULL AND v.expires_at>clock_timestamp()",
                video=video,
                job=job,
                owner=owner,
            )
        if not found:
            raise DomainError("not_found", 404)
        row = found[0]
        body = self.storage.read(owner, row["object_key"])
        if len(body) != row["byte_count"] or not row["object_key"].endswith(row["checksum"]):
            raise DomainError("object_corrupt", 503)
        return body, row

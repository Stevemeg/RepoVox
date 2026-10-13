"""Opt-in pilot using accepted durable jobs/RLS/S3/fenced analysis; never official gold."""

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from repovox.analysis.archive import extract
from repovox.analysis.common import canonical
from repovox.analysis.filtering import filter_sources
from repovox.analysis.runner import AnalysisRunner
from repovox.analysis.transport import GitHubHTTP
from repovox.core.config import Settings
from repovox.db.database import make_engine, tenant, verify_role
from repovox.evaluation.corpus import checksum, serialize
from repovox.evaluation.exploratory import (
    Policy,
    PredictionPacket,
    blind_packet,
    checked_bytes,
    restrict_source_scope,
    seal_packet,
    validate_pinned_tree,
    write_immutable,
)
from repovox.evaluation.preparation import language_slice, verify_boundary
from repovox.schemas.requests import ProjectInput
from repovox.services.jobs import Jobs
from repovox.services.projects import Projects
from repovox.storage import ObjectRef, S3Storage
from repovox.workers.runtime import Orchestrator
from sqlalchemy import text

parser = argparse.ArgumentParser()
parser.add_argument("repository")
parser.add_argument("--store", type=Path, required=True)
parser.add_argument("--token-stdin", action="store_true")
parser.add_argument("--job", type=UUID, help="Export an already completed durable exploratory job")
args = parser.parse_args()
if args.repository not in {"pallets/click", "sindresorhus/p-limit", "jupyterlite/echo-kernel"}:
    raise ValueError("repository_not_owner_approved_for_pilot")
verify_boundary(args.store.parents[1], Path("/workspace"), 10001)
directory = args.store / args.repository.replace("/", "-")
rights = json.loads((directory / "rights-decision.json").read_bytes())
if (
    rights["repository"] != args.repository
    or rights["decision"] != "PERMITTED_INTERNAL_EXPLORATORY"
):
    raise ValueError("recorded_exploratory_rights_required")
preflight = json.loads((directory / "preflight/report.json").read_bytes())
if preflight["rejections"]:
    raise ValueError("preflight_rejection_no_archive_allowed")
sha = rights["commit_sha"]
token = json.load(sys.stdin).get("github_token") if args.token_stdin else None


class PinnedHTTP(GitHubHTTP):
    def get(self, host: str, path: str, limit: int, seconds: float = 10) -> bytes:
        # The actual API resolves an immutable ref instead of current HEAD.
        if host == "api.github.com" and path.startswith(f"/repos/{args.repository}/commits/"):
            path = f"/repos/{args.repository}/commits/{sha}"
        return super().get(host, path, limit, seconds)


http = PinnedHTTP(token)
settings = Settings()
if settings.environment not in {"development", "test"} or settings.worker_database_url is None:
    raise ValueError("exploratory_local_runtime_required")
app = make_engine(settings.database_url.get_secret_value())
worker = make_engine(settings.worker_database_url.get_secret_value())
verify_role(app, "rv_app")
verify_role(worker, "rv_worker")
storage = S3Storage(settings)
owner = UUID("11111111-1111-4111-8111-111111111111")  # Labelled demo tenant, not a reviewer.
other = UUID("22222222-2222-4222-8222-222222222222")
projects, jobs = Projects(app), Jobs(app, False, True, http)
started = time.monotonic()
if args.job is None:
    project = projects.create(
        owner,
        ProjectInput(
            title=f"AI_AUDITED_EXPLORATORY {args.repository}",
            repository_url=f"https://github.com/{args.repository}",
        ),
    )
    job = jobs.admit_analysis(owner, project["id"], f"exploratory-{sha}-{project['id']}")
else:
    job = jobs.get(owner, args.job)
if job["commit_sha"] != sha:
    raise ValueError("exploratory_pin_changed")


class ExploratoryRunner(AnalysisRunner):
    def preparation_filter(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return restrict_source_scope(manifest, frozenset(preflight["scope"]))


orchestrator = Orchestrator(worker, storage, ExploratoryRunner(worker, storage, http))
stage_times = {}
for stage in job["stages"][1:9] if args.job is None else []:
    before = time.monotonic()
    if not orchestrator.run(UUID(str(stage["id"])), "exploratory-manual-fenced-runner"):
        state = jobs.get(owner, UUID(str(job["id"])))
        write_immutable(
            directory,
            f"analysis-failure-{job['id']}.json",
            canonical(
                {
                    "policy": Policy().model_dump(),
                    "repository": args.repository,
                    "commit_sha": sha,
                    "error_code": state["error_code"],
                    "stage": stage["ordinal"],
                }
            ),
        )
        print(
            json.dumps(
                {
                    "repository": args.repository,
                    "status": "SOURCE_BLOCKED",
                    "error_code": state["error_code"],
                    "stage": stage["ordinal"],
                }
            )
        )
        raise SystemExit(2)
    stage_times[str(stage["ordinal"])] = time.monotonic() - before
state = jobs.get(owner, UUID(str(job["id"])))
if state["error_code"] != "phase2_pipeline_boundary" or not all(
    s["state"] == "succeeded" for s in state["stages"][:9]
):
    raise ValueError("accepted_phase2_boundary_required")
with tenant(app, other) as c:
    if (
        c.scalar(text("SELECT count(*) FROM analysis_results WHERE job_id=:id"), {"id": job["id"]})
        != 0
    ):
        raise ValueError("exploratory_rls_leak")
with tenant(app, owner) as c:
    artifacts = (
        c.execute(
            text(
                "SELECT a.id,a.snapshot_id,a.object_key,a.checksum,s.ordinal "
                "FROM knowledge_artifacts a JOIN job_stages s ON s.id=a.stage_id "
                "AND s.owner_id=a.owner_id WHERE a.job_id=:id AND a.owner_id=:owner "
                "ORDER BY s.ordinal"
            ),
            {"id": job["id"], "owner": owner},
        )
        .mappings()
        .all()
    )
records = []
archive: Path | None = None
payload: dict[str, Any] | None = None
for item in artifacts:
    ref = ObjectRef(
        owner, item["snapshot_id"], UUID(str(job["id"])), item["id"], item["checksum"], "analysis"
    )
    body = storage.read(owner, ref)
    if ref.key != item["object_key"]:
        raise ValueError("persisted_artifact_changed")
    name = f"original-artifacts/stage-{item['ordinal']}." + (
        "tar.gz" if item["ordinal"] == 2 else "json"
    )
    digest = checksum(body)
    if (directory / name).exists():
        checked_bytes(directory, name, digest)
    else:
        write_immutable(directory, name, body)
    records.append({"path": name, "sha256": digest, "bytes": len(body), "stage": item["ordinal"]})
    if item["ordinal"] == 2:
        archive = directory / name
    if item["ordinal"] == 9:
        payload = json.loads(body)["payload"]
if archive is None or payload is None:
    raise ValueError("persisted_prediction_artifacts_incomplete")
source = directory / "source"
if not source.exists():
    extract(archive, source)
validate_pinned_tree(source, json.loads((directory / "preflight/tree.json").read_bytes()))
for path in [source, *source.rglob("*")]:
    os.chmod(path, 0o700 if path.is_dir() else 0o600)
manifest = filter_sources(source, args.repository, sha, checksum(archive.read_bytes()))
if (directory / "source-manifest.json").exists():
    previous = json.loads((directory / "source-manifest.json").read_bytes())
    if {k: v for k, v in previous.items() if k != "processing_timestamp"} != {
        k: v for k, v in manifest.items() if k != "processing_timestamp"
    }:
        raise ValueError("retained_source_manifest_changed")
    manifest = previous
else:
    write_immutable(directory, "source-manifest.json", serialize(manifest))
selected = {path: (1, None) for path in preflight["scope"]}
packet_a = blind_packet(source, args.repository, sha, manifest, rights, selected)
metrics = {
    "durable_job_seconds": (state["finished_at"] - state["created_at"]).total_seconds(),
    "preparation_command_seconds": time.monotonic() - started,
    "durable_usage": [
        {"event_type": u["event_type"], "units": str(u["units"]), "measurements": u["measurements"]}
        for u in state["usage"]
    ],
    "stage_seconds": stage_times,
    "language_slice": language_slice(manifest),
    "coverage": payload["knowledge"]["coverage"],
    "symbols": len(payload["knowledge"]["symbols"]),
    "edges": len(payload["knowledge"]["edges"]),
    "entrypoint_candidates": len(payload["knowledge"]["entrypoints"]["candidates"]),
    "claim_counts": payload["verification"]["counts"],
    "citation_denominator": len(payload["evidence"]["items"]),
    "citation_resolved": sum(
        e["validation_status"] == "valid" for e in payload["evidence"]["items"]
    ),
    "child_peak_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    if args.job is None
    else None,
    "parser_cpu_seconds": (
        resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime
        + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
    )
    if args.job is None
    else None,
    "reference_comparison": "NOT_RUN_AWAITING_BLIND_REVIEW",
    "tenant_isolation": "OTHER_OWNER_ZERO_ROWS",
    "job_id": str(job["id"]),
    "job_state": state["error_code"],
}
packet_b = PredictionPacket(
    schema_version="exploratory-sealed-prediction-1.0",
    policy=Policy(),
    repository=args.repository,
    commit_sha=sha,
    rights_evidence_sha256=checksum(serialize(rights)),
    selected_scope=[
        {"path": e.path, "start_line": e.start_line, "end_line": e.end_line}
        for e in packet_a.excerpts
    ],
    original_artifacts=records,
    verified_payload=payload,
    metrics=metrics,
)
seal_b = seal_packet(directory, "B", packet_b.model_dump())
seal_a = seal_packet(directory, "A", packet_a.model_dump())
write_immutable(
    directory,
    "handoff-seals.json",
    serialize(
        {
            "policy": Policy().model_dump(),
            "A": seal_a,
            "B": seal_b,
            "reference_status": "PENDING_OWNER_HANDOFF_TO_CHATGPT",
            "official_manifest_changed": False,
        }
    ),
)
print(
    json.dumps(
        {
            "repository": args.repository,
            "status": "BLIND_PACKET_READY",
            "A_sha256": seal_a["sha256"],
            "B_sha256": seal_b["sha256"],
            "predictions_exposed": False,
            "independent_comparison": "NOT_RUN",
        }
    )
)

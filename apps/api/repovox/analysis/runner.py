import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from repovox.analysis.archive import extract
from repovox.analysis.common import PIPELINE, AnalysisError, Limits, canonical, digest
from repovox.analysis.contracts import validate_envelope
from repovox.analysis.filtering import filter_sources
from repovox.analysis.github import Snapshot, archive_path
from repovox.analysis.transport import GitHubHTTP
from repovox.core.errors import DomainError
from repovox.storage import ObjectRef, S3Storage

STAGES = {
    3: "filter",
    4: "structure",
    5: "entrypoints",
    6: "infer",
    7: "knowledge",
    8: "evidence",
    9: "verify",
}


def isolated(
    root: Path, request: dict[str, Any], checkpoint: Callable[[], None], timeout: float
) -> dict[str, Any]:
    request_path = root.parent / "request.json"
    request_path.write_bytes(canonical(request))
    env = {
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "LANG": "C.UTF-8",
    }
    with tempfile.TemporaryFile(dir=root.parent) as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "repovox.analysis.sandbox", str(root), str(request_path)],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
        )
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                checkpoint()
                if time.monotonic() >= deadline:
                    raise AnalysisError("analysis_timeout")
                time.sleep(0.05)
            output.seek(0)
            body = output.read(64 * 1024**2 + 1)
            if len(body) > 64 * 1024**2:
                raise AnalysisError("analysis_fact_limit")
            value = json.loads(body)
            if process.returncode != 0 or "error" in value:
                code = value.get("error", "parser_isolation_unavailable")
                if not isinstance(code, str) or not code.replace("_", "").isalpha():
                    code = "analysis_failure"
                raise AnalysisError(code)
            if not isinstance(value, dict):
                raise AnalysisError("analysis_failure")
            return value
        except (ValueError, OSError):
            raise AnalysisError("parser_isolation_unavailable") from None
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


class AnalysisRunner:
    def __init__(self, engine: Engine, storage: S3Storage, http: GitHubHTTP | None = None) -> None:
        self.engine, self.storage, self.http = engine, storage, http or GitHubHTTP()

    def preparation_filter(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Default full scope; explicit exploratory runner narrows AFTER security scans."""
        return manifest

    def run(self, lease: dict[str, Any], heartbeat: Callable[[], bool]) -> bool:
        ordinal = lease["ordinal"]
        started = time.monotonic()
        last = 0.0

        def checkpoint() -> None:
            nonlocal last
            if time.monotonic() - last > 5:
                if not heartbeat():
                    raise AnalysisError("analysis_timeout")
                last = time.monotonic()

        try:
            if sys.platform != "linux":
                raise AnalysisError("parser_isolation_unavailable")
            checkpoint()
            with self.engine.begin() as c:
                scope = c.scalar(
                    text("SELECT rv.analysis_scope(:id,:fence)"),
                    {"id": lease["stage_id"], "fence": lease["fence"]},
                )
            if scope is None:
                return False
            snapshot = scope["snapshot"]
            if digest(canonical(snapshot)) != scope["validate_digest"]:
                raise AnalysisError("artifact_corrupt")
            inputs: dict[str, Any] = {}
            hashes = [scope["validate_digest"]]
            archive_body: bytes | None = None
            for output in scope["outputs"]:
                ref = ObjectRef(
                    lease["owner_id"],
                    lease["snapshot_id"],
                    lease["job_id"],
                    UUID(output["id"]),
                    output["checksum"],
                    "analysis",
                )
                if ref.key != output["key"]:
                    raise AnalysisError("artifact_corrupt")
                checkpoint()
                body = self.storage.read(ref.owner, ref)
                if len(body) != output["bytes"]:
                    raise AnalysisError("artifact_corrupt")
                prior_input = digest(
                    (snapshot["commit_sha"] + "|" + PIPELINE + "|" + "|".join(hashes)).encode()
                )
                if output["input_digest"] != prior_input:
                    raise AnalysisError("artifact_corrupt")
                hashes.append(output["checksum"])
                if output["ordinal"] == 2:
                    archive_body = body
                else:
                    envelope = json.loads(body)
                    validate_envelope(envelope)
                    if (
                        envelope["owner_id"] != str(ref.owner)
                        or envelope["snapshot_id"] != str(ref.snapshot)
                        or envelope["commit_sha"] != snapshot["commit_sha"]
                        or envelope["input_digest"] != prior_input
                        or envelope["kind"] != STAGES[output["ordinal"]]
                    ):
                        raise AnalysisError("artifact_corrupt")
                    inputs[str(output["ordinal"])] = envelope["payload"]
            input_hash = digest(
                (snapshot["commit_sha"] + "|" + PIPELINE + "|" + "|".join(hashes)).encode()
            )
            summary: dict[str, Any] = {}
            with tempfile.TemporaryDirectory(prefix=f"repovox-{lease['job_id']}-") as temporary:
                archive = Path(temporary) / "source.tar.gz"
                root = Path(temporary) / "source"
                if ordinal == 2:
                    with archive.open("xb") as target:
                        self.http.download(
                            archive_path(Snapshot(**snapshot)),
                            target,
                            Limits().compressed,
                            checkpoint,
                        )
                    extract(archive, root, checkpoint=checkpoint)
                    filter_sources(
                        root,
                        snapshot["repository"],
                        snapshot["commit_sha"],
                        digest(archive.read_bytes()),
                        checkpoint=checkpoint,
                    )
                    body = archive.read_bytes()
                else:
                    if archive_body is None:
                        raise AnalysisError("artifact_corrupt")
                    archive.write_bytes(archive_body)
                    extract(archive, root, checkpoint=checkpoint)
                    import resource

                    before_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
                    payload = isolated(
                        root,
                        {
                            "stage": ordinal,
                            "snapshot": snapshot,
                            "snapshot_id": str(lease["snapshot_id"]),
                            "archive_hash": digest(archive_body),
                            "inputs": inputs,
                        },
                        checkpoint,
                        {3: 25, 4: 110, 5: 25, 6: 80, 7: 25, 8: 25, 9: 80}[ordinal],
                    )
                    if ordinal == 3:
                        payload = self.preparation_filter(payload)
                    envelope = {
                        "schema_version": "2.2",
                        "kind": STAGES[ordinal],
                        "owner_id": str(lease["owner_id"]),
                        "snapshot_id": str(lease["snapshot_id"]),
                        "commit_sha": snapshot["commit_sha"],
                        "pipeline_version": PIPELINE,
                        "input_digest": input_hash,
                        "generation_metadata": None,
                        "payload": payload,
                    }
                    validate_envelope(envelope)
                    body = canonical(envelope)
                    after_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
                    summary["measurements"] = {
                        "parser_cpu_seconds": after_cpu.ru_utime
                        + after_cpu.ru_stime
                        - before_cpu.ru_utime
                        - before_cpu.ru_stime,
                        "worker_child_peak_rss_kib": after_cpu.ru_maxrss,
                    }
                    if ordinal == 9:
                        summary.update(
                            {
                                "schema": "phase2-summary-v1",
                                "commit_sha": snapshot["commit_sha"],
                                "coverage": payload["knowledge"]["coverage"]["coverage"],
                                "counts": payload["verification"]["counts"],
                            }
                        )
            checkpoint()
            summary.setdefault("measurements", {})["stage_wall_seconds"] = (
                time.monotonic() - started
            )
            uploaded = ObjectRef(
                lease["owner_id"],
                lease["snapshot_id"],
                lease["job_id"],
                uuid4(),
                digest(body),
                "analysis",
            )
            self.storage.write(uploaded, body)
            if self.storage.read(uploaded.owner, uploaded) != body:
                raise AnalysisError("artifact_corrupt")
            checkpoint()
            with self.engine.begin() as c:
                committed = bool(
                    c.scalar(
                        text(
                            "SELECT rv.finish_analysis(:id,:fence,:artifact,:checksum,:ke"
                            "y,:bytes,:input,CAST(:summary AS jsonb))"
                        ),
                        {
                            "id": lease["stage_id"],
                            "fence": lease["fence"],
                            "artifact": uploaded.artifact,
                            "checksum": uploaded.checksum,
                            "key": uploaded.key,
                            "bytes": len(body),
                            "input": input_hash,
                            "summary": canonical(summary).decode(),
                        },
                    )
                )
            if not committed:
                self.storage.delete(uploaded.owner, uploaded)
            return committed
        except Exception as exc:
            code = exc.code if isinstance(exc, AnalysisError) else "analysis_failure"
            transient = exc.transient if isinstance(exc, AnalysisError) else True
            if isinstance(exc, DomainError) and exc.code in {"object_corrupt", "invalid_object"}:
                code, transient = "artifact_corrupt", False
            # A connection can fail after COMMIT: never delete an uncertain committed output.
            with self.engine.begin() as c:
                c.scalar(
                    text("SELECT rv.fail_analysis(:id,:fence,:code,:transient)"),
                    {
                        "id": lease["stage_id"],
                        "fence": lease["fence"],
                        "code": code,
                        "transient": transient,
                    },
                )
            return False

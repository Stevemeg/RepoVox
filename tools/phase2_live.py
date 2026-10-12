"""Opt-in GitHub smoke: rights inspected individually; never official corpus admission."""

import argparse
import base64
import json
import resource
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from repovox.analysis.archive import extract, safe_path
from repovox.analysis.common import PIPELINE, AnalysisError, canonical, digest
from repovox.analysis.contracts import validate_envelope
from repovox.analysis.github import archive_path, repository_url, resolve
from repovox.analysis.runner import STAGES, isolated
from repovox.analysis.transport import GitHubHTTP

parser = argparse.ArgumentParser()
parser.add_argument("repository")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--license-file")
parser.add_argument("--reviewed-license", choices=["MIT", "BSD-3-Clause", "CC0-1.0"])
args = parser.parse_args()
started = time.monotonic()
report = {"repository": args.repository, "official_evaluation_corpus": False, "status": "BLOCKED"}
try:
    http = GitHubHTTP()
    snapshot = resolve(repository_url(args.repository), http)
    report["commit_sha"] = snapshot.commit_sha
    # Read the actual commit-bound license text; a metadata badge is insufficient.
    if args.license_file:
        file = safe_path(args.license_file).as_posix()
        endpoint = f"/repos/{snapshot.repository}/contents/{file}?ref={snapshot.commit_sha}"
    else:
        endpoint = f"/repos/{snapshot.repository}/license?ref={snapshot.commit_sha}"
    license_record = json.loads(http.get("api.github.com", endpoint, 1024**2))
    text = base64.b64decode(license_record["content"], validate=False)
    license_id = args.reviewed_license or license_record["license"]["spdx_id"]
    allowed = (
        (license_id == "MIT" and b"Permission is hereby granted" in text)
        or (license_id == "BSD-3-Clause" and b"Redistribution and use" in text)
        or license_id == "CC0-1.0"
    )
    if not allowed:
        raise AnalysisError("rights_review_required")
    report.update(
        license=license_id,
        license_sha256=digest(text),
        permission_basis=f"{license_id}: engineering analysis; notices retained; "
        "no redistribution, training or official corpus approval.",
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "LICENSE.upstream.txt").write_bytes(text)
    with tempfile.TemporaryDirectory(prefix="repovox-live-") as temporary:
        archive = Path(temporary) / "source.tar.gz"
        root = Path(temporary) / "source"
        with archive.open("xb") as target:
            http.download(archive_path(snapshot), target, 100 * 1024**2, lambda: None)
        extract(archive, root)
        archive_hash = digest(archive.read_bytes())
        request = {
            "snapshot": snapshot.data(),
            "snapshot_id": str(uuid4()),
            "archive_hash": archive_hash,
            "inputs": {},
        }
        for ordinal in range(3, 10):
            stage_start = time.monotonic()
            payload = isolated(root, {**request, "stage": ordinal}, lambda: None, 115)
            envelope = {
                "schema_version": "2.2",
                "kind": STAGES[ordinal],
                "owner_id": str(uuid4()),
                "snapshot_id": request["snapshot_id"],
                "commit_sha": snapshot.commit_sha,
                "pipeline_version": PIPELINE,
                "input_digest": archive_hash,
                "generation_metadata": None,
                "payload": payload,
            }
            validate_envelope(envelope)
            request["inputs"][str(ordinal)] = payload
            report[f"stage_{ordinal}_seconds"] = round(time.monotonic() - stage_start, 4)
        result = request["inputs"]["9"]
        manifest = result["knowledge"]["coverage"]
        report.update(
            status="ANALYZED_STATIC_ONLY",
            examined_files=len(manifest["files"]),
            eligible_bytes=manifest["eligible_bytes"],
            parsed_bytes=manifest["parsed_bytes"],
            coverage=manifest["coverage"],
            symbols=len(result["knowledge"]["symbols"]),
            qualified_edges=len(result["knowledge"]["edges"]),
            entrypoints=result["knowledge"]["entrypoints"],
            claims=result["verification"]["counts"],
            evidence_valid=sum(
                e["validation_status"] == "valid" for e in result["evidence"]["items"]
            ),
            evidence_total=len(result["evidence"]["items"]),
            parser_errors=request["inputs"]["4"]["structure"]["parse_errors"],
            limitations=result["knowledge"]["limitations"],
        )
        (args.output / "verified-analysis.json").write_bytes(canonical(result))
except AnalysisError as exc:
    report["error_code"] = exc.code
except (ValueError, KeyError, TypeError, OSError):
    report["error_code"] = "live_smoke_unavailable"
report["seconds"] = round(time.monotonic() - started, 4)
report["maximum_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
report["parser_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
report["parser_cpu_seconds"] = cpu.ru_utime + cpu.ru_stime
args.output.mkdir(parents=True, exist_ok=True)
(args.output / "report.json").write_bytes(canonical(report))
print(
    json.dumps(
        {
            k: v
            for k, v in report.items()
            if k not in {"entrypoints", "limitations", "parser_errors"}
        }
    )
)
raise SystemExit(0 if report["status"] == "ANALYZED_STATIC_ONLY" else 2)

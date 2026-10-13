"""Rights preflight before archives; proposed replacements are never admitted."""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from repovox.analysis.archive import safe_path
from repovox.analysis.common import AnalysisError
from repovox.analysis.github import repository_url, resolve
from repovox.analysis.privacy import redact, screen_bytes
from repovox.analysis.transport import GitHubHTTP
from repovox.evaluation.corpus import serialize
from repovox.evaluation.exploratory import Policy, write_immutable

PINS = {
    "pallets/click": "2247b35ea1c47c727d7a06e51fa280e12a863ff6",
    "sindresorhus/p-limit": "a8a6fbec4e0e866d6d779b10889bb4f5567e70eb",
    "jupyterlite/echo-kernel": "16221829f0ba38374db8f2b8fda10f989d1a6cdd",
}
SCOPES = {
    "pallets/click": [
        "src/click/__init__.py",
        "src/click/exceptions.py",
        "examples/aliases/aliases.py",
        "pyproject.toml",
        "README.md",
    ],
    "sindresorhus/p-limit": ["index.js", "index.d.ts", "package.json", "readme.md"],
    "jupyterlite/echo-kernel": [
        "jupyterlite_echo_kernel/__init__.py",
        "setup.py",
        "src/index.ts",
        "src/kernel.ts",
        "package.json",
        "README.md",
    ],
}
parser = argparse.ArgumentParser()
parser.add_argument("repository", choices=PINS)
parser.add_argument("--store", type=Path, required=True)
parser.add_argument("--token-stdin", action="store_true")
parser.add_argument("--supplement", action="store_true", help="Inspect remaining opaque files")
args = parser.parse_args()
if os.name == "posix":
    os.umask(0o077)
if args.store.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
    raise ValueError("exploratory_evidence_must_be_outside_git")
token = json.load(sys.stdin).get("github_token") if args.token_stdin else None
http = GitHubHTTP(token)
repo = repository_url(f"https://github.com/{args.repository}")
snapshot = resolve(repo, http)
sha = PINS[repo.identity]
commit = json.loads(
    http.get("api.github.com", f"/repos/{repo.identity}/git/commits/{sha}", 1024**2)
)
tree = json.loads(
    http.get(
        "api.github.com",
        f"/repos/{repo.identity}/git/trees/{commit['tree']['sha']}?recursive=1",
        4 * 1024**2,
    )
)
if commit["sha"] != sha or tree["truncated"] or tree["sha"] != commit["tree"]["sha"]:
    raise ValueError("pinned_tree_incomplete_or_mismatch")
directory = args.store / repo.identity.replace("/", "-")
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
if not args.supplement:
    write_immutable(directory, "preflight/commit.json", serialize(commit))
    write_immutable(directory, "preflight/tree.json", serialize(tree))
license_record = json.loads(
    http.get("api.github.com", f"/repos/{repo.identity}/license?ref={sha}", 1024**2)
)
root_id = license_record["license"]["spdx_id"]
license_body = base64.b64decode(license_record["content"])
if not (
    (root_id == "MIT" and b"Permission is hereby granted" in license_body)
    or (root_id == "BSD-3-Clause" and b"Redistribution and use" in license_body)
):
    raise ValueError("unapproved_root_permission_basis")
if not args.supplement:
    write_immutable(directory, "preflight/root-license.txt", license_body)
remaining = None
if args.supplement:
    previous = json.loads((directory / "preflight/report.json").read_bytes())
    remaining = {r["path"] for r in previous["inventory"] if r["review"].startswith("OPAQUE")}
records, findings, rejected = [], [], []
for item in tree["tree"]:
    if item["type"] != "blob":
        continue
    path = str(safe_path(item["path"]))
    if remaining is not None and path not in remaining:
        continue
    name = path.rsplit("/", 1)[-1].lower()
    if item.get("size", 0) > 1024**2:
        records.append(
            {"path": path, "git_blob_sha": item["sha"], "review": "OPAQUE_OR_OVERSIZED_ROOT_SCOPE"}
        )
        continue
    blob = json.loads(
        http.get("api.github.com", f"/repos/{repo.identity}/git/blobs/{item['sha']}", 2 * 1024**2)
    )
    body = base64.b64decode(blob["content"])
    actual = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
    if actual != item["sha"] or blob["sha"] != actual:
        raise ValueError("pinned_source_blob_changed")
    try:
        screen_bytes(body)
        safe, redactions = redact(body.decode("utf-8"))
    except AnalysisError:
        rejected.append({"path": path, "reason": "PREFLIGHT_SECRET_REJECTION"})
        continue
    except UnicodeDecodeError:
        records.append(
            {
                "path": path,
                "git_blob_sha": actual,
                "file_sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
                "review": "BINARY_EXCLUDED_FROM_REVIEW",
            }
        )
        continue
    headers = [
        {"line": i + 1, "text": line[:400]}
        for i, line in enumerate(safe.splitlines())
        if re.search(
            r"(?i)copyright|spdx|licensed under|license|permission|copied from|"
            r"adapted from|taken from|third.party|vendored",
            line,
        )
    ]
    if headers:
        findings.append({"path": path, "notices": headers[:12]})
    record = {
        "path": path,
        "git_blob_sha": actual,
        "file_sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "review": "TEXT_INSPECTED_FOR_RIGHTS_MARKERS",
        "redactions": redactions,
    }
    records.append(record)
    if (
        args.supplement
        or repo.identity == "jupyterlite/echo-kernel"
        or path in SCOPES[repo.identity]
        or name.startswith(("license", "notice", "copying"))
    ):
        write_immutable(directory, f"preflight/texts/{path}", body)
report = {
    "schema_version": "exploratory-rights-preflight-1.0",
    "policy": Policy().model_dump(),
    "repository": repo.identity,
    "commit_sha": sha,
    "root_license_id": root_id,
    "license_sha256": hashlib.sha256(license_body).hexdigest(),
    "git_tree_sha": tree["sha"],
    "scope": SCOPES[repo.identity],
    "inventory": records,
    "notice_findings": findings,
    "rejections": rejected,
    "decision": "PENDING_IMPLEMENTATION_RIGHTS_REVIEW",
    "archives_downloaded": 0,
    "owner_authorization": "Phase 2C-A prompt; exploratory internal use only",
    "pilot_admission": "PROPOSED_ONLY"
    if repo.identity == "jupyterlite/echo-kernel"
    else "RIGHTS_PENDING",
}
write_immutable(
    directory,
    "preflight/supplement.json" if args.supplement else "preflight/report.json",
    serialize(report),
)
print(
    json.dumps(
        {
            "repository": repo.identity,
            "text_files_checked": sum(r["review"].startswith("TEXT") for r in records),
            "opaque_files": sum(r["review"].startswith("OPAQUE") for r in records),
            "notice_findings": findings,
            "rejections": rejected,
            "archives_downloaded": 0,
        }
    )
)

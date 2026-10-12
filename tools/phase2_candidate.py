"""Individually selected GitHub metadata/license screening; no archives or source execution."""

import argparse
import base64
import json
from pathlib import Path

from repovox.analysis.github import repository_url, resolve
from repovox.analysis.transport import GitHubHTTP
from repovox.evaluation.corpus import checksum

parser = argparse.ArgumentParser()
parser.add_argument("repository", help="One explicitly selected GitHub URL")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
http = GitHubHTTP()
snapshot = resolve(repository_url(args.repository), http)
endpoint = f"/repos/{snapshot.repository}"
metadata = json.loads(http.get("api.github.com", endpoint, 1024**2))
languages = json.loads(http.get("api.github.com", endpoint + "/languages", 1024**2))
try:
    license_record = json.loads(
        http.get("api.github.com", endpoint + f"/license?ref={snapshot.commit_sha}", 1024**2)
    )
except Exception:
    # Missing license remains pending, never an implicit permission grant.
    license_record = None
result = {
    "repository": snapshot.repository,
    "url": snapshot.canonical_url,
    "commit_sha": snapshot.commit_sha,
    "language_metadata": languages,
    "fork": metadata["fork"],
    "parent": metadata.get("parent", {}).get("full_name"),
    "template": metadata.get("template_repository", {}).get("full_name"),
    "license_id": license_record["license"]["spdx_id"] if license_record else "NOASSERTION",
    "license_path": license_record["path"] if license_record else None,
    "license_text_sha256": None,
    "rights_status": "pending",
    "source_downloaded": False,
    "preliminary_coverage": "Metadata only; source coverage and ancestry review pending.",
}
if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
    raise ValueError("screening_evidence_must_remain_outside_git")
args.output.mkdir(parents=True, exist_ok=False)
if license_record:
    body = base64.b64decode(license_record["content"])
    result["license_text_sha256"] = checksum(body)
    (args.output / "LICENSE.inspected.txt").write_bytes(body)
(args.output / "metadata.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result))

"""Analyze one pinned commit of an operator-owned local Git repository. No network access.

The tree comes from `git archive` of an exact commit and goes through the same archive
extraction, secret screening, filtering, parsing and verification code as worker jobs. Source
is parsed, never executed. This development path runs the parser in-process and does not apply
the Linux worker sandbox, so it is for the operator's own repositories only; submitted
repositories continue to require the isolated worker pipeline.
"""

import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repovox.analysis.archive import extract
from repovox.analysis.common import AnalysisError, digest
from repovox.analysis.github import Snapshot, repository_url
from repovox.analysis.sandbox import execute


def git(repository: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "-c", "core.autocrlf=false", *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=120,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise AnalysisError("local_git_unavailable") from None
    if result.returncode != 0:
        raise AnalysisError("local_git_failed")
    return result.stdout


def analyze(
    repository: Path, url: str, revision: str = "HEAD", paths: tuple[str, ...] = ()
) -> dict[str, Any]:
    return analyze_with_sources(repository, url, revision, paths)[0]


def analyze_with_sources(
    repository: Path, url: str, revision: str = "HEAD", paths: tuple[str, ...] = ()
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Verified payload plus the exact parsed and context file bytes it was derived from."""
    identity = repository_url(url)
    if not repository.is_dir() or not re.fullmatch(r"[A-Za-z0-9._/~^-]{1,200}", revision):
        raise AnalysisError("invalid_local_repository")
    if any(
        not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", p) or p.startswith(("/", "-")) or ".." in p
        for p in paths
    ):
        raise AnalysisError("invalid_local_path")
    commit = git(repository, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
    sha = commit.decode("ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise AnalysisError("invalid_local_repository")
    body = git(repository, "archive", "--format=tar.gz", "--prefix=snapshot/", sha, "--", *paths)
    snapshot = Snapshot(
        identity.identity,
        identity.url,
        0,  # Operator-asserted identity: no GitHub metadata was fetched.
        identity.owner,
        identity.name,
        True,
        revision,
        sha,
        datetime.now(UTC).isoformat(),
    ).data()
    request: dict[str, Any] = {
        "snapshot": snapshot,
        "snapshot_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{identity.url}@{sha}")),
        "archive_hash": digest(body),
        "inputs": {},
    }
    with tempfile.TemporaryDirectory(prefix="repovox-local-") as temporary:
        archive = Path(temporary) / "source.tar.gz"
        archive.write_bytes(body)
        root = Path(temporary) / "source"
        extract(archive, root)
        payload: dict[str, Any] = {}
        for stage in (3, 4, 5, 6, 7, 8, 9):
            payload = execute(stage, root, request)
            request["inputs"][str(stage)] = payload
        sources: dict[str, bytes] = {}
        for entry in payload["knowledge"]["coverage"]["files"]:
            if entry["status"] in {"parsed", "context"}:
                body = (root / entry["path"]).read_bytes()
                if digest(body) != entry["file_sha256"]:
                    raise AnalysisError("source_changed")
                sources[entry["path"]] = body
    return payload, sources

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from repovox.analysis.common import (
    ACQUISITION,
    DEFAULT_LIMITS,
    PARSER_VERSION,
    PIPELINE,
    AnalysisError,
    Limits,
)
from repovox.analysis.privacy import scan, screen_bytes, sensitive_path

LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}
EXCLUDED = {
    "node_modules",
    "vendor",
    "vendored",
    "third_party",
    "dist",
    "build",
    ".next",
    "coverage",
    "__pycache__",
    ".venv",
    "venv",
    ".git",
    "generated",
}
CONFIG = {"package.json", "pyproject.toml"}


def filter_sources(
    root: Path,
    repository: str,
    sha: str,
    archive_hash: str,
    limits: Limits = DEFAULT_LIMITS,
    checkpoint: Callable[[], None] = lambda: None,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    eligible = count = excluded = 0
    for path in sorted(root.rglob("*")):
        checkpoint()
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if scan(relative):
            raise AnalysisError("secret_detected")
        size = path.stat().st_size
        file_hash = hashlib.sha256()
        prefix = bytearray()
        overlap = b""
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                checkpoint()
                file_hash.update(chunk)
                screen_bytes(overlap + chunk)
                overlap = chunk[-4096:]
                if len(prefix) < limits.source_file:
                    prefix.extend(chunk[: limits.source_file - len(prefix)])
        body = bytes(prefix)
        p = PurePosixPath(relative)
        language = LANGUAGES.get(p.suffix, "unsupported")
        test = (
            any(x in {"tests", "test", "__tests__"} for x in p.parts)
            or p.name.startswith("test_")
            or (".test." in p.name or ".spec." in p.name or p.name.endswith("_test.py"))
        )
        classification = "test" if test else "source"
        status, reason = "eligible", "supported_source"
        if sensitive_path(relative):
            status, reason, classification = "skipped", "sensitive_path", "sensitive"
        elif set(p.parts) & EXCLUDED:
            status, reason, classification = "skipped", "vendor_or_build", "excluded"
        elif body.startswith(b"version https://git-lfs.github.com/spec/v1"):
            status, reason, classification = "skipped", "git_lfs_pointer", "unsupported"
        elif p.name in {
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "poetry.lock",
            "uv.lock",
        }:
            status, reason, classification = "skipped", "dependency_lockfile", "dependency_snapshot"
        elif size > limits.source_file:
            status, reason = (
                "skipped",
                "oversized_source" if language != "unsupported" else "oversized_context",
            )
        elif p.name.endswith((".min.js", ".min.ts")) or (
            language in {"javascript", "typescript", "tsx"}
            and max(map(len, body.split(b"\n")), default=0) > 10_000
        ):
            status, reason, classification = "skipped", "minified", "generated"
        elif (
            b"@generated" in body[:4096].lower()
            or b"automatically generated" in body[:4096].lower()
        ):
            status, reason, classification = "skipped", "generated_marker", "generated"
        elif p.name in CONFIG or p.name.lower().startswith("readme"):
            status, reason, classification = (
                "context",
                "declarative_context",
                "configuration" if p.name in CONFIG else "documentation",
            )
        elif language == "unsupported":
            status, reason, classification = "skipped", "unsupported_language", "unsupported"
        if status == "eligible":
            eligible += size
            count += 1
            if eligible > limits.source_bytes or count > limits.source_files:
                raise AnalysisError("eligible_source_limit")
        try:
            body.decode("utf-8")
        except UnicodeDecodeError:
            if status in {"eligible", "context"}:
                status, reason = (
                    "failed" if language != "unsupported" else "skipped",
                    "invalid_utf8",
                )
        if b"\0" in body and status in {"eligible", "context"}:
            status, reason = "failed" if language != "unsupported" else "skipped", "binary_content"
        if status == "skipped":
            excluded += size
        records.append(
            {
                "path": relative,
                "file_sha256": file_hash.hexdigest(),
                "bytes": size,
                "language": language,
                "classification": classification,
                "status": status,
                "reason": reason,
                "parsed_bytes": 0,
            }
        )
    return {
        "repository": repository,
        "commit_sha": sha,
        "acquisition_version": ACQUISITION,
        "archive_sha256": archive_hash,
        "files": records,
        "eligible_bytes": eligible,
        "parsed_bytes": 0,
        "excluded_bytes": excluded,
        "eligible_files": count,
        "processing_timestamp": datetime.now(UTC).isoformat(),
        "parser_version": PARSER_VERSION,
        "pipeline_version": PIPELINE,
    }

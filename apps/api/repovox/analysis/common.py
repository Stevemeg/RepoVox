import hashlib
import json
from dataclasses import dataclass
from typing import Any

PIPELINE = "phase2-static-v1"
ACQUISITION = "github-archive-v1"
RULES = "static-rules-v1"
PARSER_VERSION = "tree-sitter-0.25.2/python-0.25.0/js-0.25.0/ts-0.23.2"


class AnalysisError(Exception):
    """Only a fixed code crosses a log, queue or API boundary."""

    def __init__(self, code: str, transient: bool = False) -> None:
        self.code, self.transient = code, transient
        super().__init__(code)


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def stable(prefix: str, *values: Any) -> str:
    return f"{prefix}-{digest(canonical(values))[:32]}"


@dataclass(frozen=True)
class Limits:
    compressed: int = 100 * 1024**2
    extracted: int = 250 * 1024**2
    files: int = 10_000
    source_file: int = 1024**2
    source_files: int = 5_000
    source_bytes: int = 100 * 1024**2
    depth: int = 32
    # Tar headers/padding are bounded too, independently of regular file sizes.
    tar_bytes: int = 280 * 1024**2
    facts: int = 10_000


DEFAULT_LIMITS = Limits()

import gzip
import io
import re
import tarfile
import unicodedata
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Protocol

from repovox.analysis.common import DEFAULT_LIMITS, AnalysisError, Limits

ARCHIVES = (".tar", ".tgz", ".gz", ".zip", ".7z", ".rar", ".bz2", ".xz")


class CheckedTarInfo(tarfile.TarInfo):
    @classmethod
    def frombuf(cls, buf: bytes | bytearray, encoding: str, errors: str) -> "CheckedTarInfo":
        for field in [buf[:100], buf[345:500]]:
            _, separator, remainder = field.partition(b"\0")
            if separator and remainder.strip(b"\0"):
                raise AnalysisError("archive_unsafe_path")
        return super().frombuf(buf, encoding, errors)


def safe_path(value: str, limits: Limits = DEFAULT_LIMITS) -> PurePosixPath:
    if (
        not value
        or len(value.encode("utf-8")) > 1024
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise AnalysisError("archive_unsafe_path")
    parts = value.rstrip("/").split("/")
    if len(parts) > limits.depth or any(
        p in {"", ".", ".."}
        or p.endswith((".", " "))
        or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p)
        for p in parts
    ):
        raise AnalysisError("archive_unsafe_path")
    return PurePosixPath(*parts)


class Readable(Protocol):
    def read(self, size: int = -1) -> bytes: ...


class BoundedReader(io.RawIOBase):
    def __init__(self, source: Readable, limit: int, checkpoint: Callable[[], None]) -> None:
        self.source, self.limit, self.checkpoint = source, limit, checkpoint
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        self.checkpoint()
        data = self.source.read(min(size if size >= 0 else 64 * 1024, 64 * 1024))
        self.count += len(data)
        if self.count > self.limit:
            raise AnalysisError("archive_expansion_limit")
        return data


def extract(
    archive: Path,
    scratch: Path,
    limits: Limits = DEFAULT_LIMITS,
    checkpoint: Callable[[], None] = lambda: None,
) -> list[Path]:
    if scratch.exists():
        raise AnalysisError("scratch_not_fresh")
    scratch.mkdir(mode=0o700)
    root = scratch.resolve()
    if archive.stat().st_size > limits.compressed:
        raise AnalysisError("archive_download_limit")
    seen: set[str] = set()
    normalized: dict[str, str] = {}
    files: list[Path] = []
    total = members = 0
    archive_root: str | None = None
    try:
        with archive.open("rb") as raw, gzip.GzipFile(fileobj=raw) as gz:
            bounded = BoundedReader(gz, limits.tar_bytes, checkpoint)
            with tarfile.open(fileobj=bounded, mode="r|", tarinfo=CheckedTarInfo) as tar:
                for member in tar:
                    checkpoint()
                    members += 1
                    if members > limits.files * 2 + limits.depth:
                        raise AnalysisError("archive_member_limit")
                    name = member.name.rstrip("/")
                    path = safe_path(name, limits)
                    if name in seen:
                        raise AnalysisError("archive_duplicate")
                    seen.add(name)
                    for i in range(1, len(path.parts) + 1):
                        prefix = "/".join(path.parts[:i])
                        key = unicodedata.normalize("NFKC", prefix).casefold()
                        if key in normalized and normalized[key] != prefix:
                            raise AnalysisError("archive_collision")
                        normalized[key] = prefix
                    if archive_root is None:
                        archive_root = path.parts[0]
                    if path.parts[0] != archive_root:
                        raise AnalysisError("archive_multiple_roots")
                    if member.issparse() or any("sparse" in k.lower() for k in member.pax_headers):
                        raise AnalysisError("archive_unsafe_entry")
                    if not member.isdir() and not member.isreg():
                        raise AnalysisError("archive_unsafe_entry")
                    if len(path.parts) == 1:
                        if not member.isdir():
                            raise AnalysisError("archive_missing_root")
                        continue
                    relative = PurePosixPath(*path.parts[1:])
                    destination = root.joinpath(*relative.parts)
                    if not destination.resolve().is_relative_to(root):
                        raise AnalysisError("archive_unsafe_path")
                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
                        continue
                    total += member.size
                    if member.size < 0 or total > limits.extracted or len(files) >= limits.files:
                        raise AnalysisError("archive_extraction_limit")
                    if name.lower().endswith(ARCHIVES):
                        raise AnalysisError("archive_nested")
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    source = tar.extractfile(member)
                    if source is None:
                        raise AnalysisError("archive_malformed")
                    written = 0
                    with source, destination.open("xb") as target:
                        while chunk := source.read(64 * 1024):
                            checkpoint()
                            if written == 0 and chunk.startswith(
                                (b"PK\x03\x04", b"\x1f\x8b", b"7z\xbc\xaf\x27\x1c")
                            ):
                                raise AnalysisError("archive_nested")
                            written += len(chunk)
                            if written > member.size:
                                raise AnalysisError("archive_extraction_limit")
                            target.write(chunk)
                    if written != member.size:
                        raise AnalysisError("archive_malformed")
                    files.append(destination)
            # Account for compressed trailing data/bombs after the end-of-tar marker.
            while bounded.read(64 * 1024):
                pass
    except (tarfile.TarError, OSError, EOFError, ValueError):
        raise AnalysisError("archive_malformed") from None
    return sorted(files)

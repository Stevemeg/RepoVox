"""Development-only acquisition source: locally authored synthetic repositories from disk.

Stands in for the GitHub transport so the whole product workflow can run without acquiring any
external repository. It answers only for `https://github.com/synthetic/<directory>` and serves
a deterministic archive of that directory. The 40-hex identifier it reports is a digest of the
archive, not a Git commit, and nothing produced through this source is evidence about external
repository acquisition. It can only be enabled outside production, with fixtures enabled.
"""

import gzip
import hashlib
import io
import re
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from repovox.analysis.common import AnalysisError, canonical

OWNER = "synthetic"
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")


class SyntheticSource:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        if not self.root.is_dir():
            raise RuntimeError("Synthetic source directory not found")

    def directory(self, name: str) -> Path:
        path = (self.root / name).resolve()
        if not NAME.fullmatch(name) or path.parent != self.root or not path.is_dir():
            raise AnalysisError("repository_not_found")
        return path

    def archive(self, name: str) -> bytes:
        """Deterministic tar.gz: sorted members, fixed metadata, one root directory."""
        directory = self.directory(name)
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as tar:
                root = tarfile.TarInfo(f"{name}-synthetic")
                root.type, root.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(root)
                for path in sorted(p for p in directory.rglob("*") if p.is_file()):
                    relative = path.relative_to(directory).as_posix()
                    if path.is_symlink() or "__pycache__" in relative:
                        continue
                    body = path.read_bytes()
                    member = tarfile.TarInfo(f"{name}-synthetic/{relative}")
                    member.size, member.mode = len(body), 0o644
                    tar.addfile(member, io.BytesIO(body))
        return buffer.getvalue()

    def identifier(self, name: str) -> str:
        return hashlib.sha1(self.archive(name), usedforsecurity=False).hexdigest()

    def get(self, host: str, path: str, limit: int, seconds: float = 10) -> bytes:
        match = re.fullmatch(rf"/repos/{OWNER}/([^/]+)(/commits/[^/]+)?", path)
        if host != "api.github.com" or match is None:
            raise AnalysisError("repository_not_found")
        name = match.group(1)
        self.directory(name)
        if match.group(2):
            return canonical({"sha": self.identifier(name)})
        return canonical(
            {
                "id": int(hashlib.sha256(name.encode()).hexdigest()[:8], 16),
                "private": False,
                "visibility": "public",
                "default_branch": "synthetic",
                "html_url": f"https://github.com/{OWNER}/{name}",
            }
        )

    def download(
        self, path: str, target: BinaryIO, limit: int, checkpoint: Callable[[], None]
    ) -> None:
        match = re.fullmatch(rf"/{OWNER}/([^/]+)/tar\.gz/([a-f0-9]{{40}})", path)
        if match is None:
            raise AnalysisError("repository_not_found")
        body = self.archive(match.group(1))
        # The pinned identifier must still describe the bytes being served.
        if hashlib.sha1(body, usedforsecurity=False).hexdigest() != match.group(2):
            raise AnalysisError("repository_identity_changed")
        if len(body) > limit:
            raise AnalysisError("archive_download_limit")
        checkpoint()
        target.write(body)

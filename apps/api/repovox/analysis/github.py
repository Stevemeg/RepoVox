import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from repovox.analysis.common import ACQUISITION, AnalysisError
from repovox.analysis.privacy import scan


@dataclass(frozen=True)
class Repository:
    owner: str
    name: str

    @property
    def identity(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.identity}"


def repository_url(value: str) -> Repository:
    if not value.isascii() or len(value) > 250 or any(ord(c) < 33 for c in value):
        raise AnalysisError("invalid_repository_url")
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or parts.netloc != "github.com"
            or parts.hostname != "github.com"
            or parts.port is not None
            or parts.username is not None
            or parts.query
            or parts.fragment
            or "?" in value
            or "#" in value
        ):
            raise ValueError
        match = re.fullmatch(r"/([A-Za-z0-9-]{1,39})/([A-Za-z0-9_.-]{1,100})/?", parts.path)
        if not match:
            raise ValueError
        owner, name = match.groups()
        name = name.removesuffix(".git")
        if not name or name in {".", ".."} or owner.startswith("-") or owner.endswith("-"):
            raise ValueError
        if "--" in owner:
            raise ValueError
    except ValueError:
        raise AnalysisError("invalid_repository_url") from None
    return Repository(owner.lower(), name.lower())


@dataclass(frozen=True)
class Snapshot:
    repository: str
    canonical_url: str
    github_id: int
    owner: str
    name: str
    public: bool
    default_branch: str
    commit_sha: str
    acquired_at: str
    acquisition_version: str = ACQUISITION

    def data(self) -> dict[str, Any]:
        return asdict(self)


class HTTP(Protocol):
    def get(self, host: str, path: str, limit: int, seconds: float = 10) -> bytes: ...


def resolve(repo: Repository, http: HTTP) -> Snapshot:
    deadline = time.monotonic() + 10
    try:
        metadata = json.loads(http.get("api.github.com", f"/repos/{repo.identity}", 1024**2))
        if metadata.get("private") is True or metadata.get("visibility") == "private":
            raise AnalysisError("repository_private")
        if metadata.get("private") is not False or metadata.get("visibility") != "public":
            raise ValueError
        actual = repository_url(metadata["html_url"])
        if actual != repo:
            raise AnalysisError("repository_identity_changed")
        branch = metadata["default_branch"]
        if not isinstance(branch, str) or not branch or len(branch) > 255:
            raise ValueError
        if scan(branch) or any(ord(c) < 32 for c in branch):
            raise AnalysisError("github_invalid_metadata")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AnalysisError("github_timeout", True)
        head = json.loads(
            http.get(
                "api.github.com",
                f"/repos/{repo.identity}/commits/{quote(branch, safe='')}",
                1024**2,
                remaining,
            )
        )
        sha = head["sha"]
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError
        if not isinstance(metadata["id"], int) or isinstance(metadata["id"], bool):
            raise ValueError
        return Snapshot(
            repo.identity,
            repo.url,
            metadata["id"],
            repo.owner,
            repo.name,
            True,
            branch,
            sha,
            datetime.now(UTC).isoformat(),
        )
    except (ValueError, KeyError, TypeError):
        raise AnalysisError("github_invalid_metadata") from None


def archive_path(snapshot: Snapshot) -> str:
    repo = repository_url(snapshot.canonical_url)
    if repo.identity != snapshot.repository or not re.fullmatch(
        r"[a-f0-9]{40}", snapshot.commit_sha
    ):
        raise AnalysisError("invalid_snapshot")
    return f"/{repo.identity}/tar.gz/{snapshot.commit_sha}"

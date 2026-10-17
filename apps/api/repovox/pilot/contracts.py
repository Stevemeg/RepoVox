"""Owner-approved original-file scope, independent of analyzer output."""

from pathlib import Path
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from repovox.analysis.archive import safe_path
from repovox.analysis.common import Limits, canonical, digest

ENGINE: Final[Literal["711184e82128c7b0a6f3978cfc1cf13975db39ef"]] = (
    "711184e82128c7b0a6f3978cfc1cf13975db39ef"
)
SHA = r"^[a-f0-9]{64}$"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class File(Record):
    path: str
    sha256: str = Field(pattern=SHA)
    size: int = Field(ge=1, le=Limits().source_file)
    role: Literal["source", "context"]

    @model_validator(mode="after")
    def valid_path(self) -> "File":
        if str(safe_path(self.path)) != self.path:
            raise ValueError("pilot_path")
        return self


class Family(Record):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    files: tuple[File, ...] = Field(min_length=1, max_length=Limits().source_files)

    @model_validator(mode="after")
    def unique_files(self) -> "Family":
        if len({f.path for f in self.files}) != len(self.files):
            raise ValueError("pilot_duplicate_path")
        if not any(f.role == "source" for f in self.files):
            raise ValueError("pilot_source_required")
        if sum(f.size for f in self.files) > Limits().source_bytes:
            raise ValueError("pilot_source_limit")
        return self


class Manifest(Record):
    version: Literal["pilot-control-1.0"] = "pilot-control-1.0"
    owner: UUID
    engine: Literal["711184e82128c7b0a6f3978cfc1cf13975db39ef"] = ENGINE
    scorer: Literal["711184e82128c7b0a6f3978cfc1cf13975db39ef"] = ENGINE
    approval_sha256: str = Field(pattern=SHA)
    engine_files: dict[str, str]
    families: tuple[Family, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_families(self) -> "Manifest":
        if len({f.id for f in self.families}) != len(self.families):
            raise ValueError("pilot_duplicate_family")
        if len({f.repository.lower() for f in self.families}) != len(self.families):
            raise ValueError("pilot_duplicate_repository")
        return self

    def body(self) -> bytes:
        return canonical(self.model_dump(mode="json"))

    @property
    def sha256(self) -> str:
        return digest(self.body())

    def verify_engine(self) -> None:
        root = Path(__file__).resolve().parents[1]
        files = {
            p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in (root / "analysis").rglob("*.py")
        }
        if files != self.engine_files:
            raise ValueError("pilot_engine_freeze_mismatch")


def decode(body: bytes, expected: str) -> Manifest:
    if len(body) > 1024 * 1024 or digest(body) != expected:
        raise ValueError("pilot_manifest_commitment")
    manifest = Manifest.model_validate_json(body)
    if manifest.body() != body:
        raise ValueError("pilot_manifest_not_canonical")
    return manifest

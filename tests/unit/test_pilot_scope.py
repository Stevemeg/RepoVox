"""Independent synthetic source-scope attacks; no pilot repository or answer data."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from repovox.analysis.common import AnalysisError, digest
from repovox.analysis.filtering import filter_sources
from repovox.pilot.contracts import Family, File, Manifest, decode
from repovox.pilot.execution import scoped


@pytest.fixture
def fixture(tmp_path: Path) -> tuple[dict, Family]:
    bodies = {
        "app.py": b"def run():\n    return 7\n",
        "README.md": b"Source context.\n",
        "test_extra.py": b"def outside():\n    return 'not approved'\n",
    }
    for name, body in bodies.items():
        (tmp_path / name).write_bytes(body)
    family = Family(
        id="sample",
        repository="example/independent",
        commit="a" * 40,
        files=tuple(
            File(
                path=p,
                sha256=digest(bodies[p]),
                size=len(bodies[p]),
                role="source" if p.endswith(".py") else "context",
            )
            for p in ["app.py", "README.md"]
        ),
    )
    return filter_sources(tmp_path, family.repository, family.commit, "b" * 64), family


def test_excluded_test_never_becomes_analyzer_input(fixture: tuple[dict, Family]) -> None:
    raw, family = fixture
    with pytest.raises(ValueError, match="pilot_unapproved_source"):
        scoped(raw, family)
    filtered = scoped(raw, family, apply=True)
    assert next(f for f in filtered["files"] if f["path"] == "test_extra.py")["status"] == "skipped"
    assert [f["path"] for f in filtered["files"] if f["status"] == "eligible"] == ["app.py"]
    assert scoped(filtered, family) == filtered
    assert next(f for f in raw["files"] if f["path"] == "test_extra.py")["status"] == "eligible"


@pytest.mark.parametrize("field,value", [("repository", "example/other"), ("commit_sha", "c" * 40)])
def test_cross_family_identity(fixture: tuple[dict, Family], field: str, value: str) -> None:
    raw, family = fixture
    raw[field] = value
    with pytest.raises(ValueError, match="pilot_source_identity"):
        scoped(raw, family, apply=True)


@pytest.mark.parametrize(
    "field,value", [("file_sha256", "d" * 64), ("bytes", 999), ("status", "skipped")]
)
def test_original_hash_size_and_role(
    fixture: tuple[dict, Family], field: str, value: object
) -> None:
    raw, family = fixture
    next(f for f in raw["files"] if f["path"] == "app.py")[field] = value
    with pytest.raises(ValueError, match="pilot_original_source_changed|pilot_file_role"):
        scoped(raw, family, apply=True)


def test_missing_or_duplicate_manifest_entries(fixture: tuple[dict, Family]) -> None:
    raw, family = fixture
    duplicate = deepcopy(raw)
    duplicate["files"].append(duplicate["files"][0])
    with pytest.raises(ValueError, match="pilot_duplicate_inventory"):
        scoped(duplicate, family)
    raw["files"] = [f for f in raw["files"] if f["path"] != "README.md"]
    with pytest.raises(ValueError, match="pilot_original_source_changed"):
        scoped(raw, family)


@pytest.mark.parametrize("path", ["../out.py", "/absolute.py", "a/../b.py", "a\\b.py", "a:b.py"])
def test_escape_rejection(path: str) -> None:
    with pytest.raises((ValueError, AnalysisError), match="pilot_path|archive_unsafe_path"):
        File(path=path, sha256="f" * 64, size=10, role="source")


def test_versioned_manifest_commitment_and_engine(fixture: tuple[dict, Family]) -> None:
    _, family = fixture
    manifest = Manifest(
        owner=uuid4(), approval_sha256="c" * 64, engine_files={}, families=(family,)
    )
    assert decode(manifest.body(), manifest.sha256) == manifest
    with pytest.raises(ValueError, match="pilot_manifest_commitment"):
        decode(manifest.body() + b" ", manifest.sha256)
    with pytest.raises(ValueError, match="pilot_engine_freeze_mismatch"):
        manifest.verify_engine()
    with pytest.raises(ValidationError):
        Manifest.model_validate_json(
            manifest.body().replace(b"pilot-control-1.0", b"pilot-control-9.0")
        )
    with pytest.raises(ValidationError, match="pilot_duplicate_family"):
        Manifest(
            owner=uuid4(), approval_sha256="c" * 64, engine_files={}, families=(family, family)
        )

"""Large merge commits resolve by SHA alone; model weight containers are skipped, not unpacked.

Both cases are synthetic. The merge-commit shape mirrors what the GitHub commit endpoint embeds
(up to 300 changed files with patches); the weight files are ZIP local-file headers, which is
how `torch.save` and Keras write `.pt`/`.pth`/`.keras` files.
"""

import hashlib
import io
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from repovox.analysis.archive import WEIGHT_REASON, extract
from repovox.analysis.common import AnalysisError, Limits, canonical
from repovox.analysis.contracts import PAYLOADS
from repovox.analysis.filtering import filter_sources
from repovox.analysis.github import METADATA_LIMIT, SHA_LIMIT, Snapshot, repository_url, resolve
from repovox.analysis.sandbox import execute

SHA = "c" * 40
ZIP = b"PK\x03\x04" + bytes(range(60))
WEIGHTS = ZIP + b"\x00\x01\x02weights" * 8_000  # a few tens of KiB, read in several chunks


class MergeCommitGitHub:
    """Answers like the GitHub API for a repository whose HEAD is a 300-file merge commit."""

    def __init__(self, sha_body: bytes = SHA.encode("ascii")) -> None:
        self.sha_body = sha_body
        self.requests: list[tuple[str, int, str]] = []

    @staticmethod
    def commit_object() -> bytes:
        files = [
            {"filename": f"docs/page_{i}.md", "status": "added", "patch": "+" + "line\n" * 900}
            for i in range(300)
        ]
        return canonical({"sha": SHA, "stats": {"total": 32784}, "files": files})

    def get(
        self, host: str, path: str, limit: int, seconds: float = 10, *, media: str = "json"
    ) -> bytes:
        assert host == "api.github.com"
        self.requests.append((path, limit, media))
        if "/commits/" in path:
            body = self.sha_body if media == "sha" else self.commit_object()
        else:
            assert media == "json"
            body = canonical(
                {
                    "id": 7,
                    "private": False,
                    "visibility": "public",
                    "html_url": "https://github.com/Example/Merged",
                    "default_branch": "main",
                }
            )
        if len(body) > limit:  # GitHubHTTP enforces the same bound while streaming.
            raise AnalysisError("archive_download_limit")
        return body


def test_large_merge_commit_resolves_without_downloading_patches() -> None:
    client = MergeCommitGitHub()
    # The precondition this guards: the patch-bearing commit object is over the metadata cap.
    assert len(client.commit_object()) > METADATA_LIMIT == 1024**2
    pinned = resolve(repository_url("https://github.com/example/merged"), client)
    assert pinned.commit_sha == SHA
    assert client.requests == [
        ("/repos/example/merged", METADATA_LIMIT, "json"),
        ("/repos/example/merged/commits/main", SHA_LIMIT, "sha"),
    ]
    assert SHA_LIMIT < 100  # the commit answer is bounded to a few bytes, not to 1 MiB


@pytest.mark.parametrize(
    "body",
    [
        (SHA + "\n").encode(),
        SHA.upper().encode(),
        SHA[:-1].encode(),
        canonical({"sha": SHA}),
        b"\xff" * 40,
        b"",
    ],
)
def test_commit_sha_answer_is_validated_strictly(body: bytes) -> None:
    with pytest.raises(AnalysisError, match="github_invalid_metadata"):
        resolve(repository_url("https://github.com/example/merged"), MergeCommitGitHub(body))


def build(tmp_path: Path, members: dict[str, bytes]) -> Path:
    target = tmp_path / "source.tar.gz"
    with tarfile.open(target, "w:gz") as tar:
        root = tarfile.TarInfo("snapshot")
        root.type = tarfile.DIRTYPE
        tar.addfile(root)
        for name, body in members.items():
            info = tarfile.TarInfo(f"snapshot/{name}")
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return target


def test_weight_containers_are_skipped_and_never_written(tmp_path: Path) -> None:
    members = {
        "app/main.py": b"def main():\n    return 1\n",
        "backend/generator_brain.pth": WEIGHTS,
        "models/only/encoder.PT": ZIP,
        "vae_decoder_model.keras": ZIP + b"keras",
    }
    scratch = tmp_path / "scratch"
    skipped: list[dict] = []
    files = extract(build(tmp_path, members), scratch, skipped=skipped)
    assert [p.relative_to(scratch).as_posix() for p in files] == ["app/main.py"]
    written = sorted(p.relative_to(scratch).as_posix() for p in scratch.rglob("*"))
    assert written == ["app", "app/main.py"]  # no weight file and no weight-only directory
    assert skipped == [
        {
            "path": name,
            "file_sha256": hashlib.sha256(members[name]).hexdigest(),
            "bytes": len(members[name]),
        }
        for name in [
            "backend/generator_brain.pth",
            "models/only/encoder.PT",
            "vae_decoder_model.keras",
        ]
    ]


def test_without_a_collector_weight_containers_stay_nested_archives(tmp_path: Path) -> None:
    with pytest.raises(AnalysisError, match="archive_nested"):
        extract(build(tmp_path, {"model.pth": ZIP}), tmp_path / "scratch")


@pytest.mark.parametrize(
    "name,body",
    [
        ("bundle.zip", ZIP),
        ("bundle.tar", b"x"),
        ("data.gz", b"\x1f\x8b"),
        ("data.bz2", b"x"),
        ("data.xz", b"x"),
        ("data.7z", b"7z\xbc\xaf\x27\x1c"),
        ("disguised.py", ZIP),
        ("lib.jar", ZIP),
        ("pkg-1.0-py3-none-any.whl", ZIP),
        ("report.docx", ZIP),
        ("noextension", ZIP),
        ("weights.pkl", ZIP),
        ("model.pth.zip", ZIP),
        ("model.pth.py", ZIP),
        ("archive.npz", ZIP),
        ("compressed.pt.gz", b"\x1f\x8b"),
    ],
)
def test_other_archives_are_still_rejected_with_a_collector(
    tmp_path: Path, name: str, body: bytes
) -> None:
    skipped: list[dict] = []
    with pytest.raises(AnalysisError, match="archive_nested"):
        extract(
            build(tmp_path, {"model.pth": ZIP, name: body}), tmp_path / "scratch", skipped=skipped
        )


@pytest.mark.parametrize(
    "limits", [replace(Limits(), files=1), replace(Limits(), extracted=len(WEIGHTS))]
)
def test_skipped_members_count_toward_quotas(tmp_path: Path, limits: Limits) -> None:
    archive = build(tmp_path, {"a.py": b"x = 1\n", "b.pth": WEIGHTS})
    with pytest.raises(AnalysisError, match="archive_extraction_limit"):
        extract(archive, tmp_path / "scratch", limits, skipped=[])


def test_skipped_bytes_are_still_secret_screened(tmp_path: Path) -> None:
    secret = b"AKIA" + b"Q" * 16  # shaped like an AWS access key id; built, not a literal
    archive = build(tmp_path, {"model.pth": ZIP + b"\x00" * 70_000 + secret})
    with pytest.raises(AnalysisError, match="secret_detected"):
        extract(archive, tmp_path / "scratch", skipped=[])


def snapshot() -> dict:
    return Snapshot(
        "example/merged",
        "https://github.com/example/merged",
        7,
        "example",
        "merged",
        True,
        "main",
        "a" * 40,
        "2026-11-20T00:00:00Z",
    ).data()


def analyze(root: Path, skipped: list[dict]) -> dict:
    request = {
        "snapshot": snapshot(),
        "snapshot_id": "11111111-1111-4111-8111-111111111111",
        "archive_hash": "b" * 64,
        "inputs": {},
        "skipped_members": skipped,
    }
    stages = [(3, "filter"), (4, "structure"), (5, "entrypoints"), (6, "infer")]
    stages += [(7, "knowledge"), (8, "evidence"), (9, "verify")]
    for ordinal, kind in stages:
        payload = execute(ordinal, root, request)
        TypeAdapter(PAYLOADS[kind]).validate_python(payload)
        request["inputs"][str(ordinal)] = payload
    return request


MAIN = b'def main(x):\n    return x\nif __name__ == "__main__":\n    main(1)\n'


def test_skipped_weights_are_recorded_and_verified(tmp_path: Path) -> None:
    skipped: list[dict] = []
    root = tmp_path / "source"
    extract(build(tmp_path, {"main.py": MAIN, "backend/model.pth": WEIGHTS}), root, skipped=skipped)
    request = analyze(root, skipped)
    manifest = request["inputs"]["3"]
    entry = next(f for f in manifest["files"] if f["path"] == "backend/model.pth")
    assert entry == {
        "path": "backend/model.pth",
        "file_sha256": hashlib.sha256(WEIGHTS).hexdigest(),
        "bytes": len(WEIGHTS),
        "language": "unsupported",
        "classification": "unsupported",
        "status": "skipped",
        "reason": WEIGHT_REASON,
        "parsed_bytes": 0,
    }
    assert manifest["excluded_bytes"] >= len(WEIGHTS)
    assert [f["path"] for f in manifest["files"]] == ["backend/model.pth", "main.py"]

    # Stage 9 checks the manifest against its own re-extraction of the archive.
    for forged in (
        [],
        [{**skipped[0], "file_sha256": "0" * 64}],
        [{**skipped[0], "bytes": 1}],
        skipped + [{**skipped[0], "path": "backend/other.pth"}],
    ):
        with pytest.raises(AnalysisError, match="source_changed"):
            execute(9, root, {**request, "skipped_members": forged})
    (root / "backend").mkdir()
    (root / "backend/model.pth").write_bytes(WEIGHTS)
    with pytest.raises(AnalysisError, match="source_changed"):
        execute(9, root, request)


@pytest.mark.parametrize(
    "item,code",
    [
        ({"path": "notes.txt", "file_sha256": "a" * 64, "bytes": 1}, "artifact_corrupt"),
        ({"path": "m.pth", "file_sha256": "A" * 64, "bytes": 1}, "artifact_corrupt"),
        ({"path": "m.pth", "file_sha256": "a" * 64, "bytes": -1}, "artifact_corrupt"),
        ({"path": "m.pth", "file_sha256": "a" * 64, "bytes": True}, "artifact_corrupt"),
        ({"path": "m.pth", "file_sha256": "a" * 64, "bytes": 1, "x": 1}, "artifact_corrupt"),
        ({"path": "../m.pth", "file_sha256": "a" * 64, "bytes": 1}, "archive_unsafe_path"),
        ({"path": "main.py.pth", "file_sha256": "a" * 64, "bytes": 1}, "archive_duplicate"),
    ],
)
def test_filter_rejects_malformed_skip_records(tmp_path: Path, item: dict, code: str) -> None:
    (tmp_path / "main.py.pth").write_bytes(b"on disk")
    with pytest.raises(AnalysisError, match=code):
        filter_sources(tmp_path, "example/merged", "a" * 40, "b" * 64, skipped=[item])

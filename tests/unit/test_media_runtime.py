"""Handoff support, failure classification, bounded retrieval and the synthetic source."""

import hashlib
import io
import tarfile
import tracemalloc
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from repovox.analysis.common import AnalysisError
from repovox.analysis.github import archive_path, repository_url, resolve
from repovox.core.config import Settings
from repovox.core.errors import DomainError
from repovox.media.architecture import ArchitectureError
from repovox.media.store import CHUNK, MediaStorage, media_key
from repovox.media.worker import ArchitecturePhase
from repovox.services.media_jobs import MediaJobs
from repovox.synthetic_source import SyntheticSource

FIXTURES = Path(__file__).parents[1] / "fixtures" / "architectures"


class Body:
    def __init__(self, data: bytes) -> None:
        self.data, self.position, self.largest, self.closed = data, 0, 0, False

    def read(self, amount: int) -> bytes:
        self.largest = max(self.largest, amount)
        chunk = self.data[self.position : self.position + amount]
        self.position += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class Bucket:
    """The three S3 calls retrieval uses, over in-memory objects."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.gets = 0
        self.bodies: list[Body] = []

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        data = self.objects[Key]
        return {"ContentLength": len(data), "ETag": hashlib.md5(data).hexdigest()}  # noqa: S324

    def get_object(self, Bucket: str, Key: str, Range: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        self.gets += 1
        start, end = (int(part) for part in Range.removeprefix("bytes=").split("-"))
        body = Body(self.objects[Key][start : end + 1])
        self.bodies.append(body)
        return {"Body": body}


def storage(bucket: Bucket) -> MediaStorage:
    found = MediaStorage.__new__(MediaStorage)
    found.client, found.bucket = bucket, "b"  # type: ignore[assignment]
    import threading

    found.verifying = threading.BoundedSemaphore(2)
    found.verified, found.lock = {}, threading.Lock()
    return found


def stored(bucket: Bucket, data: bytes, owner: Any = None) -> tuple[Any, str]:
    owner = owner or uuid4()
    key = media_key(owner, uuid4(), 14, uuid4(), hashlib.sha256(data).hexdigest())
    bucket.objects[key] = data
    return owner, key


def test_verification_streams_in_bounded_chunks_and_is_remembered_per_version() -> None:
    bucket = Bucket()
    data = bytes(range(256)) * 4096  # 1 MiB
    owner, key = stored(bucket, data)
    store = storage(bucket)
    store.verify(owner, key, len(data))
    assert bucket.gets == 1 and bucket.bodies[0].largest <= CHUNK and bucket.bodies[0].closed
    store.verify(owner, key, len(data))
    assert bucket.gets == 1  # Same stored version: not hashed again.
    # A replaced object has a new ETag, is hashed again, and is refused.
    bucket.objects[key] = bytes(len(data))
    with pytest.raises(DomainError, match="object_corrupt"):
        store.verify(owner, key, len(data))
    assert bucket.gets == 2
    bucket.objects[key] = data[:-1]
    with pytest.raises(DomainError, match="object_corrupt"):
        store.verify(owner, key, len(data))
    assert bucket.gets == 2  # A wrong length is refused before any body is read.
    del bucket.objects[key]
    with pytest.raises(DomainError, match="object_unavailable"):
        store.verify(owner, key, len(data))
    with pytest.raises(DomainError, match="not_found"):
        store.verify(uuid4(), key, len(data))  # Another owner's prefix.


def test_stream_yields_only_the_requested_range_without_holding_the_object() -> None:
    bucket = Bucket()
    data = bytes(range(256)) * (32 * 1024)  # 8 MiB
    owner, key = stored(bucket, data)
    store = storage(bucket)
    assert b"".join(store.stream(key, 100, 70000)) == data[100:70001]
    tracemalloc.start()
    checksum, largest = hashlib.sha256(), 0
    for chunk in store.stream(key, 0, len(data) - 1):
        checksum.update(chunk)
        largest = max(largest, len(chunk))
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert checksum.hexdigest() == key.rsplit("/", 1)[1] and largest <= CHUNK
    assert peak < 1024**2  # Far below the 8 MiB object: nothing accumulates.
    assert all(body.closed for body in bucket.bodies)
    with pytest.raises(DomainError, match="not_found"):
        list(store.stream("media/../x", 0, 1))
    with pytest.raises(DomainError, match="not_found"):
        list(store.stream(key, 5, 4))


def test_concurrent_verification_is_limited() -> None:
    bucket = Bucket()
    owner, key = stored(bucket, b"x" * 100)
    store = storage(bucket)
    assert store.verifying.acquire(blocking=False) and store.verifying.acquire(blocking=False)
    store.WAIT = 0.01
    with pytest.raises(DomainError, match="retrieval_busy"):
        store.verify(owner, key, 100)
    assert bucket.gets == 0


@pytest.mark.parametrize(
    ("phase", "cause", "code", "transient"),
    [
        (
            "extraction",
            ArchitectureError("parser_isolation_unavailable"),
            "extraction__parser_isolation_unavailable",
            False,
        ),
        (
            "extraction",
            DomainError("object_unavailable", 503),
            "extraction__object_unavailable",
            True,
        ),
        ("rendering", DomainError("encode_failed"), "rendering__encode_failed", False),
        ("rendering", RuntimeError("unexpected"), "rendering__failure", True),
    ],
)
def test_architecture_failures_name_their_phase(
    phase: str, cause: Exception, code: str, transient: bool
) -> None:
    error = ArchitecturePhase(phase, cause)
    assert (error.code, error.transient) == (code, transient)
    assert len(error.code) <= 64 and error.code.replace("_", "").isalnum()


def test_handoff_isolates_one_job_failure_from_the_rest() -> None:
    class Engine:
        def begin(self) -> Any:
            raise AssertionError("not used")

    service = MediaJobs.__new__(MediaJobs)
    waiting = [
        {"o_job": uuid4(), "o_owner": uuid4(), "o_analysis": uuid4()},
        {"o_job": uuid4(), "o_owner": uuid4(), "o_analysis": uuid4()},
        {"o_job": uuid4(), "o_owner": uuid4(), "o_analysis": uuid4()},
    ]
    seen: list[Any] = []

    def sync(owner: Any, job: dict[str, Any]) -> bool:
        seen.append((owner, job["id"], job["analysis_job_id"], job["state"]))
        if job["id"] == waiting[0]["o_job"]:
            raise RuntimeError("core database unavailable")
        return job["id"] == waiting[2]["o_job"]

    service.sync = sync  # type: ignore[method-assign]
    service._waiting = lambda: waiting  # type: ignore[attr-defined]
    assert service.handoff() == 1
    assert seen == [
        (item["o_owner"], item["o_job"], item["o_analysis"], "awaiting_analysis")
        for item in waiting
    ]


def test_synthetic_source_serves_a_deterministic_pinned_archive(tmp_path: Path) -> None:
    source = SyntheticSource(FIXTURES)
    repo = repository_url("https://github.com/synthetic/custom_unnamed")
    snapshot = resolve(repo, source)
    assert snapshot.canonical_url == "https://github.com/synthetic/custom_unnamed"
    assert snapshot.commit_sha == source.identifier("custom_unnamed")
    target = io.BytesIO()
    source.download(archive_path(snapshot), target, 1024**2, lambda: None)
    body = target.getvalue()
    assert hashlib.sha1(body, usedforsecurity=False).hexdigest() == snapshot.commit_sha
    assert body == source.archive("custom_unnamed")  # Byte-identical on every build.
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
        names = tar.getnames()
    expected = sorted(
        f"custom_unnamed-synthetic/{p.relative_to(FIXTURES / 'custom_unnamed').as_posix()}"
        for p in (FIXTURES / "custom_unnamed").rglob("*")
        if p.is_file() and "__pycache__" not in p.as_posix()
    )
    assert names[0] == "custom_unnamed-synthetic" and names[1:] == expected
    # A changed directory no longer matches the pinned identifier.
    copy = tmp_path / "source" / "sample"
    copy.mkdir(parents=True)
    (copy / "a.py").write_text("x = 1\n", encoding="utf-8")
    changing = SyntheticSource(tmp_path / "source")
    pinned = changing.identifier("sample")
    (copy / "a.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(AnalysisError, match="repository_identity_changed"):
        changing.download(f"/synthetic/sample/tar.gz/{pinned}", io.BytesIO(), 1024, lambda: None)
    with pytest.raises(AnalysisError, match="archive_download_limit"):
        source.download(archive_path(snapshot), io.BytesIO(), 10, lambda: None)


@pytest.mark.parametrize(
    ("host", "path"),
    [
        ("api.github.com", "/repos/other/custom_unnamed"),
        ("api.github.com", "/repos/synthetic/missing"),
        ("api.github.com", "/repos/synthetic/.."),
        ("api.github.com", "/repos/synthetic/custom_unnamed/contents/x"),
        ("example.com", "/repos/synthetic/custom_unnamed"),
    ],
)
def test_synthetic_source_answers_only_for_its_own_directories(host: str, path: str) -> None:
    with pytest.raises(AnalysisError, match="repository_not_found"):
        SyntheticSource(FIXTURES).get(host, path, 1024)


def test_synthetic_source_is_refused_outside_fixture_mode() -> None:
    base: dict[str, Any] = {
        "environment": "test",
        "dev_auth": True,
        "database_url": "postgresql+psycopg://u:p@localhost/d",
        "session_secret": "s" * 32,
        "storage_access_key": "a",
        "storage_secret_key": "s",
        "synthetic_source_dir": str(FIXTURES),
    }
    with pytest.raises(ValueError, match="fixture mode"):
        Settings(**base, fixtures=False)
    assert Settings(**base, fixtures=True).synthetic_source_dir == str(FIXTURES)
    with pytest.raises(ValueError):
        Settings(**{**base, "environment": "production"}, fixtures=True)
    with pytest.raises(RuntimeError, match="not found"):
        SyntheticSource(FIXTURES / "does-not-exist")

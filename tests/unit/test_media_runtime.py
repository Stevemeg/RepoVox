"""Handoff support, failure classification, bounded retrieval and the synthetic source."""

import hashlib
import io
import json
import tarfile
import tracemalloc
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from repovox.analysis.common import AnalysisError
from repovox.analysis.github import archive_path, repository_url, resolve
from repovox.api.routes import authenticated
from repovox.auth.session import Identity
from repovox.core.config import Settings
from repovox.core.errors import DomainError
from repovox.main import create_app
from repovox.media.architecture import ArchitectureError
from repovox.media.store import CHUNK, MediaStorage, media_key
from repovox.media.worker import ArchitecturePhase
from repovox.services.media_jobs import MediaJobs
from repovox.storage import ObjectRef
from repovox.synthetic_source import SyntheticSource
from repovox.workers import tasks

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
    """The S3 calls retrieval uses, over in-memory objects, with S3 `If-Match` semantics.

    Every stored version has its own quoted ETag. `precondition` is the error code returned
    when `If-Match` names another version; `short` drops that many bytes from each response
    body, as a truncated transfer would; `after_head` runs once a head request has answered.
    """

    def __init__(self, precondition: str = "PreconditionFailed") -> None:
        self.objects: dict[str, bytes] = {}
        self.gets = 0
        self.bodies: list[Body] = []
        self.conditions: list[str | None] = []
        self.precondition, self.short, self.etags = precondition, 0, True
        self.after_head: Any = None

    def etag(self, key: str) -> str:
        return '"' + hashlib.md5(self.objects[key]).hexdigest() + '"'  # noqa: S324

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        head: dict[str, Any] = {"ContentLength": len(self.objects[Key])}
        if self.etags:
            head["ETag"] = self.etag(Key)
        if self.after_head is not None:
            self.after_head()
        return head

    def get_object(
        self,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Range: str,  # noqa: N803
        IfMatch: str | None = None,  # noqa: N803
    ) -> dict[str, Any]:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        self.conditions.append(IfMatch)
        if IfMatch is not None and IfMatch != self.etag(Key):
            raise ClientError({"Error": {"Code": self.precondition}}, "GetObject")
        self.gets += 1
        start, end = (int(part) for part in Range.removeprefix("bytes=").split("-"))
        body = Body(self.objects[Key][start : end + 1 - self.short])
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


def test_retrieval_is_pinned_to_the_verified_version() -> None:
    bucket = Bucket()
    data = bytes(range(256)) * 1024  # 256 KiB: several chunks.
    owner, key = stored(bucket, data)
    store = storage(bucket)
    etag = store.verify(owner, key, len(data))
    assert etag == bucket.etag(key) and store.verified[key] == etag
    assert bucket.conditions == [etag]  # The hashing pass read exactly the version it records.
    assert store.verify(owner, key, len(data)) == etag and bucket.gets == 1  # Remembered.
    assert b"".join(store.stream(key, 0, len(data) - 1, etag=etag)) == data
    assert b"".join(store.stream(key, 70000, 200000, etag=etag)) == data[70000:200001]
    assert bucket.conditions == [etag, etag, etag]  # Every send names the verified version.
    assert store.verified[key] == etag and all(body.closed for body in bucket.bodies)
    assert b"".join(store.stream(key, 0, 9)) == data[:10] and bucket.conditions[-1] is None


@pytest.mark.parametrize("precondition", ["PreconditionFailed", "412"])
def test_a_version_replaced_after_verification_is_refused_and_forgotten(precondition: str) -> None:
    bucket = Bucket(precondition)
    data = bytes(range(256)) * 1024
    owner, key = stored(bucket, data)
    store = storage(bucket)
    etag = store.verify(owner, key, len(data))
    # Same length, different bytes, between the check and the send: a new stored version.
    bucket.objects[key] = bytes(len(data))
    with pytest.raises(DomainError, match="object_corrupt") as refused:
        store.stream(key, 0, len(data) - 1, etag=etag)
    assert refused.value.status == 503 and key not in store.verified
    assert bucket.conditions[-1] == etag and bucket.gets == 1  # Storage sent no new bytes.
    # The next retrieval re-checks the stored object from scratch and refuses it.
    with pytest.raises(DomainError, match="object_corrupt"):
        store.verify(owner, key, len(data))
    assert key not in store.verified and all(body.closed for body in bucket.bodies)
    # Any version other than the named one is refused; a missing object is only unavailable.
    bucket.objects[key] = data
    with pytest.raises(DomainError, match="object_corrupt"):
        store.stream(key, 0, 9, etag=etag + "x")
    del bucket.objects[key]
    with pytest.raises(DomainError, match="object_unavailable"):
        store.stream(key, 0, 9, etag=etag)


def test_truncated_corrupted_or_unversioned_objects_fail_closed() -> None:
    bucket = Bucket()
    data = bytes(range(256)) * 1024
    owner, key = stored(bucket, data)
    store = storage(bucket)
    bucket.etags = False  # Nothing to pin retrieval to.
    with pytest.raises(DomainError, match="object_corrupt"):
        store.verify(owner, key, len(data))
    bucket.etags = True
    bucket.objects[key] = data[:-1]  # Truncated at rest.
    with pytest.raises(DomainError, match="object_corrupt"):
        store.verify(owner, key, len(data))
    bucket.objects[key] = data[:-1] + b"\x00"  # Corrupted at rest, same length.
    with pytest.raises(DomainError, match="object_corrupt"):
        store.verify(owner, key, len(data))
    assert bucket.gets == 1 and key not in store.verified
    bucket.objects[key] = data
    bucket.short = 100  # Truncated in transfer, under the right version.
    with pytest.raises(DomainError, match="object_corrupt"):
        store.verify(owner, key, len(data))
    assert key not in store.verified
    bucket.short = 0
    etag = store.verify(owner, key, len(data))
    bucket.short = 100
    with pytest.raises(DomainError, match="object_corrupt"):
        list(store.stream(key, 0, len(data) - 1, etag=etag))
    assert key not in store.verified and all(body.closed for body in bucket.bodies)


class Connection:
    def __init__(self, database: "Database") -> None:
        self.database = database

    def execute(self, clause: Any, params: dict[str, Any] | None = None) -> "Connection":
        self.found = self.scalar(clause, params)
        return self

    def mappings(self) -> list[dict[str, Any]]:
        return list(self.found or [])

    def scalar(self, clause: Any, params: dict[str, Any] | None = None) -> Any:
        sql, values = " ".join(str(clause).split()), dict(params or {})
        self.database.calls.append((sql, values))
        return self.database.answer(sql, values)


class Database:
    """Records every statement; `answer(sql, params)` supplies what a test's reads return."""

    def __init__(self, answer: Any = None) -> None:
        self.answer = answer or (lambda sql, params: None)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.disposed = False

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        yield Connection(self)

    def dispose(self) -> None:
        self.disposed = True

    def called(self, function: str) -> list[dict[str, Any]]:
        return [params for sql, params in self.calls if f"{function}(" in sql]

    def scopes(self) -> list[str]:
        """Owner of each tenant scope opened, in order."""
        return [params["owner"] for sql, params in self.calls if "set_config" in sql]


Analysis = tuple[dict[str, Any], list[dict[str, Any]]]


def analysis(
    owner: Any,
    job: Any,
    state: str = "failed",
    error: str | None = "phase2_pipeline_boundary",
    ordinals: tuple[int, ...] = (2, 9),
) -> Analysis:
    """One core analysis job and its unexpired artifacts, as its owner's tenant scope reads them."""
    snapshot = uuid4()
    artifacts = []
    for ordinal in ordinals:
        artifact, checksum = uuid4(), hashlib.sha256(f"{job}-{ordinal}".encode()).hexdigest()
        artifacts.append(
            {
                "ordinal": ordinal,
                "id": artifact,
                "checksum": checksum,
                "object_key": ObjectRef(owner, snapshot, job, artifact, checksum, "analysis").key,
                "byte_count": 1000 + ordinal,
            }
        )
    row = {
        "state": state,
        "error_code": error,
        "snapshot_id": snapshot,
        "commit_sha": "a" * 40,
        "metadata": {"repository": "https://github.com/synthetic/sample"},
    }
    return row, artifacts


def core(analyses: dict[Any, Analysis]) -> Database:
    def answer(sql: str, params: dict[str, Any]) -> Any:
        if "FROM generation_jobs" in sql:
            found = analyses.get(params["id"])
            return [found[0]] if found else []
        if "FROM knowledge_artifacts" in sql:
            return analyses[params["id"]][1]
        return None

    return Database(answer)


def reference(owner: Any, job: Any, found: Analysis) -> dict[str, Any]:
    row, (archive, verify) = found[0], found[1]
    return {
        "owner_id": str(owner),
        "analysis_job_id": str(job),
        "snapshot_id": str(row["snapshot_id"]),
        "commit_sha": "a" * 40,
        "repository": "https://github.com/synthetic/sample",
        "archive": {"artifact": str(archive["id"]), "checksum": archive["checksum"], "bytes": 1002},
        "verify": {"artifact": str(verify["id"]), "checksum": verify["checksum"], "bytes": 1009},
    }


CORE_URL = "postgresql+psycopg://rv_app:p@localhost/repovox"
MEDIA_URL = "postgresql+psycopg://rvm_app:p@localhost/repovox_media"


@pytest.fixture
def worker_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """A worker-process environment, with video off until a test turns it on."""
    for name in ("VIDEO", "MEDIA_DATABASE_URL", "SYNTHETIC_SOURCE_DIR", "FIXTURES", "ORIGIN"):
        monkeypatch.delenv(f"REPOVOX_{name}", raising=False)
    for name, value in {
        "ENVIRONMENT": "test",
        "DEV_AUTH": "true",
        "DATABASE_URL": CORE_URL,
        "SESSION_SECRET": "s" * 32,
        "STORAGE_ACCESS_KEY": "a",
        "STORAGE_SECRET_KEY": "s",
    }.items():
        monkeypatch.setenv(f"REPOVOX_{name}", value)
    tasks.media_handoff_service.cache_clear()
    yield monkeypatch
    tasks.media_handoff_service.cache_clear()


@pytest.mark.parametrize(("video", "media"), [("true", None), ("false", MEDIA_URL)])
def test_worker_handoff_is_a_no_op_without_video_settings(
    worker_settings: pytest.MonkeyPatch, video: str, media: str | None
) -> None:
    def refuse(*args: Any) -> None:
        raise AssertionError("nothing may connect")

    worker_settings.setattr(tasks, "make_engine", refuse)
    worker_settings.setattr("repovox.media.worker.make_media_engine", refuse)
    worker_settings.setenv("REPOVOX_VIDEO", video)
    if media is not None:
        worker_settings.setenv("REPOVOX_MEDIA_DATABASE_URL", media)
    assert tasks.media_handoff() == 0 and tasks.media_handoff_service() is None
    tasks.close_media_handoff()  # Nothing was opened, so nothing is closed.


def test_worker_handoff_advances_waiting_jobs_without_an_api_process(
    worker_settings: pytest.MonkeyPatch,
) -> None:
    alex, sam = uuid4(), uuid4()
    ready, doomed, pending = (uuid4(), uuid4()), (uuid4(), uuid4()), (uuid4(), uuid4())
    analyses = {
        ready[1]: analysis(alex, ready[1]),
        doomed[1]: analysis(sam, doomed[1], error="archive_download_limit"),
        pending[1]: analysis(sam, pending[1], state="running", error=None),
    }
    analysis_db = core(analyses)
    waiting = [
        {"o_job": job, "o_owner": owner, "o_analysis": source}
        for owner, (job, source) in ((alex, ready), (sam, doomed), (sam, pending))
    ]
    media_db = Database(lambda sql, params: waiting if "mv.awaiting()" in sql else None)
    built: list[str] = []
    checked: list[tuple[Any, str]] = []

    def make_engine(url: str) -> Database:
        built.append(url)
        return analysis_db

    def make_media_engine(url: str, role: str) -> Database:
        checked.append((url, role))
        return media_db

    worker_settings.setattr(tasks, "make_engine", make_engine)
    worker_settings.setattr(tasks, "verify_role", lambda e, role: checked.append((e, role)))
    worker_settings.setattr("repovox.media.worker.make_media_engine", make_media_engine)
    worker_settings.setenv("REPOVOX_VIDEO", "true")
    worker_settings.setenv("REPOVOX_MEDIA_DATABASE_URL", MEDIA_URL)

    assert tasks.media_handoff() == 2
    # Both existing roles were confirmed before anything was read or written.
    assert built == [CORE_URL] and checked == [(analysis_db, "rv_app"), (MEDIA_URL, "rvm_app")]
    attached = media_db.called("mv.attach")
    assert [item["id"] for item in attached] == [ready[0]]
    assert json.loads(attached[0]["reference"]) == reference(alex, ready[1], analyses[ready[1]])
    assert media_db.called("mv.analysis_failed") == [{"id": doomed[0]}]
    # Each job's analysis was read only inside its own owner's tenant scope.
    assert analysis_db.scopes() == [str(alex), str(sam), str(sam)]
    assert media_db.scopes() == [str(alex), str(sam)]
    # The next pass reuses the checked connections; the still-running analysis keeps waiting.
    waiting[:] = waiting[2:]
    assert tasks.media_handoff() == 0 and len(built) == 1
    assert [len(media_db.called(name)) for name in ("mv.attach", "mv.analysis_failed")] == [1, 1]
    tasks.close_media_handoff()
    assert analysis_db.disposed and media_db.disposed
    assert tasks.media_handoff_service.cache_info().currsize == 0


def test_worker_handoff_refuses_a_core_role_other_than_the_api_role(
    worker_settings: pytest.MonkeyPatch,
) -> None:
    analysis_db = Database()

    def verify_role(engine: Any, expected: str) -> None:
        raise RuntimeError("Unsafe database role")  # e.g. the rv_worker URL

    def make_media_engine(url: str, role: str) -> Database:
        raise AssertionError("the media database is not opened after a refused core role")

    worker_settings.setattr(tasks, "make_engine", lambda url: analysis_db)
    worker_settings.setattr(tasks, "verify_role", verify_role)
    worker_settings.setattr("repovox.media.worker.make_media_engine", make_media_engine)
    worker_settings.setenv("REPOVOX_VIDEO", "true")
    worker_settings.setenv("REPOVOX_MEDIA_DATABASE_URL", MEDIA_URL)
    with pytest.raises(RuntimeError, match="Unsafe database role"):
        tasks.media_handoff()
    # Released, not remembered: the dispatcher logs it and the next loop tries afresh.
    assert analysis_db.disposed and analysis_db.calls == []
    assert tasks.media_handoff_service.cache_info().currsize == 0


def video_app(bucket: Bucket, owner: Any, key: str, size: int) -> tuple[TestClient, MediaJobs]:
    """The real retrieval routes and `MediaJobs.video`, over a recorded database and bucket."""
    settings = Settings(
        environment="test",
        dev_auth=True,
        analysis=True,
        video=True,
        database_url="postgresql+psycopg://u:p@localhost/core",
        media_database_url="postgresql+psycopg://u:p@localhost/media",
        session_secret="s" * 32,
        storage_access_key="a",
        storage_secret_key="s",
    )
    app = create_app(settings)  # Not entered, so nothing connects.
    service = app.state.media
    record = {
        "id": uuid4(),
        "category": "walkthrough",
        "title": "Walkthrough",
        "object_key": key,
        "checksum": key.rsplit("/", 1)[1],
        "byte_count": size,
        "captions": "WEBVTT\n",
    }
    service.engine = Database(lambda sql, params: [dict(record)] if "media_videos" in sql else None)
    service._storage = storage(bucket)
    app.dependency_overrides[authenticated] = lambda: Identity(owner, uuid4(), "", "n", "e")
    return TestClient(app), service


@pytest.mark.parametrize("route", ["", "/download"])
def test_retrieval_routes_send_only_the_verified_version(route: str) -> None:
    bucket = Bucket()
    data = bytes(range(256)) * 1024
    owner, key = stored(bucket, data)
    client, service = video_app(bucket, owner, key, len(data))
    path = f"/v1/video-jobs/{uuid4()}/videos/{uuid4()}{route}"
    sent = client.get(path)
    assert sent.status_code == 200 and sent.content == data
    etag = bucket.etag(key)
    assert bucket.conditions == [etag, etag]  # The hashing pass, then the send.
    if not route:
        ranged = client.get(path, headers={"range": "bytes=70000-200000"})
        assert ranged.status_code == 206 and ranged.content == data[70000:200001]
        assert bucket.conditions == [etag, etag, etag]
    # The object is replaced after this request's check and before its send.
    bucket.after_head = lambda: bucket.objects.__setitem__(key, bytes(len(data)))
    refused = client.get(path)
    assert refused.status_code == 503 and refused.json()["error"]["code"] == "object_corrupt"
    assert bucket.conditions[-1] == etag and key not in service.storage.verified
    assert bucket.gets == len(bucket.conditions) - 1  # The replacement was never sent.


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

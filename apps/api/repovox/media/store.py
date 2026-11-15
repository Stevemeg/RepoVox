"""Object storage for media outputs, under a prefix separate from analysis artifacts.

Keys are derived from owner, job, stage and content hash. Every read verifies the hash, so a
database row can only ever name bytes that are exactly what was published.
"""

import hashlib
import itertools
import re
import threading
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from botocore.exceptions import ClientError

from repovox.core.config import Settings
from repovox.core.errors import DomainError
from repovox.storage import ObjectRef, S3Storage

LIMIT = 100 * 1024**2
CHUNK = 64 * 1024
KEY = re.compile(r"media/[a-f0-9-]{36}/[a-f0-9-]{36}/1[0-5]/[a-f0-9-]{36}/[a-f0-9]{64}")
CHANGED = {"PreconditionFailed", "412"}  # Storage no longer holds the pinned version.


def media_key(
    owner: UUID | str, job: UUID | str, ordinal: int, artifact: UUID | str, checksum: str
) -> str:
    key = f"media/{owner}/{job}/{ordinal}/{artifact}/{checksum}"
    if not KEY.fullmatch(key):
        raise DomainError("invalid_object")
    return key


class MediaStorage:
    WAIT = 20.0  # Seconds a retrieval may wait for one of the two verification slots.

    def __init__(self, settings: Settings) -> None:
        self.inner = S3Storage(settings)
        self.client, self.bucket = self.inner.client, self.inner.bucket
        # Retrieval never holds a whole object: hashing and sending both go chunk by chunk.
        # At most two objects are hashed at once; a verified object is remembered by ETag.
        self.verifying = threading.BoundedSemaphore(2)
        self.verified: dict[str, str] = {}
        self.lock = threading.Lock()

    def write(self, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
        checksum = hashlib.sha256(body).hexdigest()
        if not KEY.fullmatch(key) or not key.endswith("/" + checksum) or not 0 < len(body) <= LIMIT:
            raise DomainError("invalid_object")
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            IfNoneMatch="*",
            Metadata={"sha256": checksum},
        )

    def read(self, owner: UUID | str, key: str) -> bytes:
        """Owner-scoped, hash-verified read. The key must belong to that owner's prefix."""
        if not KEY.fullmatch(key) or not key.startswith(f"media/{owner}/"):
            raise DomainError("not_found", 404)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError:
            raise DomainError("object_unavailable", 503) from None
        stream = response["Body"]
        try:
            body: bytes = stream.read(LIMIT + 1)
        finally:
            stream.close()
        if len(body) > LIMIT or hashlib.sha256(body).hexdigest() != key.rsplit("/", 1)[1]:
            raise DomainError("object_corrupt", 503)
        return body

    def verify(self, owner: UUID | str, key: str, size: int) -> str:
        """Confirm the stored bytes still hash to their key, using bounded memory.

        Returns the ETag of the exact stored version that was confirmed. Retrieval passes it
        to `stream`, which then refuses any other version, so the bytes sent are the bytes
        that were checked. Runs once per stored version of an object (remembered by ETag).
        Hashing streams 64 KiB at a time and is limited to two objects at once, so concurrent
        requests cannot make the API hold videos in memory.
        """
        if not KEY.fullmatch(key) or not key.startswith(f"media/{owner}/"):
            raise DomainError("not_found", 404)
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            raise DomainError("object_unavailable", 503) from None
        etag = head.get("ETag")
        if not isinstance(etag, str) or not etag.strip('"'):
            raise DomainError("object_corrupt", 503)  # No version to pin retrieval to.
        if int(head.get("ContentLength", -1)) != size or size > LIMIT:
            raise DomainError("object_corrupt", 503)
        with self.lock:
            if self.verified.get(key) == etag:
                return etag
        if not self.verifying.acquire(timeout=self.WAIT):
            raise DomainError("retrieval_busy", 503)
        try:
            checksum = hashlib.sha256()
            count = 0
            # Pinned too, so the version remembered below is the version that was hashed.
            for chunk in self.stream(key, 0, size - 1, etag):
                checksum.update(chunk)
                count += len(chunk)
            if count != size or checksum.hexdigest() != key.rsplit("/", 1)[1]:
                raise DomainError("object_corrupt", 503)
        finally:
            self.verifying.release()
        with self.lock:
            if len(self.verified) >= 512:
                self.verified.clear()
            self.verified[key] = etag
        return etag

    def stream(self, key: str, start: int, end: int, etag: str | None = None) -> Iterator[bytes]:
        """An inclusive byte range in fixed-size chunks.

        With `etag`, storage serves only that stored version (`If-Match`): any other version
        is refused as `object_corrupt` and forgotten as verified. The request is made and the
        first chunk read before this returns, so a refusal reaches the caller before any
        response has started.
        """
        if not KEY.fullmatch(key) or not 0 <= start <= end < LIMIT:
            raise DomainError("not_found", 404)
        chunks = self._chunks(key, start, end, etag)
        return itertools.chain((next(chunks),), chunks)

    def _chunks(self, key: str, start: int, end: int, etag: str | None) -> Iterator[bytes]:
        span = f"bytes={start}-{end}"
        try:
            if etag is None:
                response = self.client.get_object(Bucket=self.bucket, Key=key, Range=span)
            else:
                response = self.client.get_object(
                    Bucket=self.bucket, Key=key, Range=span, IfMatch=etag
                )
        except ClientError as error:
            if etag is not None and error.response.get("Error", {}).get("Code") in CHANGED:
                self.forget(key)
                raise DomainError("object_corrupt", 503) from None
            raise DomainError("object_unavailable", 503) from None
        body = response["Body"]
        try:
            remaining = end - start + 1
            while remaining > 0:
                chunk = body.read(min(CHUNK, remaining))
                if not chunk:
                    self.forget(key)
                    raise DomainError("object_corrupt", 503)  # Shorter than its record.
                remaining -= len(chunk)
                yield chunk
        finally:
            body.close()

    def forget(self, key: str) -> None:
        """Drop a remembered verification, so the next retrieval hashes the object again."""
        with self.lock:
            self.verified.pop(key, None)

    def delete(self, key: str) -> None:
        if KEY.fullmatch(key):
            self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_job(self, owner: UUID | str, job: UUID | str) -> None:
        prefix = f"media/{UUID(str(owner))}/{UUID(str(job))}/"
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                self.client.delete_object(Bucket=self.bucket, Key=item["Key"])

    def analysis(self, reference: dict[str, Any], which: str) -> bytes:
        """Read an immutable analysis output by identity; the accepted reader checks its hash."""
        item = reference[which]
        ref = ObjectRef(
            UUID(reference["owner_id"]),
            UUID(reference["snapshot_id"]),
            UUID(reference["analysis_job_id"]),
            UUID(item["artifact"]),
            item["checksum"],
            "analysis",
        )
        body = self.inner.read(ref.owner, ref)
        if len(body) != int(item["bytes"]):
            raise DomainError("object_corrupt", 503)
        return body

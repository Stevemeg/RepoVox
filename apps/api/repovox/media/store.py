"""Object storage for media outputs, under a prefix separate from analysis artifacts.

Keys are derived from owner, job, stage and content hash. Every read verifies the hash, so a
database row can only ever name bytes that are exactly what was published.
"""

import hashlib
import re
from typing import Any
from uuid import UUID

from botocore.exceptions import ClientError

from repovox.core.config import Settings
from repovox.core.errors import DomainError
from repovox.storage import ObjectRef, S3Storage

LIMIT = 100 * 1024**2
KEY = re.compile(r"media/[a-f0-9-]{36}/[a-f0-9-]{36}/1[0-5]/[a-f0-9-]{36}/[a-f0-9]{64}")


def media_key(
    owner: UUID | str, job: UUID | str, ordinal: int, artifact: UUID | str, checksum: str
) -> str:
    key = f"media/{owner}/{job}/{ordinal}/{artifact}/{checksum}"
    if not KEY.fullmatch(key):
        raise DomainError("invalid_object")
    return key


class MediaStorage:
    def __init__(self, settings: Settings) -> None:
        self.inner = S3Storage(settings)
        self.client, self.bucket = self.inner.client, self.inner.bucket

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

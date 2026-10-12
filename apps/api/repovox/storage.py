import hashlib
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

import boto3
from botocore.client import Config
from mypy_boto3_s3 import S3Client

from repovox.core.config import Settings
from repovox.core.errors import DomainError


@dataclass(frozen=True)
class ObjectRef:
    owner: UUID
    snapshot: UUID
    job: UUID
    artifact: UUID
    checksum: str
    area: Literal["fixture", "analysis"] = "fixture"

    @property
    def key(self) -> str:
        return (
            f"development/{self.owner}/{self.snapshot}/{self.job}"
            f"/{self.area}/{self.artifact}/{self.checksum}"
        )


class ObjectStorage(Protocol):
    def write(self, ref: ObjectRef, body: bytes) -> None: ...
    def read(self, owner: UUID, ref: ObjectRef) -> bytes: ...
    def delete(self, owner: UUID, ref: ObjectRef) -> None: ...


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.storage_bucket
        self.client: S3Client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint,
            aws_access_key_id=settings.storage_access_key.get_secret_value(),
            aws_secret_access_key=settings.storage_secret_key.get_secret_value(),
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
                connect_timeout=3,
                read_timeout=5,
                retries={"max_attempts": 1},
                s3={"addressing_style": "path"},
            ),
        )

    @staticmethod
    def authorize(owner: UUID, ref: ObjectRef) -> None:
        if owner != ref.owner:
            raise DomainError("not_found", 404)

    def write(self, ref: ObjectRef, body: bytes) -> None:
        maximum = 4096 if ref.area == "fixture" else 100 * 1024**2
        if len(body) > maximum or hashlib.sha256(body).hexdigest() != ref.checksum:
            raise DomainError("invalid_object")
        self.client.put_object(
            Bucket=self.bucket,
            Key=ref.key,
            Body=body,
            ContentType="application/json" if ref.area == "fixture" else "application/octet-stream",
            IfNoneMatch="*",
            Metadata={"sha256": ref.checksum},
        )

    def read(self, owner: UUID, ref: ObjectRef) -> bytes:
        self.authorize(owner, ref)
        response = self.client.get_object(Bucket=self.bucket, Key=ref.key)
        stream = response["Body"]
        try:
            maximum = 4096 if ref.area == "fixture" else 100 * 1024**2
            body = stream.read(maximum + 1)
        finally:
            stream.close()
        if len(body) > maximum or hashlib.sha256(body).hexdigest() != ref.checksum:
            raise DomainError("object_corrupt")
        return body

    def delete(self, owner: UUID, ref: ObjectRef) -> None:
        self.authorize(owner, ref)
        self.client.delete_object(Bucket=self.bucket, Key=ref.key)

    def delete_prefix(self, owner: UUID, snapshot: UUID, job: UUID) -> None:
        prefix = f"development/{owner}/{snapshot}/{job}/"
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                self.client.delete_object(Bucket=self.bucket, Key=item["Key"])

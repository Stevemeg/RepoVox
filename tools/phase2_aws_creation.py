"""One-use native identity capture; uncertain requests are never retried."""

import base64
import hashlib

from tools.phase2_cloud_retention_model import digest, require


def create_version(sdk, registry, operation, slot, payload, generation, now):
    require(type(payload) is bytes and len(payload) <= 1024 * 1024, "synthetic_payload_limit")
    require(
        slot["kind"] == "version" and digest(payload) == slot["request_sha256"], "creation_payload"
    )
    registry.prepare(operation, slot, generation, now)
    registry.dispatch(operation, generation, now)
    response = sdk.call(
        "s3",
        "put_object",
        Bucket=slot["parent"],
        Key=slot["key"],
        Body=payload,
        ExpectedBucketOwner=registry.root["account"],
        ChecksumSHA256=base64.b64encode(hashlib.sha256(payload).digest()).decode(),
    )
    require(response.get("VersionId") not in {None, "null"}, "missing_immutable_version")
    resource = dict(
        kind=slot["kind"],
        parent=slot["parent"],
        key=slot["key"],
        identifier=response["VersionId"],
        account=registry.root["account"],
        region=registry.root["region"],
        request_sha256=slot["request_sha256"],
    )
    return registry.register(operation, resource)


def recover_identity(registry, operation, discovered):
    """Late results register for cleanup only. No automatic creation or reopen.

    Discovery must be exhaustive. Zero/multiple candidates remain unresolved;
    provider settlement still requires separate authenticated evidence.
    """
    require(len(discovered) == 1, "creation_unresolved_or_ambiguous")
    return registry.register(operation, discovered[0])

"""Exact native delete requests. A successful request is never absence proof."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal, TypedDict

from tools.phase2_cloud_retention_model import require

if TYPE_CHECKING:
    from tools.phase2_aws_registry import Registry


class CleanupExecutionResult(TypedDict):
    """Request execution only; never an independent deletion receipt."""

    version: Literal["aws-cleanup-execution-result-1.0"]
    outcome: Literal["INCOMPLETE", "AWAITING_INDEPENDENT_VERIFICATION"]
    lifecycle_state: Literal["CLEANING"]
    generation: int
    operations: int
    requested: int
    incomplete: int
    deletion_verified: Literal[False]


class Cleaner:
    def __init__(self, sdk, registered, fence):
        self.sdk, self.registered, self.fence = sdk, tuple(registered), fence

    def delete(self, resource):
        require(resource in self.registered, "unregistered_delete")
        require(
            (resource.account, resource.region)
            == (self.sdk.boundary.account, self.sdk.boundary.region),
            "delete_boundary",
        )
        resource.arn()  # Refuse unsupported/IAM-unrepresentable profiles.
        self.sdk.authenticate()
        self.fence()  # Durable claim/root/generation check, never an event assertion.
        sdk, identifier = self.sdk, resource.identifier
        if resource.kind == "compute":
            return sdk.call("ec2", "terminate_instances", InstanceIds=[identifier])
        if resource.kind == "volume":
            response = sdk.call("ec2", "describe_volumes", VolumeIds=[identifier])
            require(len(response["Volumes"]) == 1, "volume_identity")
            volume = response["Volumes"][0]
            require(volume["VolumeId"] == identifier, "volume_identity")
            require(volume["State"] == "available" and not volume["Attachments"], "volume_attached")
            self.fence()
            return sdk.call("ec2", "delete_volume", VolumeId=identifier)
        if resource.kind == "snapshot":
            response = sdk.call("ec2", "describe_snapshots", SnapshotIds=[identifier])
            require(len(response["Snapshots"]) == 1, "snapshot_identity")
            snapshot = response["Snapshots"][0]
            require(
                snapshot["SnapshotId"] == identifier and snapshot["OwnerId"] == resource.account,
                "snapshot_owner",
            )
            self.fence()
            return sdk.call("ec2", "delete_snapshot", SnapshotId=identifier)
        args = dict(Bucket=resource.parent, Key=resource.key, ExpectedBucketOwner=resource.account)
        if resource.kind in {"version", "marker"}:
            return sdk.call("s3", "delete_object", **args, VersionId=identifier)
        if resource.kind == "upload":
            # Abort is exact UploadId; parts may still complete concurrently.
            # An independent later inventory must prove settlement/absence.
            return sdk.call("s3", "abort_multipart_upload", **args, UploadId=identifier)
        require(resource.kind == "bucket", "unsupported_delete_kind")
        return sdk.call(
            "s3", "delete_bucket", Bucket=identifier, ExpectedBucketOwner=resource.account
        )


def reconcile(
    cleaner: Cleaner, registry: "Registry", worker: str, clock: Callable[[], int]
) -> CleanupExecutionResult:
    """One bounded request tick; no lifecycle advance or absence verification.

    Provider failures return INCOMPLETE only after durable progress succeeds.
    Lost claims or registry errors propagate instead of returning stale authority.
    Recurrence survives COMPLETE, but this function cannot produce that receipt.
    """
    token = registry.claim(worker, clock())
    outcomes = []
    for resource in cleaner.registered:
        registry.check_claim(token, clock())
        try:
            cleaner.delete(resource)
        except Exception:
            # Never put SDK payloads, source keys, credentials or error text in logs.
            registry.progress(token, resource.commitment, "INCOMPLETE", clock())
            outcomes.append("INCOMPLETE")
        else:
            registry.progress(token, resource.commitment, "REQUESTED", clock())
            outcomes.append("REQUESTED")
    # Also fence empty ticks and expiry/replacement after the last progress write.
    # CLEANING is the lifecycle snapshot validated by this exact generation.
    registry.check_claim(token, clock())
    incomplete = outcomes.count("INCOMPLETE")
    return {
        "version": "aws-cleanup-execution-result-1.0",
        "outcome": "INCOMPLETE" if incomplete else "AWAITING_INDEPENDENT_VERIFICATION",
        "lifecycle_state": "CLEANING",
        "generation": token["generation"],
        "operations": len(outcomes),
        "requested": outcomes.count("REQUESTED"),
        "incomplete": incomplete,
        "deletion_verified": False,
    }


def lambda_handler(event, context):
    """Deployment entry remains closed until separately reviewed live wiring."""
    from tools.phase2_aws_contract import activation_refusal

    activation_refusal()

"""Exact native delete requests. A successful request is never absence proof."""

from tools.phase2_cloud_retention_model import require


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


def reconcile(cleaner, registry, worker, clock):
    """One bounded Lambda-compatible tick. Recurrence survives COMPLETE."""
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
    return {"status": "VERIFYING", "operations": len(outcomes)}


def lambda_handler(event, context):
    """Deployment entry remains closed until separately reviewed live wiring."""
    from tools.phase2_aws_contract import activation_refusal

    activation_refusal()

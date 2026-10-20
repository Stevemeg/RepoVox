"""Synthetic botocore Stubber tests, NEVER real AWS integration/authorization."""

from dataclasses import replace

import pytest
from aws_fixtures import ACCOUNT, BOUNDARY, REGION, Harness, empty_inventory
from botocore.exceptions import ClientError

from tools.phase2_aws_cleanup import Cleaner, lambda_handler
from tools.phase2_aws_contract import SDK, Native, pages
from tools.phase2_aws_inventory import Inventory
from tools.phase2_cloud_retention_model import Refusal


@pytest.mark.parametrize("mode", ["REAL", "AWS", "DEPLOY"])
def test_live_transport_refuses_without_client_construction(mode):
    with pytest.raises(Refusal, match="live_activation_forbidden"):
        SDK({}, BOUNDARY, mode=mode)
    with pytest.raises(Refusal, match="cloud_deployment_not_authorized"):
        lambda_handler({}, None)


@pytest.mark.parametrize(
    "changed",
    [
        dict(account="222222222222"),
        dict(region="us-west-2"),
        dict(identifier="vol-00000000000000002"),
    ],
)
def test_exact_delete_refusal(changed):
    h = Harness(["sts", "ec2"])
    r = Native("volume", ACCOUNT, REGION, "vol-00000000000000001")
    other = replace(r, **changed)
    with pytest.raises(Refusal, match="unregistered_delete"):
        Cleaner(h.sdk, [r], lambda: None).delete(other)
    if "identifier" not in changed:
        with pytest.raises(Refusal, match="delete_boundary"):
            Cleaner(h.sdk, [other], lambda: None).delete(other)
    h.done()


@pytest.mark.parametrize(
    "account,arn",
    [
        ("222222222222", None),
        (ACCOUNT, f"arn:aws:sts::{ACCOUNT}:assumed-role/Cleaner/offline"),
        (ACCOUNT, f"arn:aws:sts::{ACCOUNT}:assumed-role/VerifierOther/offline"),
    ],
)
def test_independent_role_substitution_denied(account, arn):
    h = Harness(["sts"])
    h.auth(account=account, arn=arn)
    with pytest.raises(Refusal, match="authenticated_role"):
        h.sdk.authenticate()
    h.done()


def test_ec2_termination_and_ebs_attachment_race():
    h = Harness(["sts", "ec2"])
    instance = Native("compute", ACCOUNT, REGION, "i-00000000000000001")
    volume = Native("volume", ACCOUNT, REGION, "vol-00000000000000001")
    fences = []
    cleaner = Cleaner(h.sdk, [instance, volume], lambda: fences.append(1))
    h.auth()
    h.expect(
        "ec2",
        "terminate_instances",
        {"TerminatingInstances": []},
        {"InstanceIds": [instance.identifier]},
    )
    cleaner.delete(instance)  # Works even if it was stopped; not a deletion receipt.
    h.auth()
    h.expect(
        "ec2",
        "describe_volumes",
        {
            "Volumes": [
                dict(
                    VolumeId=volume.identifier,
                    State="in-use",
                    Attachments=[dict(InstanceId=instance.identifier)],
                )
            ]
        },
        {"VolumeIds": [volume.identifier]},
    )
    with pytest.raises(Refusal, match="volume_attached"):
        cleaner.delete(volume)
    h.auth()
    h.expect(
        "ec2",
        "describe_volumes",
        {"Volumes": [dict(VolumeId=volume.identifier, State="available", Attachments=[])]},
        {"VolumeIds": [volume.identifier]},
    )
    h.error("ec2", "delete_volume", "VolumeInUse", {"VolumeId": volume.identifier})
    with pytest.raises(ClientError):
        cleaner.delete(volume)  # Late attachment never force-detached.
    h.auth()
    h.expect(
        "ec2",
        "describe_volumes",
        {"Volumes": [dict(VolumeId=volume.identifier, State="available", Attachments=[])]},
        {"VolumeIds": [volume.identifier]},
    )
    h.expect("ec2", "delete_volume", {}, {"VolumeId": volume.identifier})
    cleaner.delete(volume)
    assert len(fences) == 6
    h.done()


@pytest.mark.parametrize(
    "kind,method,idarg",
    [
        ("version", "delete_object", "VersionId"),
        ("marker", "delete_object", "VersionId"),
        ("upload", "abort_multipart_upload", "UploadId"),
    ],
)
def test_s3_native_ids_exact(kind, method, idarg):
    h = Harness(["sts", "s3"])
    resource = Native(kind, ACCOUNT, REGION, "opaque/+==%2F", "synthetic-bucket", "é/+%2F.json")
    h.auth()
    h.expect(
        "s3",
        method,
        {},
        dict(
            Bucket=resource.parent,
            Key=resource.key,
            ExpectedBucketOwner=ACCOUNT,
            **{idarg: resource.identifier},
        ),
    )
    Cleaner(h.sdk, [resource], lambda: None).delete(resource)
    h.done()


def test_s3_pagination_versions_markers_and_uploads():
    h = Harness(["s3"])
    common = dict(Bucket="synthetic-bucket", ExpectedBucketOwner=ACCOUNT)
    h.expect(
        "s3",
        "list_object_versions",
        dict(
            IsTruncated=True,
            Versions=[dict(Key="é/+%2F", VersionId="v/+==")],
            NextKeyMarker="é/+%2F",
            NextVersionIdMarker="v/+==",
        ),
        common,
    )
    h.expect(
        "s3",
        "list_object_versions",
        dict(IsTruncated=False, DeleteMarkers=[dict(Key="é/+%2F", VersionId="marker/+==")]),
        dict(**common, KeyMarker="é/+%2F", VersionIdMarker="v/+=="),
    )
    h.expect(
        "s3",
        "list_multipart_uploads",
        dict(
            IsTruncated=True,
            Uploads=[dict(Key="unregistered", UploadId="opaque/+==")],
            NextKeyMarker="unregistered",
            NextUploadIdMarker="opaque/+==",
        ),
        common,
    )
    h.expect(
        "s3",
        "list_multipart_uploads",
        dict(IsTruncated=False),
        dict(**common, KeyMarker="unregistered", UploadIdMarker="opaque/+=="),
    )
    rows = Inventory(h.sdk).objects("synthetic-bucket")
    assert [(r.kind, r.identifier) for r in rows] == [
        ("version", "v/+=="),
        ("marker", "marker/+=="),
        ("upload", "opaque/+=="),
    ]
    h.done()


@pytest.mark.parametrize(
    "response", [dict(IsTruncated=True), {}, dict(IsTruncated=True, NextKeyMarker="same")]
)
def test_incomplete_s3_inventory_never_empty_proof(response):
    h = Harness(["s3"])
    h.expect(
        "s3",
        "list_object_versions",
        response,
        dict(Bucket="synthetic-bucket", ExpectedBucketOwner=ACCOUNT),
    )
    if response.get("NextKeyMarker"):
        h.expect(
            "s3",
            "list_object_versions",
            response,
            dict(Bucket="synthetic-bucket", ExpectedBucketOwner=ACCOUNT, KeyMarker="same"),
        )
    with pytest.raises(Refusal, match="missing_page|pagination_cycle"):
        Inventory(h.sdk).objects("synthetic-bucket")
    h.done()


def test_complete_inventory_uses_all_services_not_namespace():
    h = Harness(["sts", "ec2", "backup", "rbin", "s3"])
    empty_inventory(h)
    assert Inventory(h.sdk).query() == []
    h.done()


@pytest.mark.parametrize("code", ["AccessDenied", "ServiceUnavailable", "ExpiredToken"])
def test_inventory_permission_or_provider_failure_not_absence(code):
    h = Harness(["sts", "ec2"])
    h.auth()
    h.error("ec2", "describe_instances", code)
    with pytest.raises(ClientError):
        Inventory(h.sdk).query()
    h.done()


def test_snapshot_exact_ownership_and_retained_copy_failure():
    h = Harness(["sts", "ec2"])
    snapshot = Native("snapshot", ACCOUNT, REGION, "snap-00000000000000001")
    cleaner = Cleaner(h.sdk, [snapshot], lambda: None)
    h.auth()
    h.expect(
        "ec2",
        "describe_snapshots",
        {"Snapshots": [dict(SnapshotId=snapshot.identifier, OwnerId="222222222222")]},
        {"SnapshotIds": [snapshot.identifier]},
    )
    with pytest.raises(Refusal, match="snapshot_owner"):
        cleaner.delete(snapshot)
    h.auth()
    h.expect(
        "ec2",
        "describe_snapshots",
        {"Snapshots": [dict(SnapshotId=snapshot.identifier, OwnerId=ACCOUNT)]},
        {"SnapshotIds": [snapshot.identifier]},
    )
    h.error("ec2", "delete_snapshot", "InvalidSnapshot.InUse", {"SnapshotId": snapshot.identifier})
    with pytest.raises(ClientError):
        cleaner.delete(snapshot)
    h.done()


def test_pagination_cycle_and_exhaustion():
    h = Harness(["ec2"])
    h.expect("ec2", "describe_volumes", {"Volumes": [], "NextToken": "same"})
    h.expect("ec2", "describe_volumes", {"Volumes": [], "NextToken": "same"}, {"NextToken": "same"})
    with pytest.raises(Refusal, match="pagination_cycle"):
        list(pages(h.sdk, "ec2", "describe_volumes"))
    h.done()

"""Independent account/region metadata discovery. Never grants cleanup authority."""

from tools.phase2_aws_contract import Native, pages
from tools.phase2_cloud_retention_model import canonical, digest, require

COVERAGE = [
    "compute",
    "volume",
    "snapshot",
    "ami",
    "backup",
    "recycle_rule",
    "recycled_snapshot",
    "recycled_ami",
    "bucket",
    "version",
    "marker",
    "upload",
    "directory_bucket",
    "recycled_volume",
]


class Inventory:
    def __init__(self, sdk):
        self.sdk = sdk

    def query(self):
        sdk, boundary = self.sdk, self.sdk.boundary
        sdk.authenticate()
        found = []

        def add(kind, identifier, parent="", key=""):
            found.append(Native(kind, boundary.account, boundary.region, identifier, parent, key))

        for page in pages(sdk, "ec2", "describe_instances"):
            for reservation in page["Reservations"]:
                require(reservation["OwnerId"] == boundary.account, "inventory_owner")
                for instance in reservation["Instances"]:
                    if instance["State"]["Name"] != "terminated":
                        add("compute", instance["InstanceId"])
        for page in pages(sdk, "ec2", "describe_volumes"):
            for volume in page["Volumes"]:
                add("volume", volume["VolumeId"])
        for page in pages(sdk, "ec2", "describe_snapshots", OwnerIds=[boundary.account]):
            for snapshot in page["Snapshots"]:
                require(snapshot["OwnerId"] == boundary.account, "inventory_owner")
                add("snapshot", snapshot["SnapshotId"], snapshot.get("VolumeId", ""))
        for page in pages(
            sdk,
            "ec2",
            "describe_images",
            Owners=[boundary.account],
            IncludeDeprecated=True,
            IncludeDisabled=True,
        ):
            for image in page["Images"]:
                require(image["OwnerId"] == boundary.account, "inventory_owner")
                add("ami", image["ImageId"])
        for page in pages(sdk, "backup", "list_backup_vaults"):
            for vault in page["BackupVaultList"]:
                for recovery in pages(
                    sdk,
                    "backup",
                    "list_recovery_points_by_backup_vault",
                    BackupVaultName=vault["BackupVaultName"],
                ):
                    for point in recovery["RecoveryPoints"]:
                        add("backup", point["RecoveryPointArn"], vault["BackupVaultArn"])
        for resource_type in ["EBS_SNAPSHOT", "EC2_IMAGE", "EBS_VOLUME"]:
            for page in pages(sdk, "rbin", "list_rules", ResourceType=resource_type):
                for rule in page["Rules"]:
                    add("recycle_rule", rule["Identifier"])
        for method, field, kind, id_field in [
            ("list_snapshots_in_recycle_bin", "Snapshots", "recycled_snapshot", "SnapshotId"),
            ("list_images_in_recycle_bin", "Images", "recycled_ami", "ImageId"),
            ("list_volumes_in_recycle_bin", "Volumes", "recycled_volume", "VolumeId"),
        ]:
            for page in pages(sdk, "ec2", method):
                for resource in page[field]:
                    add(kind, resource[id_field])
        # Enumerate all owned general-purpose buckets, not registered parents.
        for page in pages(sdk, "s3", "list_buckets", token="ContinuationToken", MaxBuckets=1000):
            for bucket in page["Buckets"]:
                name = bucket["Name"]
                location = sdk.call(
                    "s3",
                    "get_bucket_location",
                    Bucket=name,
                    ExpectedBucketOwner=boundary.account,
                )["LocationConstraint"]
                location = {None: "us-east-1", "EU": "eu-west-1"}.get(location, location)
                require(location == boundary.region, "bucket_region_outside_profile")
                add("bucket", name)
                found.extend(self.objects(name))
        for page in pages(sdk, "s3", "list_directory_buckets", token="ContinuationToken"):
            for bucket in page["Buckets"]:
                add("directory_bucket", bucket["Name"])
        require(len({r.commitment for r in found}) == len(found), "duplicate_inventory_row")
        return found

    def objects(self, bucket):
        sdk, boundary = self.sdk, self.sdk.boundary
        found, seen = [], set()
        for method, collections, next_fields in [
            (
                "list_object_versions",
                [("Versions", "version", "VersionId"), ("DeleteMarkers", "marker", "VersionId")],
                [("NextKeyMarker", "KeyMarker"), ("NextVersionIdMarker", "VersionIdMarker")],
            ),
            (
                "list_multipart_uploads",
                [("Uploads", "upload", "UploadId")],
                [("NextKeyMarker", "KeyMarker"), ("NextUploadIdMarker", "UploadIdMarker")],
            ),
        ]:
            kwargs = dict(Bucket=bucket, ExpectedBucketOwner=boundary.account)
            for _ in range(1000):
                response = sdk.call("s3", method, **kwargs)
                for collection, kind, id_field in collections:
                    for item in response.get(collection, []):
                        found.append(
                            Native(
                                kind,
                                boundary.account,
                                boundary.region,
                                item[id_field],
                                bucket,
                                item["Key"],
                            )
                        )
                require(type(response.get("IsTruncated")) is bool, "missing_page_completeness")
                if not response["IsTruncated"]:
                    break
                require(response.get("NextKeyMarker") is not None, "missing_page_marker")
                markers = {
                    dest: response[source]
                    for source, dest in next_fields
                    if response.get(source) is not None
                }
                commitment = digest(canonical([method, markers]))
                require(commitment not in seen, "pagination_cycle")
                seen.add(commitment)
                kwargs.update(markers)
            else:
                require(False, "pagination_limit")
        return found

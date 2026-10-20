"""Offline policy structure and service-signature tests, not effective AWS IAM."""

import hashlib
from dataclasses import replace

import pytest
from aws_fixtures import (
    ACCOUNT,
    ANCHOR,
    BOUNDARY,
    REGION,
    Harness,
    empty_inventory,
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils
from test_aws_registry import registry

from tools.phase2_aws_contract import Native
from tools.phase2_aws_infrastructure import (
    artifacts,
    destructive_policy,
    synthetic_policies,
    templates,
    trust,
)
from tools.phase2_aws_inventory import COVERAGE, Inventory
from tools.phase2_aws_operations import Operations
from tools.phase2_aws_verifier import ALGORITHM, Verifier, accept
from tools.phase2_cloud_retention_model import Refusal, canonical, digest


@pytest.fixture(scope="module")
def service_key():
    # Disposable service fixture key; unrelated to enrolled Windows owner key.
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def signed(key, body):
    return dict(
        body=body,
        signature=key.sign(
            hashlib.sha256(body).digest(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
            utils.Prehashed(hashes.SHA256()),
        ),
    )


def request_fixture(tmp_path, key):
    r, emulator = registry(tmp_path)
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    r.fence(1200)
    token = r.claim("cleaner", 1200)
    emulator.seed("SETTLEMENT", generation=token["generation"], sha256="b" * 64)
    request = r.challenge(1200, BOUNDARY.role, digest(der))
    return r, request, der


def test_independent_inventory_to_kms_service_signature_and_nonce(tmp_path, service_key):
    r, request, der = request_fixture(tmp_path, service_key)
    reader = Harness(["sts", "ec2", "backup", "rbin", "s3"])
    empty_inventory(reader)
    signing_boundary = replace(
        BOUNDARY, account="222222222222", role="arn:aws:iam::222222222222:role/SigningService"
    )
    signer = Harness(["sts", "kms"], signing_boundary)
    signer.auth(
        account="222222222222", arn="arn:aws:sts::222222222222:assumed-role/SigningService/offline"
    )
    expected_body = canonical(
        dict(
            request=request,
            observed_at=1201,
            coverage=COVERAGE,
            exhaustive=True,
            present=[],
            mode="OFFLINE_ONLY",
        )
    )
    envelope = signed(service_key, expected_body)
    key_arn = f"arn:aws:kms:{REGION}:222222222222:key/00000000-0000-0000-0000-000000000001"
    signer.expect(
        "kms",
        "sign",
        dict(Signature=envelope["signature"], KeyId=key_arn, SigningAlgorithm=ALGORITHM),
        dict(
            KeyId=key_arn,
            Message=hashlib.sha256(expected_body).digest(),
            MessageType="DIGEST",
            SigningAlgorithm=ALGORITHM,
        ),
    )
    actual = Verifier(Inventory(reader.sdk), signer.sdk, key_arn, digest(der)).answer(request, 1201)
    result = accept(r, request, actual, der, 1202)
    assert result["status"] == "COMPLETE" and result["real_cloud_proof"] is False
    with pytest.raises(Refusal, match="conditional_transaction"):
        accept(r, request, actual, der, 1203)
    reader.done()
    signer.done()


@pytest.mark.parametrize(
    "change,code",
    [
        ({"observed_at": 1300}, "observation_expired"),
        ({"present": ["a" * 64]}, "protected_resources_remain"),
        ({"coverage": ["volume"]}, "observation_coverage"),
        ({"exhaustive": False}, "observation_coverage"),
    ],
)
def test_forged_expired_partial_or_nonempty_never_complete(tmp_path, service_key, change, code):
    r, request, der = request_fixture(tmp_path, service_key)
    body = canonical(
        dict(
            request=request,
            observed_at=1201,
            coverage=COVERAGE,
            exhaustive=True,
            present=[],
            mode="OFFLINE_ONLY",
        )
        | change
    )
    with pytest.raises(Refusal, match=code):
        accept(r, request, signed(service_key, body), der, 1202)
    assert r.validate()["status"] == "VERIFYING"


def test_forged_signature_and_wrong_root_fail(tmp_path, service_key):
    r, request, der = request_fixture(tmp_path, service_key)
    body = canonical(
        dict(
            request=request,
            observed_at=1201,
            coverage=COVERAGE,
            exhaustive=True,
            present=[],
            mode="OFFLINE_ONLY",
        )
    )
    envelope = signed(service_key, body)
    with pytest.raises(Refusal, match="service_signature"):
        accept(r, request, dict(envelope, body=body + b" "), der, 1202)
    with pytest.raises(Refusal, match="signing_key_binding"):
        accept(r, request, envelope, b"untrusted public key", 1202)
    with pytest.raises(Refusal, match="observation_binding"):
        accept(r, dict(request, root="f" * 64), envelope, der, 1202)


@pytest.mark.parametrize(
    "overrides,expected",
    [
        (
            {
                "describe_volumes": {
                    "Volumes": [
                        {
                            "VolumeId": "vol-00000000000000099",
                            "Attachments": [{"InstanceId": "i-00000000000000001"}],
                            "Tags": [{"Key": "namespace", "Value": "other"}],
                        }
                    ]
                }
            },
            "volume",
        ),
        (
            {
                "describe_snapshots": {
                    "Snapshots": [
                        {
                            "SnapshotId": "snap-00000000000000099",
                            "OwnerId": ACCOUNT,
                            "VolumeId": "vol-00000000000000001",
                            "Tags": [{"Key": "namespace", "Value": "other"}],
                        }
                    ]
                }
            },
            "snapshot",
        ),
        (
            {
                "describe_images": {
                    "Images": [{"ImageId": "ami-00000000000000001", "OwnerId": ACCOUNT}]
                }
            },
            "ami",
        ),
        (
            {
                "list_snapshots_in_recycle_bin": {
                    "Snapshots": [{"SnapshotId": "snap-00000000000000099"}]
                }
            },
            "recycled_snapshot",
        ),
        (
            {
                "list_backup_vaults": {
                    "BackupVaultList": [
                        {
                            "BackupVaultName": "vault",
                            "BackupVaultArn": (
                                f"arn:aws:backup:{REGION}:{ACCOUNT}:backup-vault:vault"
                            ),
                        }
                    ]
                },
                "list_recovery_points_by_backup_vault": {
                    "RecoveryPoints": [
                        {
                            "RecoveryPointArn": (
                                f"arn:aws:backup:{REGION}:{ACCOUNT}:recovery-point:synthetic"
                            )
                        }
                    ]
                },
            },
            "backup",
        ),
    ],
)
def test_foreign_namespace_and_recovery_copies_are_not_omitted(overrides, expected):
    h = Harness(["sts", "ec2", "backup", "rbin", "s3"])
    empty_inventory(h, overrides)
    rows = Inventory(h.sdk).query()
    assert len(rows) == 1 and rows[0].kind == expected
    h.done()


def test_actual_policy_exact_native_authority_and_read_only_wildcards():
    policies = synthetic_policies()
    for statement in policies["cleanup"]["Statement"]:
        assert all("*" not in arn and "?" not in arn for arn in statement["Resource"])
    for statement in policies["verifier"]["Statement"]:
        assert all(
            any(part in action for part in [":Describe", ":List", ":GetBucketLocation"])
            for action in statement["Action"]
        )
    principal = policies["cross-account-trust"]["Statement"][0]
    assert principal["Principal"] == {"AWS": "arn:aws:iam::222222222222:role/RepoVoxCleaner"}
    assert set(principal["Condition"]["StringEquals"]) == {"sts:ExternalId", "aws:PrincipalOrgID"}
    assert principal["Action"] == "sts:AssumeRole"


@pytest.mark.parametrize("key", ["wild*", "wild?", "${aws:username}"])
def test_native_key_cannot_become_iam_wildcard(key):
    resource = Native("version", ACCOUNT, REGION, "native/+==", "synthetic-bucket", key)
    with pytest.raises(Refusal, match="iam_unrepresentable_key"):
        destructive_policy([resource])


def test_version_policies_bind_exact_version_and_snapshot_arn_account():
    version = Native("version", ACCOUNT, REGION, "opaque/+==", "synthetic-bucket", "é/+%2F")
    snapshot = Native("snapshot", ACCOUNT, REGION, "snap-00000000000000001")
    p = destructive_policy([version, snapshot])["Statement"]
    assert p[0]["Condition"]["StringEquals"]["s3:VersionId"] == "opaque/+=="
    assert p[1]["Resource"] == [f"arn:aws:ec2:{REGION}::snapshot/{snapshot.identifier}"]


def test_infrastructure_all_resources_disabled_and_compiler_deterministic():
    for template in templates().values():
        assert template["Parameters"]["DeploymentAuthorized"]["Default"] == "false"
        assert all(r["Condition"] == "Deploy" for r in template["Resources"].values())
        for resource in template["Resources"].values():
            if resource["Type"] == "AWS::Scheduler::Schedule":
                assert resource["Properties"]["State"] == "DISABLED"
    assert artifacts() == artifacts()
    import json
    from pathlib import Path

    for name, body in artifacts().items():
        assert json.loads((Path("infra/aws-retention") / name).read_bytes()) == body


def test_trust_rejects_wildcard_principal():
    with pytest.raises(Refusal, match="exact_trust"):
        trust("arn:aws:iam::222222222222:role/*", "external", "o-synthetic")


def test_health_missing_and_incident_sanitized():
    h = Harness(["cloudwatch", "sns"])
    ops = Operations(
        h.sdk, "unused", "unused", "unused", "unused", "arn:aws:sns:us-east-1:111111111111:incident"
    )
    with pytest.raises(Refusal, match="health_missing_or_stale"):
        ops.health(1000, 1201)
    with pytest.raises(Refusal, match="incident_code"):
        ops.incident("provider error with protected source")
    h.expect(
        "cloudwatch",
        "put_metric_data",
        {},
        dict(
            Namespace="RepoVoxRetention",
            MetricData=[dict(MetricName="LoopProgress", Value=1, Unit="Count")],
        ),
    )
    ops.health(1200, 1201)
    h.expect(
        "sns",
        "publish",
        {},
        dict(
            TopicArn=ops.topic_arn,
            Message=canonical({"root": ANCHOR, "reason": "HEALTH_LOSS"}).decode(),
        ),
    )
    ops.incident("HEALTH_LOSS")
    h.done()

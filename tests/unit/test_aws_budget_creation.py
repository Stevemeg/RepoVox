"""Synthetic cost arithmetic and durable provider-ID creation adapter checks."""

import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
from aws_fixtures import ACCOUNT, REGION, ROOT_BODY, Boundary, Harness, LocalDynamo

from tools.phase2_aws_budget import assess
from tools.phase2_aws_creation import create_version, recover_identity
from tools.phase2_aws_registry import Registry
from tools.phase2_cloud_retention_model import Refusal, canonical, digest


def test_ten_dollars_is_not_proven_by_a_small_subtotal():
    plan = json.loads(Path("docs/operations/aws-synthetic-test-budget.json").read_bytes())
    result = assess(plan)
    assert result["status"] == "BUDGET NOT PROVEN" and result["total_usd"] is None
    assert 0 < result["reference_subtotal_usd"] < 10
    assert len(result["unknown_charges"]) == 9
    assert result["spending_authorized"] is False
    assert plan["limits"]["EBS_volumes"] == 2
    with pytest.raises(Refusal, match="owner_budget_boundary"):
        assess(plan | dict(ceiling_usd=25))


def test_provider_result_commits_before_ack_and_no_create_replay(tmp_path):
    payload = b"SYNTHETIC ONLY"
    root = copy.deepcopy(ROOT_BODY)
    root["creation_slots"][0]["request_sha256"] = digest(payload)
    anchor = digest(canonical(root))
    emulator = LocalDynamo(tmp_path / "intent.sqlite")
    emulator.boundary = Boundary(ACCOUNT, REGION, f"arn:aws:iam::{ACCOUNT}:role/Creator", anchor)
    registry = Registry(emulator, "fixture", root, anchor)
    registry.initialize()
    registry.activate("b" * 64, 1100)
    h = Harness(["s3"], emulator.boundary)
    slot = root["creation_slots"][0]
    h.expect(
        "s3",
        "put_object",
        {"VersionId": "provider/+==%2F"},
        dict(
            Bucket=slot["parent"],
            Key=slot["key"],
            Body=payload,
            ExpectedBucketOwner=ACCOUNT,
            ChecksumSHA256=base64.b64encode(hashlib.sha256(payload).digest()).decode(),
        ),
    )
    result = create_version(h.sdk, registry, "operation-1", slot, payload, 1, 1100)
    assert len(result) == 64 and registry.validate()["outstanding"] == 0
    with pytest.raises(Refusal, match="conditional_transaction"):
        create_version(h.sdk, registry, "operation-1", slot, payload, 1, 1101)
    h.done()
    with pytest.raises(Refusal, match="creation_unresolved_or_ambiguous"):
        recover_identity(registry, "operation-1", [])


def test_inflight_provider_call_returns_after_fence_cleanup_only(tmp_path):
    from test_aws_registry import registry, resource

    r, _ = registry(tmp_path)
    r.prepare("operation-1", ROOT_BODY["creation_slots"][0], 1, 1100)
    r.dispatch("operation-1", 1, 1100)
    # Models revoked credentials/in-flight completion. No absent receipt while
    # unresolved; returned ID is durably registered for cleanup after fencing.
    r.fence(1200)
    recover_identity(r, "operation-1", [resource()])
    assert r.validate()["status"] == "FENCED"
    assert r.validate()["outstanding"] == 0
    with pytest.raises(Refusal):
        r.dispatch("operation-1", 1, 1201)

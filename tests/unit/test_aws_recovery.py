"""Synthetic service failure/restart rehearsal; no cloud infrastructure."""

import pytest
from aws_fixtures import ACCOUNT, ANCHOR, REGION, Harness
from botocore.exceptions import ClientError
from test_aws_registry import registry

from tools.phase2_aws_cleanup import Cleaner, reconcile
from tools.phase2_aws_contract import Native
from tools.phase2_aws_operations import Operations
from tools.phase2_cloud_retention_model import Refusal


def test_scheduler_failure_does_not_disable_independent_reconciliation(tmp_path):
    r, _ = registry(tmp_path)
    h = Harness(["scheduler"])
    ops = Operations(
        h.sdk,
        f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:cleaner",
        f"arn:aws:iam::{ACCOUNT}:role/Scheduler",
        f"arn:aws:sqs:{REGION}:{ACCOUNT}:failures",
        "synthetic",
        f"arn:aws:sns:{REGION}:{ACCOUNT}:incident",
    )
    from botocore.stub import ANY

    h.error(
        "scheduler",
        "create_schedule",
        "ServiceUnavailable",
        dict(
            GroupName="synthetic",
            FlexibleTimeWindow={"Mode": "OFF"},
            State="ENABLED",
            ScheduleExpressionTimezone="UTC",
            Target=ANY,
            Name="expiry-" + ANCHOR[:32],
            ScheduleExpression=ANY,
            ActionAfterCompletion="NONE",
        ),
    )
    with pytest.raises(ClientError):
        ops.schedules(2000)
    # Existing external recurring route is independent; no successful schedule
    # creation is used as an activation receipt. It fences/claims while guest off.
    r.fence(2001)
    token = r.claim("existing-recurring-route", 2001)
    assert token["generation"] == 3
    assert r.root["expires"] == 2000
    h.done()


def test_lambda_crash_after_delete_before_progress_recovers_without_false_success(tmp_path):
    r, _ = registry(tmp_path)
    r.fence(1200)
    h = Harness(["sts", "ec2"])
    instance = Native("compute", ACCOUNT, REGION, "i-00000000000000001")
    h.auth()
    h.expect(
        "ec2",
        "terminate_instances",
        {"TerminatingInstances": []},
        {"InstanceIds": [instance.identifier]},
    )
    cleaner = Cleaner(h.sdk, [instance], lambda: None)
    original = r.progress

    def interrupted(*args, **kwargs):
        raise TimeoutError("synthetic Lambda interruption")

    r.progress = interrupted
    with pytest.raises(TimeoutError):
        reconcile(cleaner, r, "lambda-one", lambda: 1200)
    r.progress = original
    assert r.validate()["status"] == "CLEANING"
    with pytest.raises(Refusal):
        r.claim("too-soon", 1201)
    h.auth()
    h.expect(
        "ec2",
        "terminate_instances",
        {"TerminatingInstances": []},
        {"InstanceIds": [instance.identifier]},
    )
    result = reconcile(cleaner, r, "lambda-recovery", lambda: 1246)
    assert result["outcome"] == "AWAITING_INDEPENDENT_VERIFICATION"
    assert result["lifecycle_state"] == r.validate()["status"] == "CLEANING"
    assert result["requested"] == 1 and result["incomplete"] == 0
    assert result["deletion_verified"] is False
    # Only independent signed emptiness can complete. No canary or SDK success.
    assert r.validate()["status"] != "COMPLETE"
    h.done()


@pytest.mark.parametrize("code", ["AccessDenied", "RequestLimitExceeded", "ServiceUnavailable"])
def test_credential_revocation_provider_outage_remains_incomplete(tmp_path, code):
    r, _ = registry(tmp_path)
    r.fence(1200)
    h = Harness(["sts", "ec2"])
    instance = Native("compute", ACCOUNT, REGION, "i-00000000000000001")
    h.auth()
    h.error("ec2", "terminate_instances", code, {"InstanceIds": [instance.identifier]})
    result = reconcile(Cleaner(h.sdk, [instance], lambda: None), r, "cleanup", lambda: 1200)
    assert result["outcome"] == "INCOMPLETE"
    assert result["lifecycle_state"] == r.validate()["status"] == "CLEANING"
    assert result["requested"] == 0 and result["incomplete"] == result["operations"] == 1
    assert result["deletion_verified"] is False
    assert "status" not in result  # No ambiguous lifecycle/result alias.
    h.done()


@pytest.mark.parametrize("fail_first", [True, False])
def test_partial_provider_failure_cannot_be_hidden_by_success(tmp_path, fail_first):
    import json
    import sqlite3

    r, emulator = registry(tmp_path)
    original_root = r.get("ROOT")
    r.fence(1200)
    h = Harness(["sts", "ec2"])
    resources = [Native("compute", ACCOUNT, REGION, f"i-{number:017x}") for number in [1, 2]]
    for index, resource in enumerate(resources):
        h.auth()
        args = {"InstanceIds": [resource.identifier]}
        if (index == 0) == fail_first:
            h.error("ec2", "terminate_instances", "AccessDenied", args)
        else:
            h.expect("ec2", "terminate_instances", {"TerminatingInstances": []}, args)
    result = reconcile(Cleaner(h.sdk, resources, lambda: None), r, "partial", lambda: 1200)
    assert result["outcome"] == "INCOMPLETE"
    assert result["operations"] == 2 and result["requested"] == result["incomplete"] == 1
    assert result["deletion_verified"] is False
    assert result["lifecycle_state"] == r.validate()["status"] == "CLEANING"
    assert r.get("ROOT") == original_root
    with sqlite3.connect(emulator.path) as db:
        durable = [
            json.loads(body)["status"]
            for (body,) in db.execute("SELECT body FROM items WHERE sk LIKE 'PROGRESS#%'")
        ]
    assert sorted(durable) == ["INCOMPLETE", "REQUESTED"]
    h.done()


def test_successful_requests_await_independent_absence_not_deletion_success(tmp_path):
    r, _ = registry(tmp_path)
    r.fence(1200)
    h = Harness(["sts", "ec2"])
    resource = Native("compute", ACCOUNT, REGION, "i-00000000000000001")
    h.auth()
    h.expect(
        "ec2",
        "terminate_instances",
        {"TerminatingInstances": []},
        {"InstanceIds": [resource.identifier]},
    )
    result = reconcile(Cleaner(h.sdk, [resource], lambda: None), r, "cleanup", lambda: 1200)
    assert result == {
        "version": "aws-cleanup-execution-result-1.0",
        "outcome": "AWAITING_INDEPENDENT_VERIFICATION",
        "lifecycle_state": "CLEANING",
        "generation": 3,
        "operations": 1,
        "requested": 1,
        "incomplete": 0,
        "deletion_verified": False,
    }
    assert r.validate()["status"] == result["lifecycle_state"]
    with pytest.raises(Refusal, match="write_settlement_unproven"):
        r.challenge(1201, r.root["verifier_role"], r.root["signing_key_sha256"])
    h.done()


@pytest.mark.parametrize("expiry_point", ["before_request", "after_progress", "empty_tick"])
def test_stale_cleanup_claim_never_returns_an_execution_result(tmp_path, expiry_point):
    r, _ = registry(tmp_path)
    r.fence(1200)
    h = Harness(["sts", "ec2"])
    resource = Native("compute", ACCOUNT, REGION, "i-00000000000000001")
    resources = [] if expiry_point == "empty_tick" else [resource]
    if expiry_point == "after_progress":
        h.auth()
        h.expect(
            "ec2",
            "terminate_instances",
            {"TerminatingInstances": []},
            {"InstanceIds": [resource.identifier]},
        )
        ticks = iter([1200, 1200, 1200, 1246])
    else:
        ticks = iter([1200, 1246])
    with pytest.raises(Refusal, match="stale_claim"):
        reconcile(Cleaner(h.sdk, resources, lambda: None), r, "stale", lambda: next(ticks))
    assert r.validate()["status"] == "CLEANING"
    h.done()


def test_empty_tick_does_not_claim_absence(tmp_path):
    r, _ = registry(tmp_path)
    r.fence(1200)
    h = Harness([])
    result = reconcile(Cleaner(h.sdk, [], lambda: None), r, "empty", lambda: 1200)
    assert result["outcome"] == "AWAITING_INDEPENDENT_VERIFICATION"
    assert result["operations"] == result["requested"] == result["incomplete"] == 0
    assert result["deletion_verified"] is False
    assert result["lifecycle_state"] == r.validate()["status"] == "CLEANING"


def test_execution_fence_stale_after_provider_request(tmp_path):
    r, _ = registry(tmp_path)
    r.fence(1200)
    old = r.claim("old", 1200)
    r.claim("new-after-timeout", 1246)
    with pytest.raises(Refusal, match="stale_claim"):
        r.progress(old, "a" * 64, "REQUESTED", 1247)
    assert r.validate()["status"] != "COMPLETE"


def test_stub_removal_cannot_contact_real_endpoint():
    h = Harness(["sts"])
    h.stubs["sts"].deactivate()
    # SDK's own guard fires before any DNS/TLS/request transmission.
    with pytest.raises(Refusal, match="offline_network_forbidden"):
        h.sdk.authenticate()

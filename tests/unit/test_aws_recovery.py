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
    assert result["status"] == "VERIFYING"
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
    assert result["status"] == "VERIFYING" and r.validate()["status"] == "CLEANING"
    h.done()


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

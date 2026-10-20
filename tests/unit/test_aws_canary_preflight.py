"""Offline proposal checks only; these are not AWS IAM authorization tests."""

import copy
import inspect
import json
from pathlib import Path

import pytest

from tools.phase2_aws_canary import LIMITS, request_plan, templates, validate_binding
from tools.phase2_cloud_retention_model import Refusal


def binding():
    return dict(
        profile="IAM_STS_ONLY",
        limits=copy.deepcopy(LIMITS),
        workload_account="111111111111",
        security_account="222222222222",
        management_account="333333333333",
        primary_region="us-east-1",
        secondary_region="us-west-2",
        namespace="a" * 16,
        external_id="b" * 32,
        organization_id="o-synthetic00",
        operator_role="arn:aws:iam::222222222222:role/SyntheticOperator",
        verifier_role="arn:aws:iam::222222222222:role/SyntheticVerifier",
        not_before_utc="2030-01-01T00:00:00Z",
        not_after_utc="2030-01-01T00:30:00Z",
    )


def test_generated_templates_are_disabled_iam_only_and_committed():
    for name, t in templates().items():
        assert json.loads((Path("infra/aws-retention") / name).read_bytes()) == t
        assert t["Parameters"]["DeploymentAuthorized"]["Default"] == "false"
        assert t["Metadata"]["LiveHarness"] == "NOT_IMPLEMENTED"
        assert len(t["Resources"]) == 2
        for resource in t["Resources"].values():
            assert resource["Type"] == "AWS::IAM::Role"
            assert resource["Condition"] == "Deploy"
            assert resource["DeletionPolicy"] == resource["UpdateReplacePolicy"] == "Delete"
            p = resource["Properties"]
            assert len(p["Policies"]) == 1 and p["MaxSessionDuration"] == 3600
            assert "ManagedPolicyArns" not in p


def test_exact_trust_region_and_fixed_time_conditions():
    for t in templates().values():
        assert t["Parameters"]["ApprovedRegion"]["AllowedValues"] == ["us-east-1"]
        for r in t["Resources"].values():
            trust = r["Properties"]["AssumeRolePolicyDocument"]["Statement"]
            assert len(trust) == 1
            assert trust[0]["Action"] == "sts:AssumeRole"
            assert "*" not in json.dumps(trust[0]["Principal"])
            condition = trust[0]["Condition"]
            assert set(condition["StringEquals"]) == {
                "sts:ExternalId",
                "aws:PrincipalOrgID",
                "aws:RequestedRegion",
            }
            assert condition["DateLessThan"] == {"aws:CurrentTime": {"Ref": "NotAfterUtc"}}
            assert condition["DateGreaterThanEquals"] == {
                "aws:CurrentTime": {"Ref": "NotBeforeUtc"},
            }
            for s in r["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]:
                assert s["Condition"]["DateLessThan"] == condition["DateLessThan"]
                assert s["Condition"]["DateGreaterThanEquals"] == condition["DateGreaterThanEquals"]


def test_only_broad_resource_permission_is_read_only_list_roles():
    for t in templates().values():
        for r in t["Resources"].values():
            for s in r["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]:
                assert s["Effect"] == "Allow"
                if s["Resource"] == "*":
                    assert s["Action"] == ["iam:ListRoles"]
                else:
                    assert "*" not in json.dumps(s["Resource"])
                    assert set(s["Action"]) <= {
                        "sts:AssumeRole",
                        "iam:GetRole",
                        "iam:GetRolePolicy",
                        "iam:ListAttachedRolePolicies",
                        "iam:ListRolePolicies",
                    }


@pytest.mark.parametrize(
    "key,value,reason",
    [
        ("workload_account", None, "canary_accounts"),
        ("workload_account", "222222222222", "separate_accounts"),
        ("management_account", "111111111111", "separate_accounts"),
        ("primary_region", "us-west-2", "canary_primary"),
        ("secondary_region", "us-east-1", "canary_secondary"),
        ("namespace", "../unsafe", "canary_namespace"),
        ("organization_id", "o-*", "canary_org"),
        ("external_id", "*" * 32, "canary_external_id"),
        ("operator_role", "arn:aws:iam::111111111111:role/WrongAccount", "canary_operator"),
        ("operator_role", "arn:aws:iam::222222222222:role/*", "canary_operator"),
        (
            "verifier_role",
            "arn:aws:iam::222222222222:role/SyntheticOperator",
            "independent_verifier",
        ),
        ("not_after_utc", "2030-01-01T00:30:01Z", "canary_deadline"),
        ("not_after_utc", "2030-01-01T00:30:00+00:00", "canary_utc"),
        ("profile", "RETENTION", "canary_profile"),
    ],
)
def test_bad_proposed_bindings_refused(key, value, reason):
    b = binding()
    b[key] = value
    with pytest.raises(Refusal, match=reason):
        validate_binding(b)


@pytest.mark.parametrize("key", ["kms_keys", "dynamodb_tables", "ec2_instances", "s3_buckets"])
def test_no_scope_or_paid_resource_expansion(key):
    b = binding()
    b["limits"][key] = 1
    with pytest.raises(Refusal, match="canary_limits"):
        request_plan(b)


def test_request_plan_is_deterministic_and_never_grants_authority():
    b = binding()
    result = request_plan(b)
    assert result == request_plan(b)
    assert result["mode"] == "OFFLINE_ONLY"
    for field in (
        "live_harness_implemented",
        "deployment_authorized",
        "spending_authorized",
        "deletion_verified",
    ):
        assert result[field] is False
    assert len(result["requests"]) == 8
    assert all(r["expected"] == "AccessDenied" for r in result["requests"][3:])
    b["external_id"] = "c" * 32
    assert request_plan(b)["binding_sha256"] != result["binding_sha256"]


def test_unfilled_owner_form_cannot_be_used_as_a_binding():
    proposal = json.loads(Path("docs/operations/aws-control-canary-approval.json").read_bytes())
    assert proposal["limits"] == LIMITS and proposal["maximum_total_usd"] == 10
    assert proposal["status"] == "PENDING_OWNER_AND_INDEPENDENT_REVIEW"
    assert proposal["owner_approval_evidence_sha256"] is None
    assert proposal["maximum_residual_liability_usd"] is None
    with pytest.raises(Refusal, match="canary_accounts"):
        request_plan(proposal)


def test_zero_known_subtotal_is_not_a_complete_ten_dollar_budget():
    costs = json.loads(Path("docs/operations/aws-control-canary-costs.json").read_bytes())
    rows = costs["rows"]
    assert sum(r["known_reference_usd"] for r in rows if r["known_reference_usd"] is not None) == 0
    assert all(r["unknown"] for r in rows if r["known_reference_usd"] is None)
    assert len([r for r in rows if r["known_reference_usd"] is None]) == 5
    assert costs["budget_disposition"] == "BUDGET NOT PROVEN"
    assert costs["tax_operator_failure_inclusive_total_usd"] is None
    assert costs["maximum_residual_liability_usd"] is None
    assert costs["free_tier_or_credits_assumed"] is costs["spending_authorized"] is False


def test_compiler_has_no_transport_credentials_or_deploy_switch():
    from tools import phase2_aws_canary

    source = inspect.getsource(phase2_aws_canary)
    assert "import boto" not in source and "import requests" not in source
    assert "import subprocess" not in source and "import urllib" not in source
    assert 'add_argument("--deploy"' not in source

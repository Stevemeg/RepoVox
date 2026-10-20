"""Offline 30-minute IAM/STS-only canary compiler. No SDK, credentials or deploy path.

The request plan is a proposal, not a live harness. Existing network refusal and
blocked retention handlers are unchanged. Approval fields are deliberately empty.
"""

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from tools.phase2_aws_infrastructure import add, base, policy, statement, sub
from tools.phase2_cloud_retention_model import canonical, digest, require

ROOT = Path(__file__).resolve().parents[1]
VERSION = "aws-control-canary-preflight-1.0"
ROLE_NAMES = {
    "security": ("Caller", "Verifier"),
    "workload": ("Probe", "Audit"),
}
LIMITS = {
    "active_seconds": 1800,
    "teardown_reserve_seconds": 1800,
    "session_seconds": 900,
    "application_requests": 100,
    "iam_roles": 4,
    "inline_policies": 4,
    "cloudformation_stacks": 2,
    "kms_keys": 0,
    "dynamodb_tables": 0,
    "ec2_instances": 0,
    "ebs_volumes": 0,
    "s3_buckets": 0,
    "lambda_functions": 0,
    "schedules": 0,
    "log_groups": 0,
    "alarms": 0,
}


def trust(principal):
    return policy(
        [
            dict(
                Effect="Allow",
                Principal={"AWS": principal},
                Action="sts:AssumeRole",
                Condition={
                    "StringEquals": {
                        "sts:ExternalId": {"Ref": "ExternalId"},
                        "aws:PrincipalOrgID": {"Ref": "OrganizationId"},
                        "aws:RequestedRegion": {"Ref": "ApprovedRegion"},
                    },
                    "DateGreaterThanEquals": {"aws:CurrentTime": {"Ref": "NotBeforeUtc"}},
                    "DateLessThan": {"aws:CurrentTime": {"Ref": "NotAfterUtc"}},
                },
            )
        ]
    )


def arn(account, suffix):
    return sub(f"arn:aws:iam::${{{account}}}:role/rv-canary-${{Namespace}}-{suffix}")


def templates():
    result = {}
    for account, names in ROLE_NAMES.items():
        t = base(f"OFFLINE ONLY: {account} IAM/STS canary, no custody or retention service")
        t["Metadata"].update(Package=VERSION, LiveHarness="NOT_IMPLEMENTED")
        t["Parameters"].update(
            Namespace={"Type": "String", "AllowedPattern": "[a-f0-9]{16}"},
            ExternalId={"Type": "String", "MinLength": 32, "MaxLength": 64},
            OrganizationId={"Type": "String", "AllowedPattern": "o-[a-z0-9]{10,32}"},
            PeerAccount={"Type": "String", "AllowedPattern": "[0-9]{12}"},
            NotBeforeUtc={"Type": "String", "AllowedPattern": "[0-9TZ:-]{20}"},
            NotAfterUtc={"Type": "String", "AllowedPattern": "[0-9TZ:-]{20}"},
        )
        # Proposed primary only. IAM is global; secondary is an STS denial target.
        t["Parameters"]["ApprovedRegion"]["AllowedValues"] = ["us-east-1"]
        if account == "security":
            for name in ("OperatorRoleArn", "VerifierOperatorRoleArn"):
                t["Parameters"][name] = {
                    "Type": "String",
                    "AllowedPattern": r"arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+",
                }
            t["Rules"] = {
                "SeparateOperators": {
                    "Assertions": [
                        {
                            "Assert": {
                                "Fn::Not": [
                                    {
                                        "Fn::Equals": [
                                            {"Ref": "OperatorRoleArn"},
                                            {"Ref": "VerifierOperatorRoleArn"},
                                        ]
                                    }
                                ]
                            },
                            "AssertDescription": "Separate operator identities required",
                        }
                    ]
                }
            }
        for suffix in names:
            own = arn("AWS::AccountId", suffix)
            if account == "security":
                principal = {
                    "Ref": "OperatorRoleArn" if suffix == "Caller" else "VerifierOperatorRoleArn"
                }
                peer = arn("PeerAccount", "Probe" if suffix == "Caller" else "Audit")
                statements = [
                    statement(
                        ["sts:AssumeRole"],
                        peer,
                        Condition={
                            "StringEquals": {
                                "sts:ExternalId": {"Ref": "ExternalId"},
                                "aws:RequestedRegion": {"Ref": "ApprovedRegion"},
                            }
                        },
                    )
                ]
            else:
                principal = arn("PeerAccount", "Caller" if suffix == "Probe" else "Verifier")
                statements = []
            readable = [own]
            if suffix in {"Verifier", "Audit"}:
                readable = [arn("AWS::AccountId", item) for item in names]
                # Enumeration is read-only and never grants cleanup authority.
                statements.append(statement(["iam:ListRoles"], "*"))
                actions = [
                    "iam:GetRole",
                    "iam:GetRolePolicy",
                    "iam:ListRolePolicies",
                    "iam:ListAttachedRolePolicies",
                ]
            else:
                actions = ["iam:GetRole"]
            statements.append(statement(actions, readable))
            for s in statements:
                s.setdefault("Condition", {}).update(
                    DateGreaterThanEquals={"aws:CurrentTime": {"Ref": "NotBeforeUtc"}},
                    DateLessThan={"aws:CurrentTime": {"Ref": "NotAfterUtc"}},
                )
            add(
                t,
                suffix,
                "AWS::IAM::Role",
                {
                    "RoleName": sub(f"rv-canary-${{Namespace}}-{suffix}"),
                    "MaxSessionDuration": 3600,
                    "AssumeRolePolicyDocument": trust(principal),
                    "Policies": [
                        {"PolicyName": "CanaryOnly", "PolicyDocument": policy(statements)}
                    ],
                },
                DeletionPolicy="Delete",
                UpdateReplacePolicy="Delete",
            )
        result[f"canary-{account}.template.json"] = t
    return result


def validate_binding(binding):
    """Validate a proposed offline binding; this never authenticates approval."""
    require(binding["profile"] == "IAM_STS_ONLY", "canary_profile")
    require(binding["limits"] == LIMITS, "canary_limits")
    accounts = [binding[k] for k in ("workload_account", "security_account", "management_account")]
    require(all(re.fullmatch(r"[0-9]{12}", a or "") for a in accounts), "canary_accounts")
    require(len(set(accounts)) == 3, "separate_accounts")
    require(binding["primary_region"] == "us-east-1", "canary_primary")
    require(binding["secondary_region"] == "us-west-2", "canary_secondary")
    require(re.fullmatch(r"[a-f0-9]{16}", binding["namespace"] or ""), "canary_namespace")
    require(re.fullmatch(r"o-[a-z0-9]{10,32}", binding["organization_id"] or ""), "canary_org")
    require(re.fullmatch(r"[a-f0-9]{32}", binding["external_id"] or ""), "canary_external_id")
    for field in ("operator_role", "verifier_role"):
        require(
            re.fullmatch(
                r"arn:aws:iam::" + binding["security_account"] + r":role/[A-Za-z0-9_+=,.@/-]+",
                binding[field] or "",
            ),
            "canary_operator",
        )
    require(binding["operator_role"] != binding["verifier_role"], "independent_verifier")
    for field in ("not_before_utc", "not_after_utc"):
        require(
            re.fullmatch(r"[0-9]{4}(-[0-9]{2}){2}T[0-9]{2}(:[0-9]{2}){2}Z", binding[field] or ""),
            "canary_utc",
        )
    start = datetime.fromisoformat(binding["not_before_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(binding["not_after_utc"].replace("Z", "+00:00"))
    require(end - start == timedelta(seconds=1800), "canary_deadline")


def request_plan(binding):
    validate_binding(binding)
    prefix = "rv-canary-" + binding["namespace"] + "-"
    probe = f"arn:aws:iam::{binding['workload_account']}:role/{prefix}Probe"
    requests = [
        dict(
            case="identity", service="sts", operation="GetCallerIdentity", expected="EXACT_IDENTITY"
        ),
        dict(
            case="positive",
            service="sts",
            operation="AssumeRole",
            role=probe,
            region="us-east-1",
            duration=900,
            expected="ALLOW",
        ),
        dict(
            case="self_read",
            service="iam",
            operation="GetRole",
            role=probe,
            expected="EXACT_ROLE_ID",
        ),
        dict(
            case="wrong_region",
            service="sts",
            operation="AssumeRole",
            role=probe,
            region="us-west-2",
            expected="AccessDenied",
        ),
        dict(
            case="wrong_external_id",
            service="sts",
            operation="AssumeRole",
            role=probe,
            external_id="UNAPPROVED",
            expected="AccessDenied",
        ),
        dict(
            case="wrong_principal",
            service="sts",
            operation="AssumeRole",
            role=probe,
            caller=binding["verifier_role"],
            expected="AccessDenied",
        ),
        dict(
            case="wrong_resource",
            service="iam",
            operation="GetRole",
            role=f"arn:aws:iam::{binding['workload_account']}:role/{prefix}Audit",
            expected="AccessDenied",
        ),
        dict(
            case="after_deadline",
            service="iam",
            operation="GetRole",
            role=probe,
            expected="AccessDenied",
        ),
    ]
    return dict(
        version=VERSION,
        mode="OFFLINE_ONLY",
        live_harness_implemented=False,
        binding_sha256=digest(canonical(binding)),
        requests=requests,
        deletion_verified=False,
        deployment_authorized=False,
        spending_authorized=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare local generated templates")
    parser.add_argument("--write", action="store_true", help="write local disabled templates only")
    args = parser.parse_args()
    for name, body in templates().items():
        path = ROOT / "infra/aws-retention" / name
        text = json.dumps(body, indent=2) + "\n"
        if args.write:
            path.write_text(text, encoding="utf-8", newline="\n")
        if args.check:
            require(path.read_text(encoding="utf-8") == text, "canary_artifact_drift")
    print(
        json.dumps(
            dict(
                version=VERSION,
                mode="OFFLINE_ONLY",
                limits=LIMITS,
                budget="BUDGET NOT PROVEN",
                deployment_authorized=False,
            )
        )
    )


if __name__ == "__main__":
    main()

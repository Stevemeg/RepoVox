"""Deterministic CloudFormation/IAM compiler, disabled by default; no AWS calls.

Run --check to verify committed artifacts. There is intentionally no deploy flag.
Account creation, live policy simulation and activation require separate approval.
"""

import argparse
import json
from pathlib import Path

from tools.phase2_aws_contract import Native
from tools.phase2_cloud_retention_model import require

VERSION = "aws-retention-package-1.0"
ROOT = Path(__file__).resolve().parents[1]


def policy(statements):
    return {"Version": "2012-10-17", "Statement": statements}


def statement(actions, resources, **extra):
    return dict(Effect="Allow", Action=actions, Resource=resources, **extra)


def trust(principal, external_id, organization):
    require(
        principal.startswith("arn:aws:iam::")
        and ":role/" in principal
        and not any(c in principal + external_id + organization for c in "*?"),
        "exact_trust",
    )
    return policy(
        [
            dict(
                Effect="Allow",
                Action="sts:AssumeRole",
                Principal={"AWS": principal},
                Condition={
                    "StringEquals": {
                        "sts:ExternalId": external_id,
                        "aws:PrincipalOrgID": organization,
                    }
                },
            )
        ]
    )


def destructive_policy(resources):
    statements = []
    for r in resources:
        action = {
            "compute": "ec2:TerminateInstances",
            "volume": "ec2:DeleteVolume",
            "snapshot": "ec2:DeleteSnapshot",
            "bucket": "s3:DeleteBucket",
            "version": "s3:DeleteObjectVersion",
            "marker": "s3:DeleteObjectVersion",
            "upload": "s3:AbortMultipartUpload",
        }[r.kind]
        condition = {"StringEquals": {"aws:RequestedRegion": r.region}}
        if r.kind in {"version", "marker"}:
            condition["StringEquals"]["s3:VersionId"] = r.identifier
        statements.append(statement([action], [r.arn()], Condition=condition))
    return policy(statements)


def read_policy(region):
    # These list/describe APIs do not support exact per-resource authorization.
    # Full dedicated account coverage is intentional and grants no mutation.
    return policy(
        [
            statement(
                [
                    "ec2:DescribeInstances",
                    "ec2:DescribeVolumes",
                    "ec2:DescribeSnapshots",
                    "ec2:DescribeImages",
                    "ec2:ListSnapshotsInRecycleBin",
                    "ec2:ListImagesInRecycleBin",
                    "ec2:ListVolumesInRecycleBin",
                    "backup:ListBackupVaults",
                    "backup:ListRecoveryPointsByBackupVault",
                    "rbin:ListRules",
                    "s3:ListAllMyBuckets",
                    "s3express:ListAllMyDirectoryBuckets",
                ],
                "*",
                Condition={"StringEquals": {"aws:RequestedRegion": region}},
            ),
            statement(
                ["s3:GetBucketLocation", "s3:ListBucketVersions", "s3:ListBucketMultipartUploads"],
                "arn:aws:s3:::*",
                Condition={"StringEquals": {"aws:RequestedRegion": region}},
            ),
        ]
    )


def base(description):
    return dict(
        AWSTemplateFormatVersion="2010-09-09",
        Description=description,
        Metadata={"Package": VERSION, "Activation": "REQUIRES_SEPARATE_OWNER_AUTHORIZATION"},
        Parameters={
            "DeploymentAuthorized": {
                "Type": "String",
                "Default": "false",
                "AllowedValues": ["false", "true"],
            },
            "ApprovedAccount": {"Type": "String", "AllowedPattern": "[0-9]{12}"},
            "ApprovedRegion": {"Type": "String"},
            "ApprovalSha256": {"Type": "String", "AllowedPattern": "[a-f0-9]{64}"},
        },
        Conditions={
            "Deploy": {
                "Fn::And": [
                    {"Fn::Equals": [{"Ref": "DeploymentAuthorized"}, "true"]},
                    {"Fn::Equals": [{"Ref": "AWS::AccountId"}, {"Ref": "ApprovedAccount"}]},
                    {"Fn::Equals": [{"Ref": "AWS::Region"}, {"Ref": "ApprovedRegion"}]},
                    {"Fn::Not": [{"Fn::Equals": [{"Ref": "ApprovalSha256"}, "0" * 64]}]},
                ]
            }
        },
        Resources={},
    )


def add(template, name, kind, properties, **extra):
    template["Resources"][name] = dict(
        Type=kind, Condition="Deploy", Properties=properties, **extra
    )


def sub(value):
    return {"Fn::Sub": value}


def role(template, name, assume, permissions):
    add(
        template,
        name,
        "AWS::IAM::Role",
        dict(
            AssumeRolePolicyDocument=assume,
            MaxSessionDuration=3600,
            Policies=[dict(PolicyName="ExactPurpose", PolicyDocument=permissions)],
        ),
    )


def service_trust(service, **conditions):
    entry = dict(Effect="Allow", Principal={"Service": service}, Action="sts:AssumeRole")
    if conditions:
        entry["Condition"] = conditions
    return policy([entry])


def templates():
    security = base("RepoVox security account: immutable metadata and independent cleanup")
    security["Parameters"].update(
        {
            "CodeBucket": {"Type": "String"},
            "CodeKey": {"Type": "String"},
            "CodeVersion": {"Type": "String"},
            "CodeSha256": {"Type": "String"},
            "RegistryBucketName": {"Type": "String"},
            "ExpiryUTC": {"Type": "String"},
            "WorkloadCleanupRole": {"Type": "String"},
            "WorkloadVerifierRole": {"Type": "String"},
            "ExternalId": {"Type": "String", "MinLength": 32},
            "IncidentEndpoint": {"Type": "String"},
            "SecondaryObserverPrincipal": {"Type": "String"},
            "OrganizationId": {"Type": "String"},
        }
    )
    # No account root broadly delegates Sign or registry modification. A separately
    # approved provisioning role must complete least-privilege key administration.
    for name, spec, usage in [
        ("RegistryKey", "SYMMETRIC_DEFAULT", "ENCRYPT_DECRYPT"),
        ("VerifierKey", "RSA_3072", "SIGN_VERIFY"),
    ]:
        add(
            security,
            name,
            "AWS::KMS::Key",
            dict(
                KeySpec=spec,
                KeyUsage=usage,
                PendingWindowInDays=30,
                KeyPolicy=policy(
                    [
                        dict(
                            Effect="Allow",
                            Principal={"AWS": sub("arn:aws:iam::${AWS::AccountId}:root")},
                            Action="kms:*",
                            Resource="*",
                        )
                    ]
                ),
            ),
            DeletionPolicy="Retain",
            UpdateReplacePolicy="Retain",
        )
    add(
        security,
        "Registry",
        "AWS::DynamoDB::Table",
        dict(
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[dict(AttributeName=n, AttributeType="S") for n in ["pk", "sk"]],
            KeySchema=[
                dict(AttributeName="pk", KeyType="HASH"),
                dict(AttributeName="sk", KeyType="RANGE"),
            ],
            SSESpecification=dict(
                SSEEnabled=True, SSEType="KMS", KMSMasterKeyId={"Ref": "RegistryKey"}
            ),
            DeletionProtectionEnabled=True,
            PointInTimeRecoverySpecification=dict(PointInTimeRecoveryEnabled=False),
        ),
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    add(
        security,
        "RegistryArchive",
        "AWS::S3::Bucket",
        dict(
            BucketName={"Ref": "RegistryBucketName"},
            ObjectLockEnabled=True,
            ObjectLockConfiguration=dict(
                ObjectLockEnabled="Enabled",
                Rule=dict(DefaultRetention=dict(Mode="COMPLIANCE", Days=90)),
            ),
            VersioningConfiguration=dict(Status="Enabled"),
            OwnershipControls=dict(Rules=[dict(ObjectOwnership="BucketOwnerEnforced")]),
            PublicAccessBlockConfiguration={
                k: True
                for k in [
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                ]
            },
            BucketEncryption=dict(
                ServerSideEncryptionConfiguration=[
                    dict(
                        ServerSideEncryptionByDefault=dict(
                            SSEAlgorithm="aws:kms", KMSMasterKeyID={"Ref": "RegistryKey"}
                        )
                    )
                ]
            ),
        ),
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    add(security, "Incident", "AWS::SNS::Topic", dict(KmsMasterKeyId="alias/aws/sns"))
    add(
        security,
        "IncidentSubscription",
        "AWS::SNS::Subscription",
        dict(TopicArn={"Ref": "Incident"}, Protocol="https", Endpoint={"Ref": "IncidentEndpoint"}),
    )
    add(
        security,
        "FailureQueue",
        "AWS::SQS::Queue",
        dict(MessageRetentionPeriod=1209600, SqsManagedSseEnabled=True),
    )
    logs_policy = statement(
        ["logs:CreateLogStream", "logs:PutLogEvents"],
        sub("arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/repovox/*:*"),
    )
    registry_policy = statement(
        [
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:ConditionCheckItem",
        ],
        {"Fn::GetAtt": ["Registry", "Arn"]},
    )
    for name in ["Cleanup", "Verifier", "Supervisor"]:
        permissions = [logs_policy, statement(["sns:Publish"], {"Ref": "Incident"})]
        permissions += [statement(["sqs:SendMessage"], {"Fn::GetAtt": ["FailureQueue", "Arn"]})]
        if name == "Cleanup":
            permissions += [
                registry_policy,
                statement(
                    ["sts:AssumeRole"],
                    {"Ref": "WorkloadCleanupRole"},
                    Condition={"StringEquals": {"sts:ExternalId": {"Ref": "ExternalId"}}},
                ),
            ]
        elif name == "Verifier":
            permissions += [
                statement(
                    ["sts:AssumeRole"],
                    {"Ref": "WorkloadVerifierRole"},
                    Condition={"StringEquals": {"sts:ExternalId": {"Ref": "ExternalId"}}},
                ),
                statement(["kms:Sign", "kms:GetPublicKey"], {"Fn::GetAtt": ["VerifierKey", "Arn"]}),
            ]
        else:
            permissions += [
                registry_policy,
                statement(
                    ["cloudwatch:PutMetricData"],
                    "*",
                    Condition={"StringEquals": {"cloudwatch:namespace": "RepoVoxRetention"}},
                ),
            ]
        role(security, name + "Role", service_trust("lambda.amazonaws.com"), policy(permissions))
        add(
            security,
            name + "Logs",
            "AWS::Logs::LogGroup",
            dict(LogGroupName="/repovox/" + name, RetentionInDays=14),
        )
        add(
            security,
            name,
            "AWS::Lambda::Function",
            dict(
                Runtime="python3.12",
                Handler="tools.phase2_aws_cleanup.lambda_handler",
                Role={"Fn::GetAtt": [name + "Role", "Arn"]},
                MemorySize=256,
                Timeout=30,
                ReservedConcurrentExecutions=1,
                Code=dict(
                    S3Bucket={"Ref": "CodeBucket"},
                    S3Key={"Ref": "CodeKey"},
                    S3ObjectVersion={"Ref": "CodeVersion"},
                ),
                Environment=dict(
                    Variables=dict(
                        REPOVOX_ACTIVATION="BLOCKED", APPROVED_CODE_SHA256={"Ref": "CodeSha256"}
                    )
                ),
                LoggingConfig=dict(LogGroup={"Ref": name + "Logs"}),
                DeadLetterConfig=dict(TargetArn={"Fn::GetAtt": ["FailureQueue", "Arn"]}),
            ),
        )
    role(
        security,
        "PrimaryObservationRole",
        policy(
            [
                dict(
                    Effect="Allow",
                    Principal={"AWS": {"Ref": "SecondaryObserverPrincipal"}},
                    Action="sts:AssumeRole",
                    Condition={
                        "StringEquals": {
                            "sts:ExternalId": {"Ref": "ExternalId"},
                            "aws:PrincipalOrgID": {"Ref": "OrganizationId"},
                        }
                    },
                )
            ]
        ),
        policy(
            [
                statement(["dynamodb:GetItem"], {"Fn::GetAtt": ["Registry", "Arn"]}),
                statement(["cloudwatch:GetMetricData"], "*"),
            ]
        ),
    )
    add(security, "ScheduleGroup", "AWS::Scheduler::ScheduleGroup", dict(Name="repovox-retention"))
    role(
        security,
        "ScheduleRole",
        service_trust(
            "scheduler.amazonaws.com",
            StringEquals={"aws:SourceAccount": {"Ref": "AWS::AccountId"}},
            ArnEquals={"aws:SourceArn": {"Fn::GetAtt": ["ScheduleGroup", "Arn"]}},
        ),
        policy(
            [
                statement(
                    ["lambda:InvokeFunction"],
                    [{"Fn::GetAtt": [n, "Arn"]} for n in ["Cleanup", "Supervisor"]],
                ),
                statement(["sqs:SendMessage"], {"Fn::GetAtt": ["FailureQueue", "Arn"]}),
            ]
        ),
    )
    for name, expression, target in [
        ("Expiry", sub("at(${ExpiryUTC})"), "Cleanup"),
        ("Reconcile", "rate(1 minute)", "Cleanup"),
        ("Monitor", "rate(1 minute)", "Supervisor"),
    ]:
        add(
            security,
            name,
            "AWS::Scheduler::Schedule",
            dict(
                GroupName={"Ref": "ScheduleGroup"},
                FlexibleTimeWindow=dict(Mode="OFF"),
                ScheduleExpression=expression,
                ScheduleExpressionTimezone="UTC",
                State="DISABLED",
                Target=dict(
                    Arn={"Fn::GetAtt": [target, "Arn"]},
                    RoleArn={"Fn::GetAtt": ["ScheduleRole", "Arn"]},
                    DeadLetterConfig=dict(Arn={"Fn::GetAtt": ["FailureQueue", "Arn"]}),
                    RetryPolicy=dict(MaximumEventAgeInSeconds=3600, MaximumRetryAttempts=3),
                ),
            ),
        )
    for name, namespace, metric, dimensions in [
        ("HeartbeatMissing", "RepoVoxRetention", "LoopProgress", []),
        (
            "FailuresPresent",
            "AWS/SQS",
            "ApproximateNumberOfMessagesVisible",
            [dict(Name="QueueName", Value={"Fn::GetAtt": ["FailureQueue", "QueueName"]})],
        ),
    ]:
        add(
            security,
            name,
            "AWS::CloudWatch::Alarm",
            dict(
                Namespace=namespace,
                MetricName=metric,
                Dimensions=dimensions,
                Period=60,
                EvaluationPeriods=2,
                Statistic="Sum",
                Threshold=0,
                ComparisonOperator="LessThanOrEqualToThreshold"
                if name == "HeartbeatMissing"
                else "GreaterThanThreshold",
                TreatMissingData="breaching",
                AlarmActions=[{"Ref": "Incident"}],
            ),
        )

    workload = base(
        "RepoVox dedicated workload account: no public ingress or cleanup authority in guest"
    )
    workload["Parameters"].update(
        {
            "UbuntuImage": {"Type": "AWS::EC2::Image::Id"},
            "SecurityCleanupRole": {"Type": "String"},
            "SecurityVerifierRole": {"Type": "String"},
            "OrganizationId": {"Type": "String"},
            "ExternalId": {"Type": "String", "MinLength": 32},
        }
    )
    # IAM cannot express a JSON policy via String substitution. Exact dynamically
    # created IDs are bound in a separately compiled policy artifact after empty
    # destination provisioning; guest has no protected-write activation yet.
    for name, principal in [
        ("CleanupRole", "SecurityCleanupRole"),
        ("VerifierRole", "SecurityVerifierRole"),
    ]:
        assume = policy(
            [
                dict(
                    Effect="Allow",
                    Principal={"AWS": {"Ref": principal}},
                    Action="sts:AssumeRole",
                    Condition={
                        "StringEquals": {
                            "sts:ExternalId": {"Ref": "ExternalId"},
                            "aws:PrincipalOrgID": {"Ref": "OrganizationId"},
                        }
                    },
                )
            ]
        )
        role(workload, name, assume, read_policy({"Ref": "ApprovedRegion"}))
    add(
        workload,
        "Vpc",
        "AWS::EC2::VPC",
        dict(CidrBlock="10.89.0.0/24", EnableDnsSupport=True, EnableDnsHostnames=True),
    )
    add(
        workload,
        "Subnet",
        "AWS::EC2::Subnet",
        dict(VpcId={"Ref": "Vpc"}, CidrBlock="10.89.0.0/26", MapPublicIpOnLaunch=False),
    )
    add(
        workload,
        "Group",
        "AWS::EC2::SecurityGroup",
        dict(
            GroupDescription="No inbound; offline synthetic runtime",
            VpcId={"Ref": "Vpc"},
            SecurityGroupIngress=[],
            SecurityGroupEgress=[
                dict(IpProtocol="tcp", FromPort=443, ToPort=443, CidrIp="10.89.0.0/24")
            ],
        ),
    )
    role(
        workload,
        "RuntimeRole",
        service_trust("ec2.amazonaws.com"),
        policy(
            [
                statement(
                    ["cloudwatch:PutMetricData"],
                    "*",
                    Condition={"StringEquals": {"cloudwatch:namespace": "RepoVoxRetention"}},
                )
            ]
        ),
    )
    add(workload, "Profile", "AWS::IAM::InstanceProfile", dict(Roles=[{"Ref": "RuntimeRole"}]))
    add(
        workload,
        "Runtime",
        "AWS::EC2::Instance",
        dict(
            ImageId={"Ref": "UbuntuImage"},
            InstanceType="t3.micro",
            CreditSpecification=dict(CPUCredits="standard"),
            IamInstanceProfile={"Ref": "Profile"},
            SubnetId={"Ref": "Subnet"},
            SecurityGroupIds=[{"Ref": "Group"}],
            MetadataOptions=dict(
                HttpTokens="required", HttpEndpoint="enabled", HttpPutResponseHopLimit=1
            ),
            BlockDeviceMappings=[
                dict(
                    DeviceName="/dev/sda1",
                    Ebs=dict(
                        VolumeSize=8, VolumeType="gp3", Encrypted=True, DeleteOnTermination=False
                    ),
                )
            ],
            DisableApiTermination=False,
            InstanceInitiatedShutdownBehavior="stop",
        ),
    )
    add(
        workload,
        "Custody",
        "AWS::EC2::Volume",
        dict(
            Size=1,
            VolumeType="gp3",
            Encrypted=True,
            AvailabilityZone={"Fn::GetAtt": ["Runtime", "AvailabilityZone"]},
        ),
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    add(
        workload,
        "CustodyAttachment",
        "AWS::EC2::VolumeAttachment",
        dict(Device="/dev/sdf", InstanceId={"Ref": "Runtime"}, VolumeId={"Ref": "Custody"}),
    )

    monitor = base("RepoVox secondary region independent health-of-monitor")
    monitor["Parameters"].update(
        {
            "ObserverImage": {"Type": "String"},
            "PrimaryReadRole": {"Type": "String"},
            "ExternalId": {"Type": "String", "MinLength": 32},
        }
    )
    add(monitor, "Incident", "AWS::SNS::Topic", dict(KmsMasterKeyId="alias/aws/sns"))
    add(
        monitor,
        "ObserverLogs",
        "AWS::Logs::LogGroup",
        dict(LogGroupName="/repovox/secondary", RetentionInDays=14),
    )
    role(
        monitor,
        "ObserverRole",
        service_trust("lambda.amazonaws.com"),
        policy(
            [
                statement(
                    ["sts:AssumeRole"],
                    {"Ref": "PrimaryReadRole"},
                    Condition={"StringEquals": {"sts:ExternalId": {"Ref": "ExternalId"}}},
                ),
                statement(
                    ["cloudwatch:PutMetricData"],
                    "*",
                    Condition={
                        "StringEquals": {"cloudwatch:namespace": "RepoVoxRetentionSecondary"}
                    },
                ),
                statement(["sns:Publish"], {"Ref": "Incident"}),
                logs_policy,
            ]
        ),
    )
    add(
        monitor,
        "Observer",
        "AWS::Lambda::Function",
        dict(
            PackageType="Image",
            Code=dict(ImageUri={"Ref": "ObserverImage"}),
            Role={"Fn::GetAtt": ["ObserverRole", "Arn"]},
            MemorySize=128,
            Timeout=30,
            ReservedConcurrentExecutions=1,
            Environment=dict(Variables=dict(REPOVOX_ACTIVATION="BLOCKED")),
        ),
    )
    add(monitor, "ScheduleGroup", "AWS::Scheduler::ScheduleGroup", dict(Name="repovox-secondary"))
    role(
        monitor,
        "ScheduleRole",
        service_trust(
            "scheduler.amazonaws.com",
            StringEquals={"aws:SourceAccount": {"Ref": "AWS::AccountId"}},
            ArnEquals={"aws:SourceArn": {"Fn::GetAtt": ["ScheduleGroup", "Arn"]}},
        ),
        policy([statement(["lambda:InvokeFunction"], {"Fn::GetAtt": ["Observer", "Arn"]})]),
    )
    add(
        monitor,
        "Observe",
        "AWS::Scheduler::Schedule",
        dict(
            GroupName={"Ref": "ScheduleGroup"},
            FlexibleTimeWindow=dict(Mode="OFF"),
            ScheduleExpression="rate(1 minute)",
            State="DISABLED",
            Target=dict(
                Arn={"Fn::GetAtt": ["Observer", "Arn"]},
                RoleArn={"Fn::GetAtt": ["ScheduleRole", "Arn"]},
            ),
        ),
    )
    add(
        monitor,
        "MissingProgress",
        "AWS::CloudWatch::Alarm",
        dict(
            Namespace="RepoVoxRetentionSecondary",
            MetricName="PrimaryProgress",
            Period=60,
            EvaluationPeriods=2,
            Statistic="Sum",
            Threshold=0,
            ComparisonOperator="LessThanOrEqualToThreshold",
            TreatMissingData="breaching",
            AlarmActions=[{"Ref": "Incident"}],
        ),
    )
    # Account provisioning is separate from runtime stacks and does not place
    # Organizations authority in either controller. No management-account calls.
    accounts = base(
        "Optional organization account reservation; owner management-account approval required"
    )
    accounts["Parameters"].update(
        {"WorkloadEmail": {"Type": "String"}, "SecurityEmail": {"Type": "String"}}
    )
    for name in ["Workload", "Security"]:
        add(
            accounts,
            name + "Account",
            "AWS::Organizations::Account",
            dict(AccountName="RepoVox-" + name, Email={"Ref": name + "Email"}),
            DeletionPolicy="Retain",
            UpdateReplacePolicy="Retain",
        )
    return {"security": security, "workload": workload, "secondary": monitor, "accounts": accounts}


def synthetic_policies():
    fixture = [
        Native("compute", "111111111111", "us-east-1", "i-00000000000000001"),
        Native("volume", "111111111111", "us-east-1", "vol-00000000000000001"),
    ]
    return {
        "cleanup": destructive_policy(fixture),
        "verifier": read_policy("us-east-1"),
        "cross-account-trust": trust(
            "arn:aws:iam::222222222222:role/RepoVoxCleaner",
            "synthetic-external-id-not-a-secret-0001",
            "o-synthetic123",
        ),
    }


def binding_template(resources):
    """Compile exact IDs only after empty provisioning; no wildcard staging grant."""
    template = base("Exact resource binding; not usable before owner resource approval")
    template["Parameters"]["CleanupRoleName"] = {"Type": "String"}
    add(
        template,
        "ExactCleanupBinding",
        "AWS::IAM::Policy",
        dict(
            PolicyName="RegisteredResourcesOnly",
            Roles=[{"Ref": "CleanupRoleName"}],
            PolicyDocument=destructive_policy(resources),
        ),
    )
    return template


def artifacts():
    sample = [
        Native("compute", "111111111111", "us-east-1", "i-00000000000000001"),
        Native("volume", "111111111111", "us-east-1", "vol-00000000000000001"),
    ]
    return {
        **{f"{k}.template.json": v for k, v in templates().items()},
        "exact-binding.template.json": binding_template(sample),
        **{f"{k}.policy.json": v for k, v in synthetic_policies().items()},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    directory = ROOT / "infra/aws-retention"
    for name, body in artifacts().items():
        path = directory / name
        encoded = (json.dumps(body, indent=2) + "\n").encode()
        if args.check:
            require(path.read_bytes() == encoded, "infrastructure_drift")
        else:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_bytes(encoded)
    print(
        "Offline infrastructure artifacts checked" if args.check else "Disabled artifacts generated"
    )

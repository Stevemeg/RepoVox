"""Schedule/health/incident SDK requests. No scheduler success implies cleanup."""

from datetime import UTC, datetime

from tools.phase2_cloud_retention_model import canonical, digest, require


class Operations:
    def __init__(self, sdk, function_arn, scheduler_role, dlq_arn, group, topic_arn):
        self.sdk, self.function_arn, self.scheduler_role = sdk, function_arn, scheduler_role
        self.dlq_arn, self.group, self.topic_arn = dlq_arn, group, topic_arn

    def schedules(self, expiry):
        # Input contains opaque root only, no source keys/SDK errors or evidence.
        common = dict(
            GroupName=self.group,
            FlexibleTimeWindow={"Mode": "OFF"},
            State="ENABLED",
            ScheduleExpressionTimezone="UTC",
            Target=dict(
                Arn=self.function_arn,
                RoleArn=self.scheduler_role,
                Input=canonical({"root": self.sdk.boundary.root}).decode(),
                DeadLetterConfig={"Arn": self.dlq_arn},
                RetryPolicy={"MaximumEventAgeInSeconds": 3600, "MaximumRetryAttempts": 3},
            ),
        )
        at = datetime.fromtimestamp(expiry, UTC).strftime("%Y-%m-%dT%H:%M:%S")
        self.sdk.call(
            "scheduler",
            "create_schedule",
            **common,
            Name="expiry-" + self.sdk.boundary.root[:32],
            ScheduleExpression=f"at({at})",
            ActionAfterCompletion="NONE",
        )
        self.sdk.call(
            "scheduler",
            "create_schedule",
            **common,
            Name="reconcile-" + self.sdk.boundary.root[:32],
            ScheduleExpression="rate(1 minute)",
            ActionAfterCompletion="NONE",
        )

    def health(self, observed, now):
        require(type(observed) is int and 0 <= now - observed <= 120, "health_missing_or_stale")
        self.sdk.call(
            "cloudwatch",
            "put_metric_data",
            Namespace="RepoVoxRetention",
            MetricData=[dict(MetricName="LoopProgress", Value=1, Unit="Count")],
        )

    def incident(self, reason):
        require(
            reason in {"OVERDUE", "HEALTH_LOSS", "IAM_DENIED", "INVENTORY_INCOMPLETE"},
            "incident_code",
        )
        body = canonical({"root": self.sdk.boundary.root, "reason": reason}).decode()
        self.sdk.call("sns", "publish", TopicArn=self.topic_arn, Message=body)
        return digest(body.encode())

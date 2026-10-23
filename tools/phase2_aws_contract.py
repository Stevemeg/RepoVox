"""AWS integration contracts. No credentials, client construction or live activation.

All transports in this review package are OFFLINE_ONLY. SDK-shaped requests can
be tested without implying that AWS IAM, consistency or physical deletion passed.
"""

import re
from dataclasses import asdict, dataclass

from botocore.validate import validate_parameters
from repovox.sdk_trust import validate_client

from tools.phase2_cloud_retention_model import canonical, digest, require


def offline_network_guard(**kwargs):
    require(False, "offline_network_forbidden")


@dataclass(frozen=True)
class Boundary:
    account: str
    region: str
    role: str
    root: str

    def validate(self):
        require(re.fullmatch(r"[0-9]{12}", self.account), "account")
        require(re.fullmatch(r"[a-z]{2}-[a-z]+-[1-9]", self.region), "region")
        require(
            re.fullmatch(
                r"arn:aws:iam::" + self.account + r":role/[A-Za-z0-9_+=,.@/-]+", self.role
            ),
            "role",
        )
        require(re.fullmatch(r"[a-f0-9]{64}", self.root), "root")


class SDK:
    """Injected, model-validated SDK clients; no ambient credential discovery.

    A stubbed client must have a before-send network refusal installed by the
    harness. This class does not enable live mode. There is no deployment CLI.
    """

    def __init__(self, clients, boundary, *, mode="OFFLINE_ONLY"):
        require(mode == "OFFLINE_ONLY", "live_activation_forbidden")
        boundary.validate()
        self.clients, self.boundary = clients, boundary

    def call(self, service, method, **kwargs):
        client = self.clients[service]
        validate_client(client)
        client.meta.events.register_first("before-send.*.*", offline_network_guard)
        require(client.meta.region_name == self.boundary.region, "client_region")
        require(getattr(client, "_repovox_offline", False) is True, "offline_transport_required")
        operation = client.meta.method_to_api_mapping[method]
        validate_parameters(
            kwargs, client.meta.service_model.operation_model(operation).input_shape
        )
        return getattr(client, method)(**kwargs)

    def authenticate(self):
        caller = self.call("sts", "get_caller_identity")
        role_path = self.boundary.role.split(":role/", 1)[1]
        # STS session ARNs omit an IAM role's path. Compare exact role name and
        # account, never a prefix supplied by an event. Trust policy pins role ARN.
        session = (
            f"arn:aws:sts::{self.boundary.account}:assumed-role/{role_path.rsplit('/', 1)[-1]}/"
        )
        require(
            caller["Account"] == self.boundary.account
            and caller["Arn"].startswith(session)
            and len(caller["Arn"][len(session) :]) > 0,
            "authenticated_role",
        )
        return caller["Arn"]


def pages(sdk, service, method, *, token="NextToken", limit=1000, **kwargs):
    """Bounded complete pagination. Errors/repeated tokens never mean empty."""
    seen = set()
    for _ in range(limit):
        response = sdk.call(service, method, **kwargs)
        yield response
        following = response.get(token)
        if not following:
            return
        require(type(following) is str and following not in seen, "pagination_cycle")
        seen.add(following)
        kwargs[token] = following
    require(False, "pagination_limit")


@dataclass(frozen=True)
class Native:
    kind: str
    account: str
    region: str
    identifier: str
    parent: str = ""
    key: str = ""

    @property
    def commitment(self):
        return digest(canonical(asdict(self)))

    def arn(self):
        if self.kind in {"compute", "volume", "snapshot"}:
            family = {"compute": "instance", "volume": "volume", "snapshot": "snapshot"}[self.kind]
            prefix = {"compute": "i", "volume": "vol", "snapshot": "snap"}[self.kind]
            require(
                re.fullmatch(prefix + r"-(?:[a-f0-9]{8}|[a-f0-9]{17})", self.identifier),
                "native_id",
            )
            account = "" if self.kind == "snapshot" else self.account
            return f"arn:aws:ec2:{self.region}:{account}:{family}/{self.identifier}"
        if self.kind == "bucket":
            require(re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.identifier), "bucket_id")
            return "arn:aws:s3:::" + self.identifier
        require(self.kind in {"version", "marker", "upload"}, "unsupported_delete_kind")
        require(bool(self.identifier) and bool(self.key) and bool(self.parent), "native_object")
        Native("bucket", self.account, self.region, self.parent).arn()
        # IAM wildcard characters are not escaped by JSON. Preserve native IDs,
        # but refuse profiles that cannot compile to an exact IAM resource.
        require(not any(c in self.parent + self.key for c in "*?${}"), "iam_unrepresentable_key")
        require(not any(c in self.identifier for c in "*?${}"), "iam_unrepresentable_id")
        return f"arn:aws:s3:::{self.parent}/{self.key}"


def activation_refusal():
    require(False, "cloud_deployment_not_authorized")

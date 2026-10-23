"""OFFLINE synthetic AWS fixtures. No AWS credential chain or network requests."""

import json
import re
import sqlite3
import threading

from botocore.config import Config
from botocore.stub import Stubber
from repovox.sdk_trust import create_client

from tools.phase2_aws_contract import SDK, Boundary
from tools.phase2_aws_registry import decode, encode
from tools.phase2_cloud_retention_model import Refusal, canonical, digest

ACCOUNT = "111111111111"
REGION = "us-east-1"
ROOT_BODY = dict(
    owner="synthetic-owner",
    attempt="synthetic-attempt",
    manifest_sha256="c" * 64,
    verifier_role="arn:aws:iam::111111111111:role/Verifier",
    signing_key_sha256="a" * 64,
    resources=[],
    account=ACCOUNT,
    region=REGION,
    tenant="synthetic",
    namespace="fixture",
    created=1000,
    expires=2000,
    authorization_expires=1800,
    creation_slots=[
        dict(
            operation="operation-1",
            kind="version",
            parent="synthetic-bucket",
            key="exact/+%2F",
            request_sha256="a" * 64,
        )
    ],
)
ANCHOR = digest(canonical(ROOT_BODY))
ROLE = f"arn:aws:iam::{ACCOUNT}:role/Verifier"
BOUNDARY = Boundary(ACCOUNT, REGION, ROLE, ANCHOR)


def blocked_network(**kwargs):
    raise AssertionError("OFFLINE fixture attempted network access")


class Harness:
    def __init__(self, services, boundary=BOUNDARY):
        self.clients, self.stubs = {}, {}
        for service in services:
            client = create_client(
                service,
                aws_access_key_id="offline",
                aws_secret_access_key="offline",
                region_name=boundary.region,
                endpoint_url="https://offline.invalid",
                config=Config(retries={"max_attempts": 0}),
            )
            client._repovox_offline = True
            client.meta.events.register("before-send.*.*", blocked_network)
            stub = Stubber(client)
            stub.activate()
            self.clients[service], self.stubs[service] = client, stub
        self.sdk = SDK(self.clients, boundary)

    def expect(self, service, method, response, args=None):
        self.stubs[service].add_response(method, response, args or {})

    def error(self, service, method, code, args=None):
        self.stubs[service].add_client_error(
            method, service_error_code=code, expected_params=args or {}
        )

    def auth(self, *, arn=None, account=ACCOUNT):
        role_name = self.sdk.boundary.role.rsplit("/", 1)[-1]
        self.expect(
            "sts",
            "get_caller_identity",
            dict(
                Account=account,
                Arn=arn or f"arn:aws:sts::{ACCOUNT}:assumed-role/{role_name}/offline",
                UserId="synthetic",
            ),
        )

    def done(self):
        for stub in self.stubs.values():
            stub.assert_no_pending_responses()


class LocalDynamo:
    """SQLite-backed emulator of ONLY the expressions this package emits.

    Used for interruption/concurrency proof of protocol expectations. Not IAM,
    DynamoDB isolation, replication, API fault or service availability proof.
    """

    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE items(pk TEXT, sk TEXT, body TEXT, PRIMARY KEY(pk,sk))")
        self.calls = []
        self.fail_after_commit = False

    def row(self, db, key):
        row = db.execute(
            "SELECT body FROM items WHERE pk=? AND sk=?", (key["pk"], key["sk"])
        ).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def condition(db, expression, row, values):
        if expression == "attribute_not_exists(pk)":
            return row is None
        row = row or {}
        expression = expression.replace("#s", "status")
        bindings = {k[1:]: v for k, v in values.items()}
        for name in [
            "status",
            "generation",
            "revision",
            "outstanding",
            "lease_end",
            "worker",
            "consumed",
            "body",
            "health_until",
            "progress",
        ]:
            expression = re.sub(r"(?<![:A-Za-z_])" + name + r"\b", ":old_" + name, expression)
            bindings["old_" + name] = row.get(name)
        return db.execute("SELECT " + expression, bindings).fetchone()[0] == 1

    def call(self, service, method, **kwargs):
        assert service == "dynamodb"
        self.calls.append((method, kwargs))
        with self.lock, sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if method == "get_item":
                row = self.row(db, decode(kwargs["Key"]))
                return {"Item": encode(row)} if row else {}
            assert method == "transact_write_items"
            for operation in kwargs["TransactItems"]:
                kind, request = next(iter(operation.items()))
                item = decode(request.get("Item", request.get("Key")))
                old = self.row(db, item)
                values = json.loads(
                    json.dumps(decode(request.get("ExpressionAttributeValues", {})), default=int)
                )
                if not self.condition(db, request["ConditionExpression"], old, values):
                    raise Refusal("conditional_transaction")
                if kind == "ConditionCheck":
                    continue
                if kind == "Update":
                    item = old.copy()
                    expression = request["UpdateExpression"].replace("#s", "status")
                    parts = re.split(r"\b(SET|ADD)\b", expression)[1:]
                    for action, terms in zip(parts[::2], parts[1::2], strict=True):
                        for term in terms.split(","):
                            if action == "SET":
                                name, key = term.strip().split("=")
                                item[name] = values[key]
                            else:
                                name, key = term.strip().split()
                                item[name] += values[key]
                db.execute(
                    "INSERT OR REPLACE INTO items VALUES(?,?,?)",
                    (item["pk"], item["sk"], json.dumps(item, default=int)),
                )
            db.commit()
            if self.fail_after_commit:
                self.fail_after_commit = False
                raise TimeoutError("synthetic lost acknowledgment")
            return {}

    def seed(self, sk, **fields):
        with sqlite3.connect(self.path) as db:
            anchor = self.boundary.root
            item = dict(pk=anchor, sk=sk, **fields)
            db.execute("INSERT OR REPLACE INTO items VALUES(?,?,?)", (anchor, sk, json.dumps(item)))


def empty_inventory(h, overrides=None):
    overrides = overrides or {}
    original = h.expect

    def expected(service, method, response, args=None):
        original(service, method, overrides.get(method, response), args)

    h.auth()
    expected("ec2", "describe_instances", {"Reservations": []})
    expected("ec2", "describe_volumes", {"Volumes": []})
    expected("ec2", "describe_snapshots", {"Snapshots": []}, {"OwnerIds": [ACCOUNT]})
    expected(
        "ec2",
        "describe_images",
        {"Images": []},
        dict(Owners=[ACCOUNT], IncludeDeprecated=True, IncludeDisabled=True),
    )
    expected("backup", "list_backup_vaults", {"BackupVaultList": []})
    for vault in overrides.get("list_backup_vaults", {}).get("BackupVaultList", []):
        expected(
            "backup",
            "list_recovery_points_by_backup_vault",
            {"RecoveryPoints": []},
            {"BackupVaultName": vault["BackupVaultName"]},
        )
    for resource_type in ["EBS_SNAPSHOT", "EC2_IMAGE", "EBS_VOLUME"]:
        expected("rbin", "list_rules", {"Rules": []}, {"ResourceType": resource_type})
    for method, field in [
        ("list_snapshots_in_recycle_bin", "Snapshots"),
        ("list_images_in_recycle_bin", "Images"),
        ("list_volumes_in_recycle_bin", "Volumes"),
    ]:
        expected("ec2", method, {field: []})
    h.expect("s3", "list_buckets", {"Buckets": []}, {"MaxBuckets": 1000})
    h.expect("s3", "list_directory_buckets", {"Buckets": []})

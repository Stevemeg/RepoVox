"""Conditional DynamoDB protocol requests; original roots are externally anchored.

Transactions here are SDK implementations, not offline proof of DynamoDB isolation.
No TTL, eventually consistent Scan or mutable tag is an authorization boundary.
"""

import json
import re
import secrets

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from tools.phase2_aws_contract import Native
from tools.phase2_cloud_retention_model import canonical, digest, require


def encode(item):
    return {k: TypeSerializer().serialize(v) for k, v in item.items()}


def decode(item):
    return {k: TypeDeserializer().deserialize(v) for k, v in item.items()}


class Registry:
    def __init__(self, sdk, table, root_body, anchor):
        require(digest(canonical(root_body)) == anchor == sdk.boundary.root, "registry_anchor")
        require(
            {
                "owner",
                "tenant",
                "attempt",
                "namespace",
                "manifest_sha256",
                "account",
                "region",
                "created",
                "authorization_expires",
                "expires",
                "resources",
                "creation_slots",
                "verifier_role",
                "signing_key_sha256",
            }
            <= set(root_body),
            "root_binding_fields",
        )
        require(
            all(
                re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", root_body[k])
                for k in ["owner", "tenant", "attempt", "namespace"]
            ),
            "root_identity",
        )
        require(re.fullmatch(r"[a-f0-9]{64}", root_body["manifest_sha256"]), "source_commitment")
        require(
            re.fullmatch(r"[a-f0-9]{64}", root_body["signing_key_sha256"]), "service_key_binding"
        )
        require(
            re.fullmatch(
                r"arn:aws:iam::" + root_body["account"] + r":role/[A-Za-z0-9_+=,.@/-]+",
                root_body["verifier_role"],
            ),
            "service_role_binding",
        )
        require(
            all(type(root_body[k]) is int for k in ["created", "authorization_expires", "expires"]),
            "fixed_deadlines",
        )
        require(
            root_body["created"]
            < root_body["authorization_expires"]
            <= root_body["expires"]
            <= root_body["created"] + 30 * 86400,
            "fixed_deadlines",
        )
        self.sdk, self.table, self.root, self.anchor = sdk, table, root_body, anchor

    def key(self, sk):
        return encode(dict(pk=self.anchor, sk=sk))

    def get(self, sk):
        response = self.sdk.call(
            "dynamodb", "get_item", TableName=self.table, Key=self.key(sk), ConsistentRead=True
        )
        return decode(response["Item"]) if "Item" in response else None

    def put(self, sk, **attributes):
        return {
            "Put": dict(
                TableName=self.table,
                Item=encode(dict(pk=self.anchor, sk=sk, **attributes)),
                ConditionExpression="attribute_not_exists(pk)",
            )
        }

    def transact(self, *items):
        initializing = any(
            "Put" in item and decode(item["Put"]["Item"]).get("sk") == "ROOT" for item in items
        )
        if not initializing:
            items = (
                *items,
                {
                    "ConditionCheck": dict(
                        TableName=self.table,
                        Key=self.key("ROOT"),
                        ConditionExpression="body=:expected",
                        ExpressionAttributeValues=encode(
                            {":expected": canonical(self.root).decode()}
                        ),
                    )
                },
            )
        return self.sdk.call(
            "dynamodb",
            "transact_write_items",
            TransactItems=list(items),
            ClientRequestToken=secrets.token_hex(16),
        )

    def update(self, expression, condition, values):
        return {
            "Update": dict(
                TableName=self.table,
                Key=self.key("STATE"),
                UpdateExpression=expression,
                ConditionExpression=condition,
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues=encode(values),
            )
        }

    def validate(self):
        row = self.get("ROOT")
        require(
            row is not None and row["body"] == canonical(self.root).decode(), "registry_corrupt"
        )
        return self.get("STATE")

    def initialize(self):
        # Root bytes are additionally pinned in owner receipt and immutable S3
        # version. This transaction cannot grant readiness by itself.
        return self.transact(
            self.put("ROOT", body=canonical(self.root).decode()),
            self.put(
                "STATE",
                status="PENDING",
                generation=0,
                revision=0,
                outstanding=0,
                lease_end=0,
                worker="",
                health_until=0,
                progress=0,
            ),
        )

    def activate(self, readiness_sha, now):
        require(len(readiness_sha) == 64, "readiness_commitment")
        self.validate()
        require(now < self.root["authorization_expires"], "authorization_expired")
        # Readiness must be an authenticated external activation receipt in a
        # future live wiring. An offline hash is not a real activation grant.
        return self.transact(
            self.update(
                "SET #s=:active, generation=:one, readiness=:proof, health_until=:health",
                "#s=:pending AND generation=:zero",
                {
                    ":active": "ACTIVE",
                    ":pending": "PENDING",
                    ":zero": 0,
                    ":one": 1,
                    ":proof": readiness_sha,
                    ":health": min(now + 120, self.root["authorization_expires"]),
                },
            )
        )

    def heartbeat(self, generation, progress, now):
        self.validate()
        require(now < self.root["authorization_expires"], "authorization_expired")
        return self.transact(
            self.update(
                "SET progress=:p, health_until=:health",
                "#s=:active AND generation=:g AND progress<:p",
                {
                    ":p": progress,
                    ":health": min(now + 120, self.root["authorization_expires"]),
                    ":active": "ACTIVE",
                    ":g": generation,
                },
            )
        )

    def prepare(self, operation, slot, generation, now):
        self.validate()
        require(slot in self.root["creation_slots"], "unapproved_creation")
        require(operation == slot["operation"], "operation_binding")
        require(now < self.root["authorization_expires"], "authorization_expired")
        return self.transact(
            self.update(
                "ADD outstanding :one, revision :one",
                "#s=:active AND generation=:g AND health_until>:now",
                {":one": 1, ":active": "ACTIVE", ":g": generation, ":now": now},
            ),
            self.put("INTENT#" + operation, body=canonical(slot).decode(), status="PREPARED"),
        )

    def dispatch(self, operation, generation, now):
        self.validate()
        require(now < self.root["authorization_expires"], "authorization_expired")
        return self.transact(
            self.update(
                "ADD revision :one",
                "#s=:active AND generation=:g AND health_until>:now",
                {":one": 1, ":active": "ACTIVE", ":g": generation, ":now": now},
            ),
            {
                "Update": dict(
                    TableName=self.table,
                    Key=self.key("INTENT#" + operation),
                    UpdateExpression="SET #s=:sent",
                    ConditionExpression="#s=:prepared",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues=encode(
                        {":sent": "DISPATCHED", ":prepared": "PREPARED"}
                    ),
                )
            },
        )

    def register(self, operation, resource):
        self.validate()
        intent = self.get("INTENT#" + operation)
        require(intent is not None, "registration_intent")
        slot = json.loads(intent["body"])
        require(
            all(resource[k] == slot[k] for k in ["kind", "parent", "key", "request_sha256"]),
            "registration_scope",
        )
        require(
            resource["account"] == self.root["account"]
            and resource["region"] == self.root["region"],
            "registration_boundary",
        )
        Native(
            **{k: resource[k] for k in ["kind", "account", "region", "identifier", "parent", "key"]}
        ).arn()
        require(
            resource["kind"] != "version" or resource["identifier"] != "null",
            "unversioned_creation",
        )
        body = canonical(resource).decode()
        existing = self.get("RESOURCE#" + operation)
        if existing is not None:
            require(existing["body"] == body, "registration_substitution")
            return digest(body.encode())
        require(intent["status"] == "DISPATCHED", "registration_intent")
        self.transact(
            self.update(
                "ADD outstanding :minus, revision :one",
                "#s<>:complete AND outstanding>=:one",
                {":minus": -1, ":one": 1, ":complete": "COMPLETE"},
            ),
            {
                "Update": dict(
                    TableName=self.table,
                    Key=self.key("INTENT#" + operation),
                    UpdateExpression="SET #s=:registered",
                    ConditionExpression="#s=:sent",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues=encode(
                        {":registered": "REGISTERED", ":sent": "DISPATCHED"}
                    ),
                )
            },
            self.put("RESOURCE#" + operation, body=body),
        )
        return digest(body.encode())

    def fence(self, now):
        self.validate()
        # Health loss/withdrawal can fence early. No path restores ACTIVE.
        return self.transact(
            self.update(
                "SET #s=:fenced, lease_end=:zero ADD generation :one, revision :one",
                "#s=:active OR #s=:pending",
                {
                    ":fenced": "FENCED",
                    ":zero": 0,
                    ":one": 1,
                    ":active": "ACTIVE",
                    ":pending": "PENDING",
                },
            )
        )

    def claim(self, worker, now):
        state = self.validate()
        require(
            state["status"] in {"FENCED", "CLEANING", "VERIFYING", "COMPLETE"}, "cleanup_not_fenced"
        )
        generation = int(state["generation"])
        self.transact(
            self.update(
                "SET #s=:cleaning, worker=:w, lease_end=:end ADD generation :one",
                "generation=:g AND #s<>:active AND #s<>:pending AND lease_end<=:now",
                {
                    ":cleaning": "CLEANING",
                    ":w": worker,
                    ":end": now + 45,
                    ":one": 1,
                    ":g": generation,
                    ":active": "ACTIVE",
                    ":pending": "PENDING",
                    ":now": now,
                },
            )
        )
        return dict(worker=worker, generation=generation + 1, root=self.anchor)

    def check_claim(self, token, now):
        state = self.validate()
        require(
            token["root"] == self.anchor
            and state["worker"] == token["worker"]
            and state["generation"] == token["generation"]
            and state["status"] == "CLEANING"
            and now < state["lease_end"],
            "stale_claim",
        )

    def progress(self, token, resource_sha, status, now):
        require(status in {"REQUESTED", "INCOMPLETE"}, "progress_status")
        self.check_claim(token, now)
        return self.transact(
            self.update(
                "ADD revision :one",
                "#s=:cleaning AND generation=:g AND worker=:w AND lease_end>:now",
                {
                    ":one": 1,
                    ":cleaning": "CLEANING",
                    ":g": token["generation"],
                    ":w": token["worker"],
                    ":now": now,
                },
            ),
            self.put("PROGRESS#" + secrets.token_hex(16), resource=resource_sha, status=status),
        )

    def challenge(self, now, verifier_role, key_sha):
        require(
            (verifier_role, key_sha)
            == (self.root["verifier_role"], self.root["signing_key_sha256"]),
            "pinned_verifier_authority",
        )
        state = self.validate()
        require(
            state["status"] in {"CLEANING", "VERIFYING", "COMPLETE"} and state["outstanding"] == 0,
            "unsettled_creation",
        )
        # No absence proof is possible without independently reviewed settlement
        # evidence. In this package only synthetic fixtures can supply this row.
        settlement = self.get("SETTLEMENT")
        require(
            settlement is not None and settlement["generation"] == state["generation"],
            "write_settlement_unproven",
        )
        request = dict(
            version="aws-absence-1.0",
            root=self.anchor,
            scope="DEDICATED_ACCOUNT_REGION",
            account=self.root["account"],
            region=self.root["region"],
            tenant=self.root["tenant"],
            namespace=self.root["namespace"],
            generation=int(state["generation"]),
            revision=int(state["revision"]),
            nonce=secrets.token_hex(32),
            issued=now,
            expires=now + 60,
            verifier_role=verifier_role,
            signing_key_sha256=key_sha,
            settlement=settlement["sha256"],
        )
        self.transact(
            self.update(
                "SET #s=:verifying",
                "generation=:g AND revision=:r AND outstanding=:zero AND #s<>:active",
                {
                    ":verifying": "VERIFYING",
                    ":g": request["generation"],
                    ":r": request["revision"],
                    ":zero": 0,
                    ":active": "ACTIVE",
                },
            ),
            self.put("NONCE#" + request["nonce"], body=canonical(request).decode(), consumed=False),
        )
        return request

    def complete(self, request, response_sha, now):
        self.validate()
        require(request["root"] == self.anchor and now < request["expires"], "observation_expired")
        self.transact(
            self.update(
                "SET #s=:complete",
                "#s=:verifying AND generation=:g AND revision=:r AND outstanding=:zero",
                {
                    ":complete": "COMPLETE",
                    ":verifying": "VERIFYING",
                    ":g": request["generation"],
                    ":r": request["revision"],
                    ":zero": 0,
                },
            ),
            {
                "Update": dict(
                    TableName=self.table,
                    Key=self.key("NONCE#" + request["nonce"]),
                    UpdateExpression="SET consumed=:true, response_sha=:sha",
                    ConditionExpression="consumed=:false AND body=:body",
                    ExpressionAttributeValues=encode(
                        {
                            ":true": True,
                            ":false": False,
                            ":body": canonical(request).decode(),
                            ":sha": response_sha,
                        }
                    ),
                )
            },
        )

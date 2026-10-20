"""KMS service-signing adapter and pinned public-key verification (not owner key)."""

import base64
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils

from tools.phase2_aws_inventory import COVERAGE
from tools.phase2_cloud_retention_model import Refusal, canonical, digest, require

ALGORITHM = "RSASSA_PSS_SHA_256"


class Verifier:
    def __init__(self, inventory, signing_sdk, key_arn, public_key_sha):
        self.inventory, self.signing_sdk = inventory, signing_sdk
        self.key_arn, self.public_key_sha = key_arn, public_key_sha

    def answer(self, request, now):
        reader = self.inventory.sdk.boundary
        require(
            request["version"] == "aws-absence-1.0"
            and request["scope"] == "DEDICATED_ACCOUNT_REGION",
            "inventory_scope",
        )
        require(
            (request["account"], request["region"], request["verifier_role"], request["root"])
            == (reader.account, reader.region, reader.role, reader.root),
            "verifier_binding",
        )
        require(request["signing_key_sha256"] == self.public_key_sha, "signing_key_binding")
        require(request["issued"] <= now < request["expires"], "observation_expired")
        present = self.inventory.query()  # Authenticates separate read-only role.
        self.signing_sdk.authenticate()
        body = canonical(
            dict(
                request=request,
                observed_at=now,
                coverage=COVERAGE,
                exhaustive=True,
                present=sorted(r.commitment for r in present),
                mode="OFFLINE_ONLY",
            )
        )
        response = self.signing_sdk.call(
            "kms",
            "sign",
            KeyId=self.key_arn,
            Message=hashlib.sha256(body).digest(),
            MessageType="DIGEST",
            SigningAlgorithm=ALGORITHM,
        )
        require(
            response["KeyId"] == self.key_arn and response["SigningAlgorithm"] == ALGORITHM,
            "signer_identity",
        )
        return dict(body=body, signature=response["Signature"])


def accept(registry, request, envelope, pinned_der, now):
    body, signature = envelope["body"], envelope["signature"]
    require(type(body) is bytes and len(body) < 256000 and type(signature) is bytes, "envelope")
    require(digest(pinned_der) == request["signing_key_sha256"], "signing_key_binding")
    public = serialization.load_der_public_key(pinned_der)
    if not isinstance(public, rsa.RSAPublicKey):
        raise Refusal("service_key_profile")
    require(public.key_size >= 3072, "service_key_profile")
    try:
        public.verify(
            signature,
            hashlib.sha256(body).digest(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
            utils.Prehashed(hashes.SHA256()),
        )
    except InvalidSignature:
        require(False, "service_signature")
    record = json.loads(body)
    require(record["request"] == request and canonical(record) == body, "observation_binding")
    require(
        set(record) == {"request", "observed_at", "coverage", "exhaustive", "present", "mode"}
        and record["mode"] == "OFFLINE_ONLY"
        and record["exhaustive"] is True
        and record["coverage"] == COVERAGE,
        "observation_coverage",
    )
    require(
        request["issued"] <= record["observed_at"] <= now < request["expires"],
        "observation_expired",
    )
    require(record["present"] == [], "protected_resources_remain")
    registry.complete(request, digest(body), now)
    return dict(
        version="aws-offline-receipt-1.0",
        observation_sha256=digest(body),
        status="COMPLETE",
        real_cloud_proof=False,
    )


def wire_envelope(envelope):
    return {key: base64.b64encode(value).decode("ascii") for key, value in envelope.items()}

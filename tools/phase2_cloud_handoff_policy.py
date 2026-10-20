"""Offline reviewer-copy decision evaluator; never an export or live grant API."""

import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tools.phase2_cloud_retention_model import Refusal, canonical, digest, require


def evaluate_copy_decision(body, signature, *, approved_public_key, binding, now):
    """Synthetic signed decisions only. Existing real custody grant APIs unchanged.

    A hash of approval evidence alone is NOT authentication. Verify a separately
    pinned public key and exact signed decision, then every destination/guarantee.
    """
    require(type(body) is bytes and len(body) <= 64000, "decision_format")
    try:
        record = json.loads(body)
    except (ValueError, TypeError):
        raise Refusal("decision_format") from None
    require(type(record) is dict and record.get("status") == "APPROVED", "owner_decision_pending")
    try:
        Ed25519PublicKey.from_public_bytes(approved_public_key).verify(signature, body)
    except (ValueError, TypeError, InvalidSignature):
        raise Refusal("owner_decision_authentication") from None
    require(
        set(record)
        == {
            "version",
            "mode",
            "status",
            "option",
            "binding",
            "authorization_expires",
            "copies",
            "approval_evidence_sha256",
        },
        "decision_format",
    )
    require(
        record["version"] == "reviewer-copy-decision-1.0" and record["mode"] == "SYNTHETIC_ONLY",
        "not_live_authorization",
    )
    require(canonical(record) == body and record["binding"] == binding, "decision_binding")
    require(
        type(record["authorization_expires"]) is int
        and type(now) is int
        and binding["created"]
        <= now
        < record["authorization_expires"]
        <= binding["retention_expires"],
        "copy_authorization_expired",
    )
    require(
        record["approval_evidence_sha256"] == binding["approval_evidence_sha256"],
        "approval_evidence",
    )
    require(
        record["option"] in {"MANAGED_REVIEW", "CONTRACTED_PROCESSOR"}, "handoff_option_blocked"
    )
    copies = record["copies"]
    require(type(copies) is list and 0 < len(copies) <= 20, "copy_inventory")
    require(len({canonical(c["destination"]) for c in copies}) == len(copies), "duplicate_copy")
    for copy in copies:
        require(
            set(copy)
            == {
                "destination",
                "classification",
                "expires",
                "independent_deletion_verification",
                "provider_contract_sha256",
                "cleanup_receipt_required",
            },
            "copy_format",
        )
        require(copy["destination"] in binding["registered_destinations"], "unregistered_export")
        require(copy["classification"] == "SOURCE_ONLY_A", "prediction_export_forbidden")
        require(
            type(copy["expires"]) is int and now < copy["expires"] <= binding["retention_expires"],
            "copy_retention_extension",
        )
        require(
            copy["cleanup_receipt_required"] is True
            and copy["independent_deletion_verification"] is True,
            "copy_cleanup_unproven",
        )
        if record["option"] == "CONTRACTED_PROCESSOR":
            require(
                copy["provider_contract_sha256"] in binding["approved_processor_contracts"],
                "processor_contract_missing",
            )
        else:
            require(copy["provider_contract_sha256"] is None, "managed_copy_contract")
    return dict(
        status="SYNTHETIC_POLICY_ELIGIBLE",
        decision_sha256=digest(body),
        real_handoff_authorized=False,
    )

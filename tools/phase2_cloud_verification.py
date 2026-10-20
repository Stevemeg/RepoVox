"""Separate authenticated absence interface. OFFLINE FIXTURES ONLY; not AWS proof.

The cleaner has no signing key/reader credential. The verifier opens its own
read-only provider connection, authenticates a distinct principal, and signs a
fresh root/fence/catalog/nonce-bound observation. Never shares MockCloud objects.
"""

import json
import secrets
import sqlite3
from dataclasses import asdict

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tools.phase2_cloud_retention_model import Resource, canonical, digest, require

KINDS = ["bucket", "compute", "snapshot", "upload", "version", "volume"]
INVENTORY_SCOPE = "DEDICATED_ACCOUNT_REGION"
QUERY_VERSION = "absence-query-1.2"


def require_inventory_scope(request):
    require(
        type(request) is dict
        and request.get("version") == QUERY_VERSION
        and request.get("inventory_scope") == INVENTORY_SCOPE,
        "inventory_scope",
    )


class ReadOnlyFixtureInventory:
    """Independent authenticated connection to an offline provider fixture.

    It exposes no mutation method. SQLite read-only URI enforces no writes on
    this connection. Credential checks model a provider boundary, NOT AWS IAM.
    """

    def __init__(self, path, principal, credential):
        self.path, self.principal, self.credential = path, principal, credential

    def query(self, request):
        require_inventory_scope(request)
        with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT credential_sha,permission FROM principals WHERE principal=?",
                (self.principal,),
            ).fetchone()
            require(
                row == (digest(self.credential), "READ_ONLY_VERIFIER"),
                "verifier_provider_authentication",
            )
            require(self.principal == request["principal"], "verifier_principal")
            require(
                db.execute("SELECT account,region FROM endpoint").fetchone()
                == (request["account"], request["region"]),
                "provider_boundary",
            )
            resources = [
                Resource(**json.loads(body))
                for (body,) in db.execute("SELECT body FROM resources WHERE present=1")
            ]
        # Read coverage is account/region-wide, NOT a deletion allowlist. Parent
        # metadata may be absent (detached disks) or unusable (snapshot copies).
        # Never narrow absence evidence using namespace, tenant, tags or lineage.
        for resource in resources:
            require(
                (resource.account, resource.region) == (request["account"], request["region"]),
                "provider_resource_boundary",
            )
            require(resource.kind in KINDS, "provider_resource_kind")
        return sorted(digest(canonical(asdict(r))) for r in resources)


class OfflineVerifier:
    """Synthetic signing service, separately provisioned from cleanup authority.

    Private keys here must be disposable fixture keys, never owner enrollment.
    A live implementation needs its own KMS/trust/IAM deployment and API tests.
    """

    def __init__(self, reader, fixture_signing_key):
        require(type(reader) is ReadOnlyFixtureInventory, "independent_reader_required")
        self.reader, self.signing_key = reader, fixture_signing_key

    def answer(self, request):
        present = self.reader.query(request)
        body = canonical(
            dict(
                request=request,
                observed_at=request["issued_at"],
                coverage=KINDS,
                exhaustive=True,
                present=present,
                mode="SYNTHETIC_ONLY",
            )
        )
        return body, self.signing_key.sign(body)


def challenge(ledger, now):
    with ledger.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        ledger.validate(db)
        state, generation, ready = db.execute(
            "SELECT status,generation,ready FROM state"
        ).fetchone()
        require(state in {"VERIFYING", "COMPLETE"} and not ready, "verification_state")
        require(type(now) is int and now >= ledger.manifest.created, "clock")
        require(
            not db.execute("SELECT 1 FROM intent_status WHERE status='DISPATCHED'").fetchone(),
            "unresolved_creation",
        )
        resources = ledger.resources(db)
        manifest = ledger.manifest
        request = dict(
            version=QUERY_VERSION,
            inventory_scope=INVENTORY_SCOPE,
            root=ledger.expected,
            generation=generation,
            catalog=digest(canonical(sorted(r.commitment for r in resources))),
            nonce=secrets.token_hex(32),
            issued_at=now,
            valid_until=now + 60,
            account=manifest.account,
            region=manifest.region,
            namespace=manifest.namespace,
            tenant=manifest.tenant,
            principal=manifest.verifier_principal,
            identities=[list(r.identity) for r in sorted(resources, key=lambda r: r.identity)],
        )
        db.execute(
            "INSERT INTO observations(nonce,request) VALUES(?,?)",
            (request["nonce"], canonical(request)),
        )
        db.commit()
        return request


def accept_observation(ledger, request, envelope, now):
    require_inventory_scope(request)
    body, signature = envelope
    require(
        type(body) is bytes and len(body) <= 256000 and type(signature) is bytes,
        "observation_format",
    )
    try:
        Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(ledger.manifest.verifier_public_key)
        ).verify(signature, body)
    except (InvalidSignature, ValueError, TypeError):
        from tools.phase2_cloud_retention_model import Refusal

        raise Refusal("verifier_signature") from None
    try:
        record = json.loads(body)
    except (ValueError, TypeError):
        record = None
    require(
        type(record) is dict
        and set(record) == {"request", "observed_at", "coverage", "exhaustive", "present", "mode"},
        "observation_format",
    )
    require(record["request"] == request and canonical(record) == body, "observation_binding")
    require(
        record["mode"] == "SYNTHETIC_ONLY"
        and record["exhaustive"] is True
        and record["coverage"] == KINDS,
        "observation_coverage",
    )
    require(
        type(now) is int
        and type(record["observed_at"]) is int
        and request["issued_at"] <= record["observed_at"] <= now < request["valid_until"],
        "observation_stale",
    )
    require(record["present"] == [], "protected_resources_remain")
    with ledger.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        ledger.validate(db)
        row = db.execute(
            "SELECT request,consumed FROM observations WHERE nonce=?", (request["nonce"],)
        ).fetchone()
        require(row == (canonical(request), 0), "observation_replay_or_unknown")
        state, generation, ready = db.execute(
            "SELECT status,generation,ready FROM state"
        ).fetchone()
        require(
            state in {"VERIFYING", "COMPLETE"}
            and generation == request["generation"]
            and not ready,
            "verification_state",
        )
        require(
            request["catalog"]
            == digest(canonical(sorted(r.commitment for r in ledger.resources(db)))),
            "observation_catalog_changed",
        )
        db.execute(
            "UPDATE observations SET consumed=1,response_sha=? WHERE nonce=?",
            (digest(body), request["nonce"]),
        )
        db.execute("UPDATE state SET status='COMPLETE'")
        ledger.audit(db, "ABSENCE_VERIFIED")
        db.commit()
    return dict(
        version="synthetic-cleanup-receipt-1.2",
        inventory_scope=INVENTORY_SCOPE,
        registry=ledger.expected,
        status="COMPLETE",
        verified_at=now,
        remaining=0,
        observation_sha256=digest(body),
        real_cloud_proof=False,
    )


def verify_absence(ledger, observer, now):
    require(type(observer) is OfflineVerifier, "separate_observer_required")
    request = challenge(ledger, now)
    return accept_observation(ledger, request, observer.answer(request), now)

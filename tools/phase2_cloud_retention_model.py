"""NONDEPLOYABLE cloud-retention protocol model: synthetic metadata and mock APIs only.

No boto clients, credentials, Lambda handler, shell commands or protected bytes.
SQLite models conditional durable state; it does NOT prove AWS IAM/API behavior.
"""

import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path


class Refusal(ValueError):
    """Fixed, payload-free reason code."""


def require(condition, code):
    if not condition:
        raise Refusal(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class Resource:
    kind: str
    identifier: str
    account: str
    region: str
    namespace: str
    tenant: str
    provisioning_sha256: str
    parent: str = ""
    key: str = ""

    @property
    def commitment(self):
        return digest(canonical(asdict(self)))


@dataclass(frozen=True)
class Manifest:
    owner: str
    tenant: str
    attempt: str
    namespace: str
    scope_sha256: str
    account: str
    region: str
    created: int
    expires: int
    authorization_expires: int
    resources: tuple[Resource, ...]
    mode: str = "SYNTHETIC_ONLY"
    version: str = "cloud-retention-model-1.0"
    custodian_uid: int = 10002
    custodian_gid: int = 10002
    capability_mask: int = 0
    no_new_privileges: bool = True

    def validate(self):
        require(self.mode == "SYNTHETIC_ONLY", "real_activation_forbidden")
        require(self.version == "cloud-retention-model-1.0", "model_version")
        require(
            type(self.custodian_uid) is int
            and self.custodian_uid == 10002
            and type(self.custodian_gid) is int
            and self.custodian_gid == 10002
            and type(self.capability_mask) is int
            and self.capability_mask == 0
            and self.no_new_privileges is True,
            "custodian_profile",
        )
        for name in (self.owner, self.tenant, self.attempt, self.namespace):
            require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name), "identity")
        require(re.fullmatch(r"[a-f0-9]{64}", self.scope_sha256), "scope")
        require(re.fullmatch(r"[0-9]{12}", self.account), "account")
        require(re.fullmatch(r"[a-z]{2}-[a-z]+-[1-9]", self.region), "region")
        require(
            all(type(n) is int for n in (self.created, self.expires, self.authorization_expires))
            and self.created < self.authorization_expires <= self.expires
            and self.expires - self.created <= 30 * 86400,
            "fixed_deadlines",
        )
        require(0 < len(self.resources) <= 100, "resource_limit")
        ids = {r.identifier: r for r in self.resources}
        require(len(ids) == len(self.resources), "duplicate_resource")
        require(sum(r.kind == "compute" for r in self.resources) == 1, "one_runtime")
        for r in self.resources:
            require(
                re.fullmatch(r"[a-f0-9]{64}", r.provisioning_sha256)
                and r.provisioning_sha256 != "0" * 64,
                "provisioning_receipt",
            )
            require(
                (r.account, r.region, r.namespace, r.tenant)
                == (self.account, self.region, self.namespace, self.tenant),
                "resource_boundary",
            )
            require(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", r.identifier), "resource_id")
            require(
                r.kind in {"compute", "volume", "snapshot", "bucket", "version", "upload"},
                "unsupported_resource",
            )
            if r.kind in {"volume", "snapshot", "version", "upload"}:
                parent_kind = {
                    "volume": "compute",
                    "snapshot": "volume",
                    "version": "bucket",
                    "upload": "bucket",
                }[r.kind]
                require(r.parent in ids and ids[r.parent].kind == parent_kind, "resource_parent")
            else:
                require(not r.parent, "unexpected_parent")
            if r.kind in {"version", "upload"}:
                require(re.fullmatch(r"objects/[a-f0-9]{64}", r.key), "opaque_object_key")
            else:
                require(not r.key, "unexpected_key")

    @property
    def body(self):
        self.validate()
        return canonical(asdict(self))

    @property
    def commitment(self):
        return digest(self.body)


class Ledger:
    """Local synthetic transaction/intent model, never a real custody store."""

    def __init__(self, path: Path, manifest: Manifest, expected: str, create=False):
        require(manifest.commitment == expected, "registry_commitment")
        self.path, self.manifest, self.expected = path, manifest, expected
        if create:
            require(not path.exists(), "exclusive_registry")
            with self.connect() as db:
                db.executescript("""
                  CREATE TABLE registry(body BLOB NOT NULL);
                  CREATE TRIGGER immutable_update BEFORE UPDATE ON registry
                    BEGIN SELECT RAISE(ABORT,'immutable_registry'); END;
                  CREATE TRIGGER immutable_delete BEFORE DELETE ON registry
                    BEGIN SELECT RAISE(ABORT,'immutable_registry'); END;
                  CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1), status TEXT,
                    generation INTEGER, ready INTEGER, worker TEXT, lease_end INTEGER);
                  CREATE TABLE actions(resource TEXT PRIMARY KEY, status TEXT);
                  CREATE TABLE incidents(reason TEXT PRIMARY KEY, status TEXT);
                  CREATE TABLE audit(seq INTEGER PRIMARY KEY, body BLOB, sha TEXT);
                """)
                db.execute("INSERT INTO registry VALUES(?)", (manifest.body,))
                db.execute("INSERT INTO state VALUES(1,'CREATED',1,0,'',0)")
                self.audit(db, "REGISTERED")
        self.snapshot()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2, isolation_level=None)
        db.execute("PRAGMA synchronous=EXTRA")
        try:
            with db:
                yield db
        finally:
            db.close()

    def validate(self, db):
        rows = db.execute("SELECT body FROM registry").fetchall()
        require(len(rows) == 1 and digest(rows[0][0]) == self.expected, "registry_integrity")
        previous = "0" * 64
        for seq, body, sha in db.execute("SELECT seq,body,sha FROM audit ORDER BY seq"):
            try:
                record = json.loads(body)
            except (ValueError, TypeError):
                raise Refusal("audit_integrity") from None
            require(
                type(record) is dict and set(record) == {"previous", "seq", "event"},
                "audit_integrity",
            )
            require(
                record["previous"] == previous and record["seq"] == seq and digest(body) == sha,
                "audit_integrity",
            )
            previous = sha

    def audit(self, db, event):
        row = db.execute("SELECT seq,sha FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        body = canonical(
            dict(seq=row[0] + 1 if row else 1, previous=row[1] if row else "0" * 64, event=event)
        )
        db.execute("INSERT INTO audit VALUES(?,?,?)", (json.loads(body)["seq"], body, digest(body)))

    def snapshot(self):
        with self.connect() as db:
            db.execute("BEGIN")
            self.validate(db)
            return db.execute("SELECT status,generation,ready FROM state").fetchone()

    def incident(self, code):
        require(
            code in {"HEALTH_LOST", "CLEANUP_INCOMPLETE", "POST_COMPLETION_DRIFT"}, "incident_code"
        )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.validate(db)
            cursor = db.execute("INSERT OR IGNORE INTO incidents VALUES(?,'PENDING')", (code,))
            if cursor.rowcount:
                self.audit(db, "ALERT_QUEUED")
            db.commit()

    def deliver_incidents(self, sink):
        require(type(sink) is MockAlerts, "mock_alert_sink_required")
        with self.connect() as db:
            self.validate(db)
            pending = db.execute("SELECT reason FROM incidents WHERE status='PENDING'").fetchall()
        for (code,) in pending:
            # No transaction held across delivery; receiver deduplicates this opaque identity.
            sink.deliver(self.expected, code)
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.validate(db)
                db.execute("UPDATE incidents SET status='DELIVERED' WHERE reason=?", (code,))
                db.commit()

    def activate(self, now, *, supervision_verified, inventory_verified):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.validate(db)
            status = db.execute("SELECT status FROM state").fetchone()[0]
            require(status == "CREATED", "terminal_or_already_active")
            require(
                self.manifest.created <= now < self.manifest.authorization_expires,
                "authorization_expired",
            )
            require(supervision_verified and inventory_verified, "retention_not_activated")
            db.execute("UPDATE state SET status='ACTIVE',ready=1")
            self.audit(db, "ACTIVATED")
            db.commit()

    def admission(self, resource, generation, tenant, now):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.validate(db)
            state, fence, ready = db.execute("SELECT status,generation,ready FROM state").fetchone()
            require(tenant == self.manifest.tenant, "tenant")
            require(resource in self.manifest.resources, "unregistered_copy")
            require(
                self.manifest.created <= now < self.manifest.authorization_expires,
                "authorization_expired",
            )
            require(state == "ACTIVE" and ready and fence == generation, "execution_fenced")
            # This is admission only, NOT atomic completion of an external write.
            return fence

    def invalidate(self, reason):
        require(reason in {"HEALTH_LOST", "WITHDRAWN", "EXPIRY", "SCOPE_FAILURE"}, "reason")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.validate(db)
            state = db.execute("SELECT status FROM state").fetchone()[0]
            if state not in {"FENCED", "CLEANING", "VERIFYING", "COMPLETE"}:
                db.execute("UPDATE state SET status='FENCED',generation=generation+1,ready=0")
                self.audit(db, reason)
            db.commit()

    def claim_cleanup(self, worker, now):
        require(re.fullmatch(r"[a-z0-9_-]{1,64}", worker), "worker_identity")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.validate(db)
            state, gen, owner, until = db.execute(
                "SELECT status,generation,worker,lease_end FROM state"
            ).fetchone()
            if state == "COMPLETE":
                return None
            require(
                now >= self.manifest.expires or state != "ACTIVE" and state != "CREATED", "not_due"
            )
            require(not owner or now >= until, "cleanup_busy")
            db.execute(
                "UPDATE state SET status='CLEANING',generation=?,ready=0,worker=?,lease_end=?",
                (gen + 1, worker, now + 60),
            )
            self.audit(db, "CLEANUP_CLAIMED")
            db.commit()
            return gen + 1

    def fenced_transaction(self, worker, generation, now, operation):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.validate(db)
            state, gen, owner, until = db.execute(
                "SELECT status,generation,worker,lease_end FROM state"
            ).fetchone()
            require(
                state in {"CLEANING", "VERIFYING"}
                and owner == worker
                and gen == generation
                and now < until,
                "cleanup_fenced",
            )
            operation(db)
            db.commit()


class MockCloud:
    """Explicit mock API. Resources contain identities/states, never protected data."""

    def __init__(self, resources, account, region):
        self.account, self.region = account, region
        self.resources = {r.identifier: r for r in resources}
        self.present = set(self.resources)
        self.fail = set()
        self.calls = []
        self.quiesced = False
        self.quiesce_available = True
        self.guest_running = True
        self.recycled = set()
        self.lock = threading.RLock()

    def inventory(self, manifest):
        with self.lock:
            require(
                (self.account, self.region) == (manifest.account, manifest.region),
                "provider_boundary",
            )
            require("inventory" not in self.fail, "provider_unavailable")
            expected = {r.identifier: r for r in manifest.resources}
            for key in self.present & expected.keys():
                require(self.resources[key] == expected[key], "provider_identity")
            owned = {
                k: v
                for k, v in self.resources.items()
                if v.namespace == manifest.namespace and k in self.present
            }
            require(set(owned) <= set(expected), "unmanaged_source_copy")
            for key, observed in owned.items():
                require(expected[key] == observed, "provider_identity")
            return tuple(sorted(owned))

    def quiesce(self, manifest):
        with self.lock:
            self.inventory(manifest)
            require(self.quiesce_available, "writers_not_quiescent")
            self.quiesced = True

    def delete(self, resource, manifest):
        with self.lock:
            self.inventory(manifest)
            require(resource in manifest.resources, "unregistered_delete")
            require(self.quiesced, "writers_not_quiescent")
            require(resource.identifier not in self.fail, "provider_unavailable")
            require(resource.identifier not in self.recycled, "provider_retention_hold")
            if resource.identifier not in self.present:
                return  # Idempotent not-found only after boundary/inventory checks.
            if resource.kind == "volume":
                require(resource.parent not in self.present, "volume_still_attached")
            if resource.kind == "bucket":
                require(
                    not any(
                        r.parent == resource.identifier and k in self.present
                        for k, r in self.resources.items()
                    ),
                    "bucket_not_empty",
                )
            self.calls.append((resource.kind, resource.commitment))
            self.present.remove(resource.identifier)


class MockAlerts:
    """Synthetic notification transport; delivery is not a human acknowledgment."""

    def __init__(self):
        self.available = True
        self.delivered = set()

    def deliver(self, root_sha, code):
        require(self.available, "notification_unavailable")
        self.delivered.add((root_sha, code))


class Controller:
    """Synthetic reconcile protocol. Never invokes an AWS API or existing pilot tool."""

    def __init__(self, ledger, cloud):
        require(type(cloud) is MockCloud, "mock_api_required")
        self.ledger, self.cloud = ledger, cloud

    def reconcile(self, now, worker="cleaner", crash_after_delete=False):
        manifest = self.ledger.manifest
        status = self.ledger.snapshot()[0]
        if status == "COMPLETE":
            # Reconciliation remains active and independently checks absence again.
            if self.cloud.inventory(manifest):
                self.ledger.incident("POST_COMPLETION_DRIFT")
                raise Refusal("post_completion_resource")
            return "COMPLETE"
        generation = self.ledger.claim_cleanup(worker, now)
        if generation is None:
            return "COMPLETE"
        try:
            self.cloud.quiesce(manifest)
            rank = {
                "compute": 0,
                "upload": 1,
                "version": 2,
                "snapshot": 3,
                "volume": 4,
                "bucket": 5,
            }
            for resource in sorted(manifest.resources, key=lambda r: (rank[r.kind], r.identifier)):

                def intent(db, resource=resource):
                    db.execute(
                        "INSERT OR IGNORE INTO actions VALUES(?,'INTENT')", (resource.commitment,)
                    )

                self.ledger.fenced_transaction(worker, generation, now, intent)
                self.cloud.delete(resource, manifest)  # No DB lock across provider I/O.
                if crash_after_delete:
                    raise InterruptedError("synthetic_crash")

                def done(db, resource=resource):
                    db.execute(
                        "UPDATE actions SET status='ABSENT' WHERE resource=?",
                        (resource.commitment,),
                    )

                self.ledger.fenced_transaction(worker, generation, now, done)
            self.ledger.fenced_transaction(
                worker,
                generation,
                now,
                lambda db: db.execute("UPDATE state SET status='VERIFYING',worker='',lease_end=0"),
            )
            return "VERIFYING"
        except Refusal:
            # Fixed code only; never persist SDK exception messages/request bodies.
            self.ledger.incident("CLEANUP_INCOMPLETE")
            self.ledger.fenced_transaction(
                worker,
                generation,
                now,
                lambda db: db.execute("UPDATE state SET worker='',lease_end=0"),
            )
            return "OVERDUE_INCOMPLETE" if now >= manifest.expires else "INCOMPLETE"

    def verify(self, now, observer):
        require(
            type(observer) is MockCloud and observer is not self.cloud, "separate_observer_required"
        )
        require(
            observer.resources is self.cloud.resources and observer.present is self.cloud.present,
            "independent_inventory_view",
        )
        require(not observer.inventory(self.ledger.manifest), "protected_resources_remain")
        with self.ledger.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.ledger.validate(db)
            status, ready = db.execute("SELECT status,ready FROM state").fetchone()
            require(status in {"VERIFYING", "COMPLETE"} and not ready, "verification_state")
            require(now >= self.ledger.manifest.created, "clock")
            if status != "COMPLETE":
                db.execute("UPDATE state SET status='COMPLETE'")
                self.ledger.audit(db, "ABSENCE_VERIFIED")
            db.commit()
        return dict(
            version="synthetic-cleanup-receipt-1.0",
            registry=self.ledger.expected,
            status="COMPLETE",
            verified_at=now,
            remaining=0,
            real_cloud_proof=False,
        )


def health(ledger, now, runtime_progress_at, reconciler_progress_at):
    healthy = all(
        type(t) is int and 0 <= now - t <= 90 for t in (runtime_progress_at, reconciler_progress_at)
    )
    if not healthy:
        ledger.invalidate("HEALTH_LOST")
        ledger.incident("HEALTH_LOST")
    return healthy

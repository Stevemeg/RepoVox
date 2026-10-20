"""NONDEPLOYABLE dynamic-ID intent protocol; no provider SDK or protected bytes.

Intent and result transactions are separate from the mock provider operation.
An uncertain DISPATCHED operation is never sent again. Recovery is cleanup-only.
"""

import json
from dataclasses import asdict

from tools.phase2_cloud_retention_model import canonical, digest, require


class Registration:
    def __init__(self, ledger):
        self.ledger = ledger

    def prepare(self, slot, generation, tenant, now):
        ledger = self.ledger
        with ledger.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ledger.validate(db)
            require(tenant == ledger.manifest.tenant, "tenant")
            require(slot in ledger.manifest.creation_slots, "unapproved_creation")
            require(
                ledger.manifest.created <= now < ledger.manifest.authorization_expires,
                "authorization_expired",
            )
            require(
                db.execute("SELECT status,generation,ready FROM state").fetchone()
                == ("ACTIVE", generation, 1),
                "execution_fenced",
            )
            body = canonical(dict(root=ledger.expected, slot=asdict(slot), generation=generation))
            row = db.execute(
                "SELECT body FROM create_intents WHERE operation=?", (slot.operation,)
            ).fetchone()
            if row:
                require(row[0] == body, "intent_substitution")
            else:
                db.execute("INSERT INTO create_intents VALUES(?,?)", (slot.operation, body))
                db.execute("INSERT INTO intent_status VALUES(?,'PREPARED')", (slot.operation,))
                ledger.audit(db, "CREATION_PREPARED")
            db.commit()

    def dispatch(self, slot, generation, now):
        ledger = self.ledger
        with ledger.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ledger.validate(db)
            require(slot in ledger.manifest.creation_slots, "unapproved_creation")
            require(
                ledger.manifest.created <= now < ledger.manifest.authorization_expires,
                "authorization_expired",
            )
            require(
                db.execute("SELECT status,generation,ready FROM state").fetchone()
                == ("ACTIVE", generation, 1),
                "execution_fenced",
            )
            changed = db.execute(
                "UPDATE intent_status SET status='DISPATCHED' "
                "WHERE operation=? AND status='PREPARED'",
                (slot.operation,),
            )
            require(changed.rowcount == 1, "creation_already_dispatched_or_missing")
            ledger.audit(db, "CREATION_DISPATCHED")
            db.commit()
        # Exactly one permission to send, not an atomic guarantee about a network call.
        return slot

    def register(self, slot, resource):
        """Persist a returned/discovered identity even after fencing, for cleanup only."""
        ledger = self.ledger
        with ledger.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ledger.validate(db)
            require(slot in ledger.manifest.creation_slots, "unapproved_creation")
            require(
                db.execute("SELECT status FROM state").fetchone()[0] != "COMPLETE",
                "terminal_registration",
            )
            require(
                resource.kind != "version" or resource.identifier != "null", "unversioned_creation"
            )
            require(
                (resource.kind, resource.parent, resource.key, resource.provisioning_sha256)
                == (slot.kind, slot.parent, slot.key, slot.request_sha256),
                "registration_scope",
            )
            body = canonical(asdict(resource))
            existing = db.execute(
                "SELECT body FROM registrations WHERE operation=?", (slot.operation,)
            ).fetchone()
            if existing:
                require(existing[0] == body, "registration_substitution")
                return digest(body)  # Lost acknowledgment: exact duplicate, not a new create.
            require(
                db.execute(
                    "SELECT status FROM intent_status WHERE operation=?", (slot.operation,)
                ).fetchone()
                == ("DISPATCHED",),
                "registration_intent",
            )
            tail = db.execute(
                "SELECT seq,sha FROM registrations ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            seq, previous = (tail[0] + 1, tail[1]) if tail else (1, ledger.expected)
            sha = digest(canonical([seq, slot.operation, digest(body), previous]))
            db.execute(
                "INSERT INTO registrations VALUES(?,?,?,?,?)",
                (seq, slot.operation, body, sha, previous),
            )
            db.execute(
                "UPDATE intent_status SET status='REGISTERED' WHERE operation=?", (slot.operation,)
            )
            ledger.resources(db)  # Atomic scope/duplicate validation before committing.
            ledger.audit(db, "PROVIDER_ID_REGISTERED")
            db.commit()
            return digest(body)

    def recover(self, provider, now):
        """Mock-only full discovery after provider-side write quiescence.

        No automatic creation retry. A real adapter must prove that no previously
        admitted request can finish later; stopping a guest alone cannot prove it.
        """
        require(now >= self.ledger.manifest.created, "clock")
        with self.ledger.connect() as db:
            self.ledger.validate(db)
            pending = db.execute(
                "SELECT operation FROM intent_status WHERE status='DISPATCHED'"
            ).fetchall()
        if not pending:
            return
        require(
            provider.quiesce_available and not provider.creation_in_flight, "creation_not_quiescent"
        )
        provider.quiesced = True
        slots = {s.operation: s for s in self.ledger.manifest.creation_slots}
        for (operation,) in pending:
            slot = slots[operation]
            require("inventory" not in provider.fail, "provider_unavailable")
            # No prefix/tag matching. A mock exhaustive enumeration at an exact,
            # fresh, pre-registered parent/key; every identity still gets registered.
            matches = [
                r
                for identity, r in provider.resources.items()
                if identity in provider.present
                and (r.kind, r.parent, r.key) == (slot.kind, slot.parent, slot.key)
            ]
            require(len(matches) == 1, "creation_unresolved_or_ambiguous")
            self.register(slot, matches[0])

    def pending(self):
        with self.ledger.connect() as db:
            self.ledger.validate(db)
            return db.execute(
                "SELECT operation,status FROM intent_status ORDER BY operation"
            ).fetchall()

    def commitment(self):
        with self.ledger.connect() as db:
            self.ledger.validate(db)
            rows = db.execute(
                "SELECT operation,body,sha FROM registrations ORDER BY seq"
            ).fetchall()
            return digest(canonical([(op, json.loads(body), sha) for op, body, sha in rows]))

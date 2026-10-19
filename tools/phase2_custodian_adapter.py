"""Explicit new offline custody interface; never changes the historical Store.

The trusted operator supplies admission and retention-readiness checks. No network
or database lock is held across a filesystem operation. Upstream pilot publication
still requires its own CP-01/02/03 transaction; these checks are not a distributed
transaction. Cancellation can leave retained orphan bytes, never a qualifying
publication. Reviewer exports use source_packet only, never this privileged API.
"""

from datetime import UTC, datetime

from repovox.analysis.privacy import screen_bytes
from repovox.evaluation.custody_v2 import KINDS, Event, validate_chain
from repovox.evaluation.v2 import serialize
from sqlalchemy import text

from tools.phase2_custodian_lifecycle import digest, require


class PilotLeaseAdmission:
    """Concrete active-execution gate using unchanged authenticated CP-01 scope SQL.

    A new owner-approved capture/review authorization is required after execution
    closes; this gate intentionally cannot authorize those later operations.
    """

    def __init__(self, executor, attempt, generation, manifest_sha, family, stage):
        # Obtain the fence through the accepted authenticated claim; never accept
        # a caller's unrelated stage/fence as proof of an attempt binding.
        lease = executor.claim(stage, attempt, generation, manifest_sha, family)
        require(
            lease is not None and str(lease["owner_id"]) == str(executor.owner),
            "pilot_claim_denied",
        )
        self.engine, self.owner, self.attempt = executor.engine, str(executor.owner), str(attempt)
        self.stage, self.fence, self.manifest_sha = stage, lease["fence"], manifest_sha
        self.lease = lease

    def __call__(self, plan):
        if plan["attempt"] != self.attempt or plan["manifest_sha256"] != self.manifest_sha:
            return False
        with self.engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('repovox.owner_id',:owner,true)"), {"owner": self.owner}
            )
            body = connection.scalar(
                text("SELECT rv.pilot_scope(:stage,:fence)"),
                {"stage": self.stage, "fence": self.fence},
            )
        return body is not None and digest(body.encode()) == plan["manifest_sha256"]


class CustodianStore:
    def __init__(self, lifecycle, token, admission, retention_ready):
        require(callable(admission) and callable(retention_ready), "custody_gates_required")
        self.lifecycle, self.token = lifecycle, token
        self.admission, self.retention_ready = admission, retention_ready

    def _gate(self, tenant):
        require(
            tenant == self.lifecycle.plan["tenant"] == self.token["tenant"], "custody_tenant_denied"
        )
        require(self.admission(self.lifecycle.plan) is True, "pilot_admission_denied")
        require(self.retention_ready(self.lifecycle.plan) is True, "retention_not_ready")

    def write(self, tenant, body):
        self._gate(tenant)
        screen_bytes(body)
        sha = digest(body)
        self.lifecycle.put(self.token, {tenant + "-" + sha: body})
        self._gate(tenant)  # Lost admission means no successful acknowledgment.
        return sha

    def read(self, tenant, sha):
        self._gate(tenant)
        require(len(sha) == 64 and all(c in "abcdef0123456789" for c in sha), "invalid_commitment")
        body = self.lifecycle.read(self.token, tenant + "-" + sha)
        require(digest(body) == sha, "private_evidence_changed")
        self._gate(tenant)
        return body

    def append_event(self, prior, **metadata):
        """Content and sequence reservation share one recoverable intent batch."""
        events = validate_chain(prior) if prior else []
        require(len(events) < len(KINDS), "custody_protocol_complete")
        event = Event.model_validate(
            {
                **metadata,
                "sequence": len(events) + 1,
                "kind": KINDS[len(events)],
                "recorded_at": datetime.now(UTC).isoformat(),
                "previous_event_sha256": prior[-1][1] if prior else None,
            }
        )
        tenant = event.tenant_id
        self.read(tenant, event.payload_sha256)
        for body, sha in prior:
            require(self.read(tenant, sha) == body, "retained_event_changed")
        body = serialize(event)
        sha = digest(body)
        validate_chain([*prior, (body, sha)])
        slot = f"{tenant}-{event.session_id}-event-{event.sequence}"
        self.lifecycle.put(
            self.token,
            {tenant + "-" + sha: body, slot: sha.encode()},
            event=(event.session_id, event.sequence, sha),
        )
        self._gate(tenant)
        return body, sha

    def validate_retained_chain(self, records):
        events = validate_chain(records)
        for event, (body, sha) in zip(events, records, strict=True):
            require(self.read(event.tenant_id, sha) == body, "retained_event_changed")
            slot = f"{event.tenant_id}-{event.session_id}-event-{event.sequence}"
            require(
                self.lifecycle.read(self.token, slot) == sha.encode(), "retained_event_slot_changed"
            )
        return events

    def prereveal(self, records, trusted_head):
        """Reuse accepted reference/response/blindness checks via a read-only facade."""
        from types import SimpleNamespace

        from repovox.evaluation.custody_v2 import prereveal

        self.validate_retained_chain(records)
        facade = SimpleNamespace(read=self.read, root=self.lifecycle.data)
        return prereveal(records, trusted_head, facade)

    def reveal(self, records, trusted_head, source, proofs):
        """Separately authorized future operation; never invoked by preparation."""
        from repovox.evaluation.v2 import Prediction, Scope, decode, validate_reference

        reference, prediction_hash = self.prereveal(records, trusted_head)
        events = self.validate_retained_chain(records)
        first = events[0]
        scope = decode(self.read(first.tenant_id, first.scope_sha256), first.scope_sha256, Scope)
        validate_reference(
            self.read(first.tenant_id, events[4].payload_sha256),
            events[4].payload_sha256,
            scope,
            first.scope_sha256,
            source,
            proofs,
        )
        metadata = {
            key: getattr(first, key)
            for key in [
                "tenant_id",
                "session_id",
                "scope_sha256",
                "engineering_commit",
                "scorer_commit",
                "trusted_context",
                "identity_basis",
            ]
        }
        event = self.append_event(records, **metadata, payload_sha256=prediction_hash)
        prediction = decode(
            self.read(first.tenant_id, prediction_hash), prediction_hash, Prediction
        )
        require(
            prediction.scope_sha256 == reference.scope_sha256
            and prediction.engineering_commit == first.engineering_commit,
            "revealed_prediction_binding",
        )
        return prediction, event

    def compare_sealed(self, records, trusted_head, source, proofs):
        """Accepted scorer, unchanged mathematics; new writes remain lifecycle-bound."""
        from repovox.evaluation.scoring_v2 import score
        from repovox.evaluation.v2 import Prediction, decode

        require(len(records) == 6 and records[-1][1] == trusted_head, "reveal_event_required")
        events = self.validate_retained_chain(records)
        self.prereveal(records[:5], records[4][1])
        first, last = events[0], events[-1]
        prediction_body = self.read(first.tenant_id, last.payload_sha256)
        prediction = decode(prediction_body, last.payload_sha256, Prediction)
        require(
            prediction.engineering_commit == first.engineering_commit, "revealed_prediction_binding"
        )
        body = serialize(
            score(
                self.read(first.tenant_id, events[4].payload_sha256),
                events[4].payload_sha256,
                self.read(first.tenant_id, last.payload_sha256),
                last.payload_sha256,
                self.read(first.tenant_id, first.scope_sha256),
                first.scope_sha256,
                source,
                proofs,
            )
        )
        sha = self.write(first.tenant_id, body)
        metadata = {
            key: getattr(first, key)
            for key in [
                "tenant_id",
                "session_id",
                "scope_sha256",
                "engineering_commit",
                "scorer_commit",
                "trusted_context",
                "identity_basis",
            ]
        }
        event = self.append_event(records, **metadata, payload_sha256=sha)
        return body, sha, event

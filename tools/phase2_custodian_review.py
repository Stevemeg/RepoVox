"""Offline, owner-key-authorized post-execution operations. No HTTP/Celery route.

Ed25519 keys are provisioned outside this tool. This verifier never creates owner
approvals or signs grants. A signature proves possession of the separately pinned
key, not provider identity, human review, or the truth of an annotation.
"""

import base64
import re
import time
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from repovox.analysis.privacy import screen_bytes
from repovox.evaluation.custody_v2 import Event, source_packet, validate_chain
from repovox.evaluation.projection_v2 import project_analysis
from repovox.evaluation.scoring_v2 import score
from repovox.evaluation.v2 import (
    Prediction,
    Reference,
    Scope,
    decode,
    serialize,
    source_bytes,
    validate_citation,
    validate_fact,
    validate_reference,
)
from repovox.pilot.control import Controller

from tools.phase2_custodian_lifecycle import (
    REVIEW_VERSION,
    canonical,
    digest,
    require,
    stamp,
    strict,
)
from tools.phase2_custodian_source import CustodySource, protect_memory
from tools.phase2_custodian_watchdog import LiveWatchdog

OPERATIONS = {
    "handoff": 3,
    "capture": 4,
    "seal_reference": 5,
    "reveal": 6,
    "compare": 7,
    "close": 8,
}
GRANT_FIELDS = {
    "version",
    "binding_sha256",
    "namespace",
    "tenant",
    "owner",
    "attempt",
    "family",
    "scope_sha256",
    "prediction_sha256",
    "operation",
    "input_sha256",
    "previous_head",
    "issued_at",
    "expires_at",
    "nonce",
    "approval_evidence_sha256",
}


def content_name(tenant, sha):
    require(re.fullmatch(r"[a-f0-9]{64}", sha), "invalid_commitment")
    return tenant + "-" + sha


class ReviewSession:
    """Privileged offline custodian interface; reviewer receives ONLY handoff output.

    Owner grants are operation-, payload-, head-, family- and namespace-specific.
    One durable intent commits payload, event, sequence slot and acknowledgment.
    There is no user-supplied predicate for closure or grant authentication.
    """

    def __init__(self, lifecycle, token, session, public_key, binding_sha256, watchdog):
        require(type(watchdog) is LiveWatchdog, "verified_watchdog_required")
        self.watchdog = watchdog
        require(lifecycle.plan["version"] == REVIEW_VERSION, "review_lifecycle_required")
        protect_memory()
        require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", session), "review_session")
        self.life, self.token, self.session = lifecycle, token, session
        self.binding_name = "review-" + session + "-binding"
        body = lifecycle.read(token, self.binding_name)
        require(digest(body) == binding_sha256, "review_binding_changed")
        self.binding, self.binding_sha = strict(body), binding_sha256
        require(self.binding["version"] == "custody-review-binding-1.0", "review_binding_version")
        require(digest(public_key) == self.binding["owner_key_sha256"], "owner_key_substitution")
        self.key = Ed25519PublicKey.from_public_bytes(public_key)
        require(
            self.binding["plan_sha256"] == lifecycle.plan_sha
            and self.binding["tenant"] == lifecycle.plan["tenant"]
            and self.binding["attempt"] == lifecycle.plan["attempt"],
            "review_namespace_binding",
        )

    @classmethod
    def establish(
        cls,
        life,
        token,
        controller,
        owner,
        generation,
        manifest,
        family,
        scope_body,
        analysis_body,
        records,
        public_key,
        proofs,
        watchdog,
    ):
        """Verify real authenticated SQL closure, original output and source before detaching.

        A terminal EXECUTION_CLOSED row is immutable under accepted CP-01. An
        offline receipt therefore remains valid across DB shutdown/restart. No SQL
        lease or DB credentials enter a grant or its recipient's Package A.
        """
        require(life.plan["version"] == REVIEW_VERSION, "review_lifecycle_required")
        protect_memory()
        require(type(controller) is Controller, "authenticated_controller_required")
        manifest.verify_engine()
        require(type(watchdog) is LiveWatchdog, "verified_watchdog_required")
        watchdog.proof(life.plan)
        status = controller.status(owner, life.plan["attempt"])
        require(
            status["state"] == "EXECUTION_CLOSED"
            and status["generation"] == generation + 1
            and status["manifest_sha"] == manifest.sha256
            and str(owner) == str(manifest.owner)
            and life.plan["manifest_sha256"] == manifest.sha256,
            "successful_execution_closure_required",
        )
        events = validate_chain(records)
        require(len(events) == 2, "sealed_execution_chain_required")
        first = events[0]
        require(
            first.engineering_commit == manifest.engine and first.scorer_commit == manifest.scorer,
            "execution_engineering_binding",
        )
        scope = decode(scope_body, first.scope_sha256, Scope)
        require(
            scope.tenant_id == first.tenant_id == life.plan["tenant"]
            and scope.analysis_owner_id == str(owner)
            and scope.family_id == family.id
            and scope.repository == family.repository
            and scope.commit_sha == family.commit
            and family in manifest.families,
            "execution_scope_binding",
        )
        selected = {f.path: (f.sha256, f.size) for f in family.files}
        require(
            {f.path: (f.file_sha256, f.size) for f in scope.files} == selected,
            "approved_scope_required",
        )
        expected_prediction = project_analysis(
            analysis_body,
            digest(analysis_body),
            scope,
            first.scope_sha256,
            manifest.engine,
        )
        tenant = life.plan["tenant"]

        def read(sha):
            return life.read(token, content_name(tenant, sha))

        require(read(digest(analysis_body)) == analysis_body, "original_analysis_required")
        require(
            read(events[1].payload_sha256) == serialize(expected_prediction),
            "original_projection_required",
        )
        source = CustodySource(life, token, scope_body, first.scope_sha256)
        originals = source_bytes(source, scope, proofs)
        for fact in expected_prediction.facts:
            validate_fact(fact.fact, scope, originals)
            for citation in fact.evidence:
                validate_citation(citation, scope, originals)
        for claim in expected_prediction.unprojected_claims:
            for citation in claim.citations:
                validate_citation(citation, scope, originals)
        for body in [scope_body, *originals.values(), *proofs.values()]:
            require(read(digest(body)) == body, "original_source_evidence_required")
        require(
            read(first.payload_sha256)
            == serialize(source_packet(scope_body, first.scope_sha256, source, proofs)),
            "source_only_packet_required",
        )
        for event, (body, sha) in zip(events, records, strict=True):
            require(read(sha) == body, "retained_event_changed")
            require(
                life.read(token, f"{tenant}-{first.session_id}-event-{event.sequence}")
                == sha.encode(),
                "retained_event_slot_changed",
            )
        binding = dict(
            version="custody-review-binding-1.0",
            plan_sha256=life.plan_sha,
            owner=str(owner),
            tenant=tenant,
            attempt=life.plan["attempt"],
            family=family.id,
            scope_sha256=first.scope_sha256,
            prediction_sha256=events[1].payload_sha256,
            source_packet_sha256=first.payload_sha256,
            analysis_sha256=digest(analysis_body),
            closed_generation=status["generation"],
            closed_observed_at=datetime.now(UTC).isoformat(),
            execution_head=records[1][1],
            manifest_sha256=manifest.sha256,
            owner_key_sha256=digest(public_key),
            engineering_commit=manifest.engine,
            scorer_commit=manifest.scorer,
            session=first.session_id,
        )
        body = canonical(binding)
        life.put(token, {"review-" + first.session_id + "-binding": body})
        return cls(life, token, first.session_id, public_key, digest(body), watchdog)

    def _read(self, sha):
        return self.life.read(self.token, content_name(self.binding["tenant"], sha))

    def records(self):
        records = []
        for sequence in range(1, 8):
            slot = f"{self.binding['tenant']}-{self.session}-event-{sequence}"
            try:
                sha = self.life.read(self.token, slot).decode("ascii")
            except ValueError as exc:
                if str(exc) != "evidence_not_committed":
                    raise
                break
            records.append((self._read(sha), sha))
        validate_chain(records)
        return records

    def _grant(self, signed, approval):
        require(isinstance(signed, bytes) and len(signed) <= 16384, "grant_size")
        require(isinstance(approval, bytes) and 0 < len(approval) <= 1_000_000, "approval_size")
        packet = strict(signed)
        require(set(packet) == {"grant", "signature"}, "grant_envelope")
        grant = packet["grant"]
        require(set(grant) == GRANT_FIELDS, "grant_fields")
        try:
            self.key.verify(base64.b64decode(packet["signature"], validate=True), canonical(grant))
        except (InvalidSignature, ValueError) as exc:
            raise ValueError("owner_signature_invalid") from exc
        require(grant["version"] == "custody-review-authorization-1.0", "grant_version")
        require(grant["binding_sha256"] == self.binding_sha, "grant_binding")
        require(grant["namespace"] == self.life.plan["namespace"], "grant_namespace")
        for field in ["tenant", "owner", "attempt", "family", "scope_sha256", "prediction_sha256"]:
            require(grant[field] == self.binding[field], "grant_" + field)
        require(grant["operation"] in OPERATIONS, "grant_operation")
        require(re.fullmatch(r"[a-f0-9]{32}", grant["nonce"]), "grant_nonce")
        require(digest(approval) == grant["approval_evidence_sha256"], "owner_approval_evidence")
        require(
            stamp(self.binding["closed_observed_at"])
            <= stamp(grant["issued_at"])
            <= time.time()
            < stamp(grant["expires_at"])
            <= stamp(self.life.plan["authorization_expires_at"])
            <= stamp(self.life.plan["expires_at"]),
            "review_authorization_expired",
        )
        require(
            stamp(grant["expires_at"]) - stamp(grant["issued_at"]) <= 86400,
            "review_operation_lifetime",
        )
        return grant

    def _validated_reference(self, body, records, source, proofs):
        scope_body = self._read(self.binding["scope_sha256"])
        scope = decode(scope_body, self.binding["scope_sha256"], Scope)
        ref = decode(body, digest(body), Reference)
        events = validate_chain(records)
        require(
            ref.revision == 1
            and ref.revision_context == "initial_blind"
            and ref.provenance.response_capture_sha256 == events[3].payload_sha256
            and ref.blind_source_sha256 == self.binding["source_packet_sha256"]
            and ref.prediction_commitment_sha256 == self.binding["prediction_sha256"],
            "independent_reference_binding",
        )
        self._read(ref.provenance.source_only_attestation_sha256)
        for sha in [
            ref.provenance.source_only_attestation_sha256,
            ref.provenance.response_capture_sha256,
            ref.blind_source_sha256,
        ]:
            proofs[sha] = self._read(sha)
        validate_reference(body, digest(body), scope, self.binding["scope_sha256"], source, proofs)

    def _source(self):
        scope_body = self._read(self.binding["scope_sha256"])
        scope = decode(scope_body, self.binding["scope_sha256"], Scope)
        source = CustodySource(self.life, self.token, scope_body, self.binding["scope_sha256"])
        proofs = {
            sha: self._read(sha)
            for sha in [
                scope.rights_evidence_sha256,
                scope.snapshot_verification_sha256,
            ]
        }
        if "analysis_sha256" in self.binding:
            sha = self.binding["analysis_sha256"]
            proofs[sha] = self._read(sha)
        return source, proofs

    def perform(self, signed, approval, payload):
        """Returns only this operation's output; never exports a general Store/read handle.

        Duplicate identical signed requests return the original committed response;
        a different nonce/head cannot fork an event sequence. Recovery may commit
        a complete intent only before its original operation deadline.
        """
        grant = self._grant(signed, approval)
        require(
            digest(self.life.read(self.token, self.binding_name)) == self.binding_sha,
            "review_binding_changed",
        )
        self.watchdog.proof(self.life.plan)
        require(digest(payload) == grant["input_sha256"], "grant_payload_changed")
        operation = grant["operation"]
        slot = "review-use-" + grant["nonce"]
        try:
            acknowledgment = strict(self.life.read(self.token, slot))
        except ValueError as exc:
            if str(exc) != "evidence_not_committed":
                raise
        else:
            require(acknowledgment["grant_sha256"] == digest(signed), "authorization_replay")
            return self._read(acknowledgment["output_sha256"]), acknowledgment
        records = self.records()
        require(len(records) + 1 == OPERATIONS[operation], "review_event_sequence")
        require(records[-1][1] == grant["previous_head"], "review_head_changed")
        require(records[1][1] == self.binding["execution_head"], "execution_head_changed")
        output = payload
        if operation == "handoff":
            require(digest(payload) == self.binding["source_packet_sha256"], "source_only_handoff")
            require(payload == self._read(digest(payload)), "handoff_changed")
        elif operation in {"seal_reference", "reveal", "compare"}:
            source, proofs = self._source()
            reference = (
                payload
                if operation == "seal_reference"
                else self._read(validate_chain(records)[4].payload_sha256)
            )
            self._validated_reference(reference, records, source, proofs)
            if operation == "reveal":
                require(digest(payload) == self.binding["prediction_sha256"], "premature_reveal")
                decode(payload, self.binding["prediction_sha256"], Prediction)
            elif operation == "compare":
                require(payload == reference, "comparison_reference_changed")
                output = serialize(
                    score(
                        reference,
                        digest(reference),
                        self._read(self.binding["prediction_sha256"]),
                        self.binding["prediction_sha256"],
                        self._read(self.binding["scope_sha256"]),
                        self.binding["scope_sha256"],
                        source,
                        proofs,
                    )
                )
        elif operation == "close":
            require(payload == records[-1][0], "closure_head_required")
        screen_bytes(output)
        acknowledgment = dict(grant_sha256=digest(signed), output_sha256=digest(output))
        entries = {
            content_name(self.binding["tenant"], digest(output)): output,
            content_name(self.binding["tenant"], digest(approval)): approval,
            content_name(self.binding["tenant"], digest(signed)): signed,
            slot: canonical(acknowledgment),
        }
        for body in entries.values():
            screen_bytes(body)
        # Already retained immutable content is verified, not resubmitted in a mixed batch.
        entries = {n: b for n, b in entries.items() if not self._retained(n, b)}
        event_binding = None
        if operation != "close":
            first = validate_chain(records)[0]
            metadata = first.model_dump()
            metadata.update(
                sequence=len(records) + 1,
                recorded_at=datetime.now(UTC).isoformat(),
                previous_event_sha256=records[-1][1],
                payload_sha256=digest(output),
            )
            from repovox.evaluation.custody_v2 import KINDS

            metadata["kind"] = KINDS[len(records)]
            body = serialize(Event.model_validate(metadata))
            validate_chain([*records, (body, digest(body))])
            entries[content_name(self.binding["tenant"], digest(body))] = body
            entries[f"{self.binding['tenant']}-{self.session}-event-{len(records) + 1}"] = digest(
                body
            ).encode()
            event_binding = (self.session, len(records) + 1, digest(body))
        self.life.put(
            self.token,
            entries,
            event=event_binding,
            operation_expires_at=grant["expires_at"],
            seal=operation == "close",
        )
        # Deadline crossing never yields a qualifying acknowledgment.
        self._grant(signed, approval)
        self.watchdog.proof(self.life.plan)
        return output, acknowledgment

    def _retained(self, name, body):
        try:
            existing = self.life.read(self.token, name)
        except ValueError as exc:
            if str(exc) == "evidence_not_committed":
                return False
            raise
        require(existing == body, "immutable_evidence_conflict")
        return True

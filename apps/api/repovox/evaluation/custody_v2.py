"""Offline v2 custody and future blind handoff; never mounts into application workers."""

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from repovox.analysis.privacy import redact, screen_bytes
from repovox.evaluation.gold import ID, SHA, Hash, Record
from repovox.evaluation.preparation import verify_boundary
from repovox.evaluation.v2 import (
    Policy,
    Prediction,
    Reference,
    Scope,
    Window,
    decode,
    digest,
    serialize,
    source_bytes,
)


class Excerpt(Record):
    citation: Window
    numbered_source: str
    redacted: bool


class SourcePacket(Record):
    schema_version: Literal["evaluation-blind-source-2.0"] = "evaluation-blind-source-2.0"
    scope_sha256: Hash
    excerpts: list[Excerpt]
    policy: Policy


def source_packet(
    scope_body: bytes, scope_hash: str, root: Path, proofs: dict[str, bytes]
) -> SourcePacket:
    """Source-only signature: predictions, scorer results and proposed answers cannot enter."""
    scope = decode(scope_body, scope_hash, Scope)
    bodies = source_bytes(root, scope, proofs)
    excerpts = []
    for f in scope.files:
        body = bodies[f.path]
        for w in f.windows:
            value, marks = redact(body[w.start_byte : w.end_byte].decode("utf-8"))
            excerpts.append(
                Excerpt(
                    citation=w,
                    numbered_source="\n".join(
                        f"{i}: {line}" for i, line in enumerate(value.split("\n"), w.start_line)
                    ),
                    redacted=bool(marks),
                )
            )
    return SourcePacket(scope_sha256=scope_hash, excerpts=excerpts, policy=Policy())


class Store:
    """Owner-only DAC + exclusive content writes. Administrator edits remain possible."""

    def __init__(self, root: Path, git_root: Path, tenant_id: str, worker_uid: int) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", tenant_id):
            raise ValueError("v2_invalid_tenant")
        verify_boundary(root, git_root, worker_uid)
        self.root, self.git_root, self.tenant_id, self.worker_uid = (
            root,
            git_root,
            tenant_id,
            worker_uid,
        )

    def _check(self, tenant_id: str) -> None:
        if tenant_id != self.tenant_id:
            raise ValueError("v2_tenant_denied")
        verify_boundary(self.root, self.git_root, self.worker_uid)

    def write(self, tenant_id: str, body: bytes) -> str:
        self._check(tenant_id)
        screen_bytes(body)
        sha = digest(body)
        path = self.root / (tenant_id + "-" + sha)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        return sha

    def read(self, tenant_id: str, sha: str) -> bytes:
        self._check(tenant_id)
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("v2_invalid_commitment")
        body = (self.root / (tenant_id + "-" + sha)).read_bytes()
        if digest(body) != sha:
            raise ValueError("v2_private_evidence_changed")
        return body


KINDS = [
    "SOURCE_APPROVED",
    "PREDICTION_SEALED",
    "SOURCE_HANDED_OFF",
    "RESPONSE_CAPTURED",
    "REFERENCE_SEALED",
    "PREDICTION_REVEALED",
    "COMPARISON_SEALED",
]


class Event(Record):
    schema_version: Literal["evaluation-custody-event-2.0"] = "evaluation-custody-event-2.0"
    tenant_id: ID
    session_id: ID
    sequence: int = Field(ge=1, le=7)
    kind: str
    recorded_at: str
    trusted_context: str = Field(min_length=1)
    scope_sha256: Hash
    engineering_commit: SHA
    scorer_commit: SHA
    payload_sha256: Hash
    previous_event_sha256: Hash | None
    identity_basis: Literal["owner_attested", "synthetic_fixture"]
    provider_authenticated: Literal[False] = False

    @model_validator(mode="after")
    def valid(self) -> "Event":
        if self.kind != KINDS[self.sequence - 1]:
            raise ValueError("v2_event_sequence")
        stamp = datetime.fromisoformat(self.recorded_at)
        if stamp.tzinfo is None or stamp.utcoffset() != UTC.utcoffset(stamp):
            raise ValueError("v2_event_utc_required")
        if (self.sequence == 1) != (self.previous_event_sha256 is None):
            raise ValueError("v2_event_chain_required")
        return self


def append_event(
    store: Store, prior: list[tuple[bytes, str]], **metadata: str
) -> tuple[bytes, str]:
    """Trusted operator supplies approved commitments; real local time is recorded, not invented."""
    events = validate_chain(prior) if prior else []
    if len(events) >= len(KINDS):
        raise ValueError("v2_protocol_already_complete")
    event = Event.model_validate(
        {
            **metadata,
            "sequence": len(events) + 1,
            "kind": KINDS[len(events)],
            "recorded_at": datetime.now(UTC).isoformat(),
            "previous_event_sha256": prior[-1][1] if prior else None,
        }
    )
    body = serialize(event)
    validate_chain([*prior, (body, digest(body))])
    store.read(event.tenant_id, event.payload_sha256)
    for prior_body, prior_sha in prior:
        if store.read(event.tenant_id, prior_sha) != prior_body:
            raise ValueError("v2_retained_event_mismatch")
    # Exclusive sequence reservation prevents replay/forking a retained session.
    slot = store.root / f"{event.tenant_id}-{event.session_id}-event-{event.sequence}"
    fd = os.open(slot, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(digest(body).encode())
        target.flush()
        os.fsync(target.fileno())
    return body, store.write(event.tenant_id, body)


def validate_chain(records: list[tuple[bytes, str]]) -> list[Event]:
    events = [decode(body, sha, Event) for body, sha in records]
    for i, event in enumerate(events):
        if event.sequence != i + 1 or (i and event.previous_event_sha256 != records[i - 1][1]):
            raise ValueError("v2_event_chain_mismatch")
        if i and (
            datetime.fromisoformat(event.recorded_at)
            < datetime.fromisoformat(events[i - 1].recorded_at)
            or any(
                getattr(event, key) != getattr(events[0], key)
                for key in [
                    "tenant_id",
                    "session_id",
                    "scope_sha256",
                    "engineering_commit",
                    "scorer_commit",
                    "identity_basis",
                ]
            )
        ):
            raise ValueError("v2_event_context_or_chronology")
        if i == 5 and event.payload_sha256 != events[1].payload_sha256:
            raise ValueError("v2_reveal_commitment_mismatch")
    return events


def prereveal(
    records: list[tuple[bytes, str]], trusted_head: str, store: Store
) -> tuple[Reference, str]:
    """Validate the first five events and retained bytes before parsing B at reveal."""
    if len(records) != 5 or records[-1][1] != trusted_head:
        raise ValueError("v2_pre_reveal_chain_required")
    events = validate_chain(records)
    tenant = events[0].tenant_id
    for event, (body, sha) in zip(events, records, strict=True):
        if (
            store.read(tenant, sha) != body
            or (store.root / f"{tenant}-{event.session_id}-event-{event.sequence}").read_text()
            != sha
        ):
            raise ValueError("v2_retained_event_mismatch")
    payloads = [store.read(tenant, e.payload_sha256) for e in events]
    scope_body = store.read(tenant, events[0].scope_sha256)
    scope = decode(scope_body, events[0].scope_sha256, Scope)
    if scope.tenant_id != tenant:
        raise ValueError("v2_protocol_tenant_mismatch")
    packet = decode(payloads[0], events[0].payload_sha256, SourcePacket)
    ref = decode(payloads[4], events[4].payload_sha256, Reference)
    if (
        packet.scope_sha256 != events[0].scope_sha256
        or events[2].payload_sha256 != events[0].payload_sha256
        or ref.scope_sha256 != packet.scope_sha256
        or ref.provenance.response_capture_sha256 != events[3].payload_sha256
        or ref.tenant_id != tenant
        or ref.revision != 1
        or ref.prediction_commitment_sha256 != events[1].payload_sha256
        or ref.blind_source_sha256 != events[0].payload_sha256
    ):
        raise ValueError("v2_handoff_capture_binding")
    store.read(tenant, ref.provenance.source_only_attestation_sha256)
    for sha in [scope.rights_evidence_sha256, scope.snapshot_verification_sha256]:
        store.read(tenant, sha)
    # B bytes have been hashed, not parsed or revealed. Reference must also pass source validation.
    return ref, events[1].payload_sha256


def reveal(
    records: list[tuple[bytes, str]],
    trusted_head: str,
    store: Store,
    source: Path,
    proofs: dict[str, bytes],
) -> Prediction:
    """Only after pre-reveal source validation, preserve event six, then parse original B."""
    from repovox.evaluation.v2 import validate_reference

    ref, prediction_hash = prereveal(records, trusted_head, store)
    events = validate_chain(records)
    first = events[0]
    scope_body = store.read(first.tenant_id, first.scope_sha256)
    scope = decode(scope_body, first.scope_sha256, Scope)
    validate_reference(
        store.read(first.tenant_id, events[4].payload_sha256),
        events[4].payload_sha256,
        scope,
        first.scope_sha256,
        source,
        proofs,
    )
    append_event(
        store,
        records,
        tenant_id=first.tenant_id,
        session_id=first.session_id,
        scope_sha256=first.scope_sha256,
        engineering_commit=first.engineering_commit,
        scorer_commit=first.scorer_commit,
        payload_sha256=prediction_hash,
        trusted_context=first.trusted_context,
        identity_basis=first.identity_basis,
    )
    prediction = decode(store.read(first.tenant_id, prediction_hash), prediction_hash, Prediction)
    if (
        prediction.scope_sha256 != ref.scope_sha256
        or prediction.engineering_commit != first.engineering_commit
    ):
        raise ValueError("v2_revealed_prediction_binding")
    return prediction


def compare_sealed(
    records: list[tuple[bytes, str]],
    trusted_head: str,
    store: Store,
    source: Path,
    proofs: dict[str, bytes],
) -> tuple[bytes, str]:
    """Future execution entrypoint. Only a retained post-reference reveal permits comparison."""
    from repovox.evaluation.scoring_v2 import score

    if len(records) != 6 or records[-1][1] != trusted_head:
        raise ValueError("v2_reveal_event_required")
    events = validate_chain(records)
    prereveal(records[:5], records[4][1], store)
    first, last = events[0], events[-1]
    if (
        store.read(first.tenant_id, trusted_head) != records[-1][0]
        or (store.root / f"{first.tenant_id}-{first.session_id}-event-6").read_text()
        != trusted_head
    ):
        raise ValueError("v2_reveal_event_changed")
    prediction_body = store.read(first.tenant_id, last.payload_sha256)
    prediction = decode(prediction_body, last.payload_sha256, Prediction)
    if prediction.engineering_commit != first.engineering_commit:
        raise ValueError("v2_revealed_prediction_binding")
    report = score(
        store.read(first.tenant_id, events[4].payload_sha256),
        events[4].payload_sha256,
        prediction_body,
        last.payload_sha256,
        store.read(first.tenant_id, first.scope_sha256),
        first.scope_sha256,
        source,
        proofs,
    )
    body = serialize(report)
    sha = store.write(first.tenant_id, body)
    append_event(
        store,
        records,
        tenant_id=first.tenant_id,
        session_id=first.session_id,
        scope_sha256=first.scope_sha256,
        engineering_commit=first.engineering_commit,
        scorer_commit=first.scorer_commit,
        payload_sha256=sha,
        trusted_context=first.trusted_context,
        identity_basis=first.identity_basis,
    )
    return body, sha

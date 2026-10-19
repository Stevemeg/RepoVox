"""Synthetic owner keys and responses ONLY; real restricted Linux custody processes.

Unit fixtures install a clearly synthetic closure binding. The PostgreSQL suite
exercises ReviewSession.establish against actual authenticated terminal rows.
"""

import base64
import json
import multiprocessing
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fcntl")

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_custodian_lifecycle import available_tick, fixture, record
from test_evaluation_v2 import case as case

from tools import phase2_custodian_watchdog as watchdog
from tools.phase2_custodian_adapter import CustodianStore, LeaseBoundExecutor
from tools.phase2_custodian_lifecycle import canonical, digest
from tools.phase2_custodian_review import OPERATIONS, ReviewSession

pytestmark = pytest.mark.skipif(os.geteuid() != 10002, reason="restricted custodian UID required")


def start_watchdog(life, parent):
    status = parent / ("status-" + uuid.uuid4().hex)
    status.mkdir(mode=0o700)
    config = parent / ("config-" + uuid.uuid4().hex)
    body = canonical(dict(root=str(life.root), plan=life.plan, receipt=life.receipt))
    config.write_bytes(body)
    config.chmod(0o600)
    command = [sys.executable, str(Path(watchdog.__file__).resolve()), str(config), str(status)]
    process = subprocess.Popen(
        command,
        env={**os.environ, "RV_CUSTODIAN_CONFIG_SHA256": digest(body)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    until = time.monotonic() + 5
    while not (status / "heartbeat.json").exists() and time.monotonic() < until:
        assert process.poll() is None, process.communicate()[1]
        time.sleep(0.02)
    probe = watchdog.LiveWatchdog(
        process.pid, command, status, digest(Path(watchdog.__file__).read_bytes())
    )
    probe.proof(life.plan)
    return process, probe


def sign(key, grant):
    return canonical(
        dict(grant=grant, signature=base64.b64encode(key.sign(canonical(grant))).decode())
    )


def grant_for(
    session, key, operation, payload, approval=b"SYNTHETIC OWNER APPROVAL ONLY", **changes
):
    binding = session.binding
    grant = dict(
        version="custody-review-authorization-1.0",
        binding_sha256=session.binding_sha,
        namespace=session.life.plan["namespace"],
        **{
            k: binding[k]
            for k in ["owner", "tenant", "attempt", "family", "scope_sha256", "prediction_sha256"]
        },
        operation=operation,
        input_sha256=digest(payload),
        previous_head=session.records()[-1][1],
        issued_at=datetime.now(UTC).isoformat(),
        expires_at=session.life.plan["authorization_expires_at"],
        nonce=uuid.uuid4().hex,
        approval_evidence_sha256=digest(approval),
    )
    grant.update(changes)
    return sign(key, grant), approval


@pytest.fixture
def review(case, tmp_path):
    root, scope, proofs, ref, pred = case
    life, token = fixture(
        tmp_path, tenant=scope.tenant_id, active=False, version="custodian-lifecycle-1.1"
    )
    process, probe = start_watchdog(life, tmp_path)
    life.activate(token, probe.proof(life.plan))
    # Fixture seeding only, not the concrete post-execution authorization boundary.
    store = CustodianStore(life, token, lambda p: True, lambda p: True, synthetic_fixture=True)
    for body in [
        serialize(scope),
        serialize(pred),
        *[body for sha, body in proofs.items() if sha != ref.provenance.response_capture_sha256],
        *[p.read_bytes() for p in root.glob("*.py")],
    ]:
        store.write(scope.tenant_id, body)
    metadata = dict(
        tenant_id=scope.tenant_id,
        session_id="synthetic-review",
        scope_sha256=ref.scope_sha256,
        engineering_commit=pred.engineering_commit,
        scorer_commit=pred.engineering_commit,
        trusted_context="SYNTHETIC ONLY",
        identity_basis="synthetic_fixture",
    )
    packet = proofs[ref.blind_source_sha256]
    records = []
    for body in [packet, serialize(pred)]:
        records.append(store.append_event(records, **metadata, payload_sha256=digest(body)))
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    binding = dict(
        version="custody-review-binding-1.0",
        plan_sha256=life.plan_sha,
        owner=scope.analysis_owner_id,
        tenant=scope.tenant_id,
        attempt=life.plan["attempt"],
        family=scope.family_id,
        scope_sha256=ref.scope_sha256,
        prediction_sha256=digest(serialize(pred)),
        source_packet_sha256=ref.blind_source_sha256,
        execution_head=records[1][1],
        closed_observed_at=datetime.now(UTC).isoformat(),
        owner_key_sha256=digest(public),
    )
    life.put(token, {"review-synthetic-review-binding": canonical(binding)})
    session = ReviewSession(
        life, token, "synthetic-review", public, digest(canonical(binding)), probe
    )
    value = SimpleNamespace(
        session=session,
        key=key,
        public=public,
        life=life,
        token=token,
        ref=ref,
        pred=pred,
        packet=packet,
        process=process,
        probe=probe,
        response=proofs[ref.provenance.response_capture_sha256],
    )
    try:
        yield value
    finally:
        if process.poll() is None:
            process.kill()
        _, stderr = process.communicate(timeout=5)
        record(
            "review-watchdog-exit",
            dict(
                namespace=life.plan["namespace"],
                exit_code=process.returncode,
                stderr=stderr.decode(errors="replace"),
                observed_at=datetime.now(UTC).isoformat(),
                synthetic_only=True,
            ),
        )


from repovox.evaluation.v2 import serialize  # noqa: E402


def advance(review, count=7):
    s = review.session
    for operation in OPERATIONS:
        if OPERATIONS[operation] > count:
            break
        payload = {
            "handoff": review.packet,
            "capture": review.response,
            "seal_reference": serialize(review.ref),
            "reveal": serialize(review.pred),
            "compare": serialize(review.ref),
            "close": s.records()[-1][0],
        }[operation]
        signed, approval = grant_for(s, review.key, operation, payload)
        output, ack = s.perform(signed, approval, payload)
        assert ack["output_sha256"] == digest(output)
        assert s.perform(signed, approval, payload) == (output, ack)
    return s.records()


def test_complete_synthetic_chronology_and_closure(review):
    initial = review.session.records()
    records = advance(review, 8)
    assert records[:2] == initial and len(records) == 7
    assert available_tick(review.life)["state"] == "SEALED"
    with pytest.raises(ValueError, match="lifecycle_not_executable"):
        review.life.put(review.token, {"extra": b"no"})
    record(
        "review-protocol",
        dict(
            events=[json.loads(b) for b, _ in records],
            deadline=review.life.plan["expires_at"],
            synthetic_only=True,
        ),
    )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("tenant", "tenant-b", "grant_tenant"),
        ("attempt", "wrong", "grant_attempt"),
        ("family", "wrong", "grant_family"),
        ("namespace", "wrong", "grant_namespace"),
        ("owner", "wrong", "grant_owner"),
        ("scope_sha256", "0" * 64, "grant_scope_sha256"),
        ("prediction_sha256", "0" * 64, "grant_prediction_sha256"),
        ("binding_sha256", "0" * 64, "grant_binding"),
        ("previous_head", "0" * 64, "review_head_changed"),
        ("operation", "execute", "grant_operation"),
        ("operation", "capture", "review_event_sequence"),
        ("operation", "reveal", "review_event_sequence"),
        ("operation", "compare", "review_event_sequence"),
    ],
)
def test_wrong_authority_and_binding(review, field, value, reason):
    before = review.session.records()
    signed, approval = grant_for(review.session, review.key, "handoff", review.packet)
    grant = json.loads(signed)["grant"]
    grant[field] = value
    signed = sign(review.key, grant)
    with pytest.raises(ValueError, match=reason):
        review.session.perform(signed, approval, review.packet)
    assert review.session.records() == before


@pytest.mark.parametrize("bad", ["signature", "approval", "payload", "expired", "key", "callback"])
def test_forgery_expiry_and_arbitrary_callback(review, bad):
    s = review.session
    signed, approval = grant_for(s, review.key, "handoff", review.packet)
    payload = review.packet
    if bad == "signature":
        packet = json.loads(signed)
        packet["grant"]["input_sha256"] = "0" * 64
        signed = canonical(packet)
    elif bad == "approval":
        approval = b"forged"
    elif bad == "payload":
        payload = b"changed"
    elif bad == "expired":
        signed, approval = grant_for(
            s,
            review.key,
            "handoff",
            payload,
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        )
    elif bad == "key":
        signed, approval = grant_for(s, Ed25519PrivateKey.generate(), "handoff", payload)
    else:
        with pytest.raises(ValueError, match="verified_watchdog_required"):
            ReviewSession(
                review.life, review.token, s.session, review.public, s.binding_sha, lambda: True
            )
        return
    with pytest.raises(ValueError):
        s.perform(signed, approval, payload)
    assert len(s.records()) == 2


def test_no_prediction_disclosure_and_reference_replacement(review):
    s = review.session
    signed, approval = grant_for(s, review.key, "handoff", serialize(review.pred))
    with pytest.raises(ValueError, match="source_only_handoff"):
        s.perform(signed, approval, serialize(review.pred))
    advance(review, 4)
    changed = review.ref.model_copy(update={"prediction_commitment_sha256": "0" * 64})
    payload = serialize(changed)
    signed, approval = grant_for(s, review.key, "seal_reference", payload)
    with pytest.raises(ValueError, match="independent_reference_binding"):
        s.perform(signed, approval, payload)
    advance_from = len(s.records())
    assert advance_from == 4


def test_replay_and_simultaneous_submission(review):
    s = review.session
    signed, approval = grant_for(s, review.key, "handoff", review.packet)
    ctx = multiprocessing.get_context("fork")
    workers = []
    for _ in range(2):

        def submit():
            try:
                s.perform(signed, approval, review.packet)
            except (ValueError, BlockingIOError):
                pass  # One winner; loser must not create a fork.

        process = ctx.Process(target=submit)
        process.start()
        workers.append(process)
    for process in workers:
        process.join(5)
        assert process.exitcode == 0
    assert len(s.records()) == 3
    assert s.perform(signed, approval, review.packet)[0] == review.packet
    changed = json.loads(signed)["grant"]
    changed["input_sha256"] = digest(b"replay changed payload")
    with pytest.raises(ValueError, match="authorization_replay"):
        s.perform(sign(review.key, changed), approval, b"replay changed payload")


@pytest.mark.parametrize("state", ["INVALIDATED", "WITHDRAWN", "SEALED"])
def test_terminal_custody_never_reopened(review, state):
    signed, approval = grant_for(review.session, review.key, "handoff", review.packet)
    review.life.transition(review.token, state)
    with pytest.raises(ValueError):
        review.session.perform(signed, approval, review.packet)
    with pytest.raises(ValueError):
        review.life.activate(review.token, review.probe.proof(review.life.plan))


def test_watchdog_crash_blocks_review(review):
    signed, approval = grant_for(review.session, review.key, "handoff", review.packet)
    review.process.kill()
    review.process.wait(5)
    with pytest.raises((ValueError, FileNotFoundError)):
        review.session.perform(signed, approval, review.packet)
    assert len(review.session.records()) == 2


def test_operation_deadline_recovery_cannot_promote_expired_intent(review, monkeypatch):
    life = review.life
    original = life._file

    def slow(name, *args):
        result = original(name, *args)
        if name == "expiring-operation":
            time.sleep(0.3)
        return result

    monkeypatch.setattr(life, "_file", slow)
    with pytest.raises(ValueError, match="operation_authorization_expired"):
        life.put(
            review.token,
            {"expiring-operation": b"synthetic partial operation"},
            operation_expires_at=(datetime.now(UTC) + timedelta(seconds=0.15)).isoformat(),
        )
    monkeypatch.setattr(life, "_file", original)
    # Actual watchdog may already have invalidated/deleted the expired intent.
    assert available_tick(life)["state"] in {"INVALIDATED", "EXPIRED"}
    assert available_tick(life)["state"] == "EXPIRED"
    assert not list(life.data.iterdir())


def test_execution_token_cannot_authorize_review(review):
    with pytest.raises(ValueError, match="grant_envelope"):
        review.session.perform(canonical(review.token), b"not an approval", review.packet)
    assert len(review.session.records()) == 2


def test_original_source_missing_blocks_handoff(review):
    signed, approval = grant_for(review.session, review.key, "handoff", review.packet)
    scope = json.loads(review.session._read(review.session.binding["scope_sha256"]))
    sha = scope["files"][0]["file_sha256"]
    (review.life.data / ("tenant-a-" + sha)).unlink()
    with pytest.raises(ValueError, match="registered_evidence_missing"):
        review.session.perform(signed, approval, review.packet)


def test_modified_sealed_reference_blocks_reveal(review):
    advance(review, 5)
    payload = serialize(review.pred)
    signed, approval = grant_for(review.session, review.key, "reveal", payload)
    (review.life.data / ("tenant-a-" + digest(serialize(review.ref)))).write_bytes(b"forged")
    with pytest.raises(ValueError, match="registered_evidence_corrupt"):
        review.session.perform(signed, approval, payload)


def test_crash_after_commit_retrieves_identical_ack_without_new_event(review):
    s = review.session
    signed, approval = grant_for(s, review.key, "handoff", review.packet)
    context = multiprocessing.get_context("fork")

    def crash():
        original = s.life.put

        def put(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(88)

        s.life.put = put
        s.perform(signed, approval, review.packet)

    process = context.Process(target=crash)
    process.start()
    process.join(5)
    assert process.exitcode == 88
    reopened = ReviewSession(
        review.life, review.token, s.session, review.public, s.binding_sha, review.probe
    )
    assert reopened.perform(signed, approval, review.packet)[0] == review.packet
    assert len(reopened.records()) == 3


def test_capture_authorization_expiry_is_fail_closed(review, monkeypatch):
    advance(review, 3)
    signed, approval = grant_for(
        review.session,
        review.key,
        "capture",
        review.response,
        expires_at=(datetime.now(UTC) + timedelta(seconds=0.4)).isoformat(),
    )
    original = review.life._file
    touched = []
    capture_slot = "review-use-" + json.loads(signed)["grant"]["nonce"]

    def delayed(name, *args):
        body = original(name, *args)
        if name == capture_slot:
            touched.append(name)
            time.sleep(0.5)
        return body

    monkeypatch.setattr(review.life, "_file", delayed)
    with pytest.raises(ValueError, match="operation_authorization_expired"):
        review.session.perform(signed, approval, review.response)
    monkeypatch.setattr(review.life, "_file", original)
    if touched:
        assert available_tick(review.life)["state"] in {"INVALIDATED", "EXPIRED"}
        assert available_tick(review.life)["state"] == "EXPIRED"
        assert not list(review.life.data.iterdir())
    else:
        # Bounded scheduling may expire the same unchanged grant at admission.
        # Earlier denial must have no response, nonce receipt or new custody event.
        assert available_tick(review.life)["state"] == "ACTIVE"
        assert len(review.session.records()) == 3
        assert not (review.life.data / capture_slot).exists()
        assert not (review.life.data / ("tenant-a-" + digest(review.response))).exists()
    record(
        "capture-expiry-boundary",
        dict(
            write_entered=bool(touched),
            reason="operation_authorization_expired",
            acknowledged=False,
        ),
    )


def test_comparison_requires_reveal_even_after_reference_sealing(review):
    advance(review, 5)
    payload = serialize(review.ref)
    signed, approval = grant_for(review.session, review.key, "compare", payload)
    with pytest.raises(ValueError, match="review_event_sequence"):
        review.session.perform(signed, approval, payload)
    assert len(review.session.records()) == 5


def test_close_crash_recovery_commits_seal_and_ack_together(review):
    advance(review, 7)
    session = review.session
    payload = session.records()[-1][0]
    signed, approval = grant_for(session, review.key, "close", payload)
    slot = "review-use-" + json.loads(signed)["grant"]["nonce"]

    def crash():
        original = session.life._file

        def last_file(name, *args):
            body = original(name, *args)
            if name == slot:
                os._exit(86)
            return body

        session.life._file = last_file
        session.perform(signed, approval, payload)

    process = multiprocessing.get_context("fork").Process(target=crash)
    process.start()
    process.join(5)
    assert process.exitcode == 86
    # Actual recovery must not leave an acknowledged close in ACTIVE custody.
    assert available_tick(review.life)["state"] == "SEALED"
    assert session.perform(signed, approval, payload)[0] == payload
    assert len(session.records()) == 7


def test_review_and_execution_authority_cannot_be_substituted(review, tmp_path):
    with pytest.raises(ValueError, match="authenticated_execution_gate_required"):
        CustodianStore(review.life, review.token, lambda p: True, lambda p: True)
    with pytest.raises(ValueError, match="authenticated_execution_gate_required"):
        LeaseBoundExecutor(review.session, review.key)
    with pytest.raises(ValueError, match="owner_key_substitution"):
        ReviewSession(
            review.life,
            review.token,
            review.session.session,
            Ed25519PrivateKey.generate().public_key().public_bytes_raw(),
            review.session.binding_sha,
            review.probe,
        )
    legacy, token = fixture(tmp_path, active=False)
    with pytest.raises(ValueError, match="review_lifecycle_required"):
        ReviewSession.establish(
            legacy,
            token,
            None,
            None,
            None,
            None,
            None,
            b"",
            b"",
            [],
            b"",
            {},
            review.probe,
        )
    assert legacy.tick()["state"] == "CREATED" and not list(legacy.data.iterdir())

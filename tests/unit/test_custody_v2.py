"""Synthetic private-store and blind-protocol controls; no historical packets accessed."""

import os
from pathlib import Path

import pytest
from repovox.evaluation.custody_v2 import (
    Event,
    Store,
    append_event,
    compare_sealed,
    prereveal,
    reveal,
    source_packet,
    validate_chain,
)
from repovox.evaluation.v2 import digest, serialize
from test_evaluation_v2 import case as case


@pytest.fixture
def private(case):
    if os.name != "posix":
        pytest.skip("Actual POSIX store runs in mandatory Linux suite.")
    root = case[0] / "private"
    root.mkdir(mode=0o700)
    return Store(root, Path(__file__).resolve().parents[2], "tenant-a", os.getuid() + 1)


def history(case, private, engineering_commit=None):
    root, scope, proofs, ref, pred = case
    values = list(proofs.values()) + [serialize(scope), serialize(pred), serialize(ref)]
    for body in values:
        private.write(scope.tenant_id, body)
    packet = source_packet(serialize(scope), digest(serialize(scope)), root, proofs)
    a = digest(serialize(packet))
    assert private.read(scope.tenant_id, a) == serialize(packet)
    payloads = [
        a,
        digest(serialize(pred)),
        a,
        ref.provenance.response_capture_sha256,
        digest(serialize(ref)),
    ]
    records = []
    for payload in payloads:
        records.append(
            append_event(
                private,
                records,
                tenant_id=scope.tenant_id,
                session_id="synthetic-blind-session",
                scope_sha256=ref.scope_sha256,
                engineering_commit=engineering_commit or pred.engineering_commit,
                scorer_commit="e" * 40,
                payload_sha256=payload,
                trusted_context="synthetic-test-process",
                identity_basis="synthetic_fixture",
            )
        )
    return records


def test_source_packet_has_no_prediction_fields(case):
    root, scope, proofs, _, _ = case
    packet = source_packet(serialize(scope), digest(serialize(scope)), root, proofs)
    assert set(packet.model_dump()) == {"schema_version", "scope_sha256", "excerpts", "policy"}
    assert packet.excerpts[0].numbered_source.startswith("1: from .cargo import Crate")


def test_private_original_bytes_immutable_and_cross_tenant_denied(private):
    body = b' {"independent": "original bytes"}\n'
    key = private.write("tenant-a", body)
    assert private.read("tenant-a", key) == body
    assert (private.root / ("tenant-a-" + key)).stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        private.write("tenant-a", body)
    with pytest.raises(ValueError, match="tenant_denied"):
        private.read("tenant-b", key)
    with pytest.raises(ValueError, match="tenant_denied"):
        private.write("tenant-b", body)
    (private.root / ("tenant-a-" + key)).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="private_evidence_changed"):
        private.read("tenant-a", key)


def test_real_store_permissions_and_overlap_denied(private):
    private.root.chmod(0o755)
    with pytest.raises(ValueError, match="permissions"):
        private.write("tenant-a", b"data")
    private.root.chmod(0o700)
    with pytest.raises(ValueError, match="overlaps_git"):
        Store(private.root, private.root, "tenant-a", os.getuid() + 1)
    with pytest.raises(ValueError, match="identity_overlap"):
        Store(private.root, Path("/workspace"), "tenant-a", os.getuid())


def test_blind_chronology_and_actual_capture_required(case, private):
    records = history(case, private)
    ref, bhash = prereveal(records, records[-1][1], private)
    assert bhash == digest(serialize(case[4])) and ref.annotation_scope == "complete"
    for length in [0, 1, 2, 3, 4]:
        with pytest.raises(ValueError, match="pre_reveal"):
            prereveal(records[:length], records[-1][1], private)
    capture = private.root / ("tenant-a-" + ref.provenance.response_capture_sha256)
    capture.unlink()
    with pytest.raises(FileNotFoundError):
        prereveal(records, records[-1][1], private)


def test_reveal_validates_source_before_opening_prediction(case, private):
    records = history(case, private)
    (case[0] / "main.py").write_bytes(b"changed")
    with pytest.raises(ValueError, match="source_hash_mismatch"):
        reveal(records, records[-1][1], private, case[0], case[2])
    assert not (private.root / "tenant-a-synthetic-blind-session-event-6").exists()


def test_synthetic_reveal_and_repeat_rejection(case, private):
    records = history(case, private)
    pred = reveal(records, records[-1][1], private, case[0], case[2])
    assert pred == case[4]
    with pytest.raises(ValueError, match="reveal_event_required"):
        compare_sealed(records, records[-1][1], private, case[0], case[2])
    event_sha = (private.root / "tenant-a-synthetic-blind-session-event-6").read_text()
    revealed = [*records, (private.read("tenant-a", event_sha), event_sha)]
    body, report_sha = compare_sealed(revealed, event_sha, private, case[0], case[2])
    assert private.read("tenant-a", report_sha) == body
    with pytest.raises(FileExistsError):
        compare_sealed(revealed, event_sha, private, case[0], case[2])
    with pytest.raises(FileExistsError):
        reveal(records, records[-1][1], private, case[0], case[2])


@pytest.mark.parametrize("mutation", ["timestamp", "tenant", "sequence", "previous", "hash"])
def test_chain_tampering_rejected(case, private, mutation):
    records = history(case, private)
    event = Event.model_validate_json(records[2][0])
    if mutation == "timestamp":
        event.recorded_at = "2000-01-01T00:00:00+00:00"
    elif mutation == "tenant":
        event.tenant_id = "tenant-b"
    elif mutation == "sequence":
        event.sequence = 7
    elif mutation == "previous":
        event.previous_event_sha256 = "f" * 64
    body = serialize(event)
    records[2] = (body, digest(body) if mutation != "hash" else "f" * 64)
    with pytest.raises(ValueError):
        validate_chain(records)


def test_windows_store_not_falsely_claimed(tmp_path):
    if os.name == "posix":
        pytest.skip("Windows-specific fail-closed check.")
    with pytest.raises(ValueError, match="posix_boundary"):
        Store(tmp_path, Path(__file__).parents[2], "tenant-a", 10001)


def test_compare_rechecks_frozen_engineering_even_without_reveal_helper(case, private):
    records = history(case, private, engineering_commit="f" * 40)
    first = Event.model_validate_json(records[0][0])
    records.append(
        append_event(
            private,
            records,
            tenant_id=first.tenant_id,
            session_id=first.session_id,
            scope_sha256=first.scope_sha256,
            engineering_commit=first.engineering_commit,
            scorer_commit=first.scorer_commit,
            payload_sha256=digest(serialize(case[4])),
            trusted_context="synthetic-test-process",
            identity_basis="synthetic_fixture",
        )
    )
    with pytest.raises(ValueError, match="revealed_prediction_binding"):
        compare_sealed(records, records[-1][1], private, case[0], case[2])


def test_compare_rejects_changed_reveal_reservation(case, private):
    records = history(case, private)
    reveal(records, records[-1][1], private, case[0], case[2])
    slot = private.root / "tenant-a-synthetic-blind-session-event-6"
    sha = slot.read_text()
    records.append((private.read("tenant-a", sha), sha))
    slot.write_text("f" * 64)
    with pytest.raises(ValueError, match="reveal_event_changed"):
        compare_sealed(records, sha, private, case[0], case[2])


def test_symlinked_source_and_private_evidence_rejected(case, private):
    from repovox.evaluation.v2 import source_bytes

    original = case[0] / "main.py"
    original.rename(case[0] / "renamed.py")
    original.symlink_to(case[0] / "renamed.py")
    with pytest.raises(ValueError, match="source_containment"):
        source_bytes(case[0], case[1], case[2])
    (private.root / "link").symlink_to(original)
    with pytest.raises(ValueError, match="permissions_or_links"):
        private.write("tenant-a", b"synthetic")

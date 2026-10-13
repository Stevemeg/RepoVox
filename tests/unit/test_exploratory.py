"""Synthetic exploratory workflow tests, never independent AI/human review evidence."""

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError
from repovox.analysis.common import AnalysisError
from repovox.analysis.filtering import filter_sources
from repovox.evaluation.corpus import checksum, serialize
from repovox.evaluation.exploratory import (
    AIReference,
    BlindPacket,
    Policy,
    PredictionPacket,
    blind_packet,
    capture_response,
    checked_bytes,
    compare_reference,
    restrict_source_scope,
    scoped_prediction,
    seal_packet,
    validate_pinned_tree,
    write_immutable,
)
from test_evaluation_path import path_case as source_fixture


@pytest.fixture
def path_case(tmp_path: Path) -> tuple:
    return source_fixture.__wrapped__(tmp_path)


@pytest.fixture
def packets(path_case: tuple, tmp_path: Path) -> tuple:
    source, family, payload = path_case
    manifest = filter_sources(source, family.repository, family.commit_sha, "a" * 64)
    rights = {
        "repository": family.repository,
        "commit_sha": family.commit_sha,
        "decision": "PERMITTED_INTERNAL_EXPLORATORY",
        "summary": "SYNTHETIC TEST ONLY",
    }
    packet = blind_packet(
        source,
        family.repository,
        family.commit_sha,
        manifest,
        rights,
        {"main.py": (1, None), "helper.py": (1, None)},
    )
    prediction = PredictionPacket(
        schema_version="exploratory-sealed-prediction-1.0",
        policy=Policy(),
        repository=family.repository,
        commit_sha=family.commit_sha,
        rights_evidence_sha256=packet.rights_evidence_sha256,
        selected_scope=[
            {"path": e.path, "start_line": e.start_line, "end_line": e.end_line}
            for e in packet.excerpts
        ],
        original_artifacts=[],
        verified_payload=payload,
        metrics={"synthetic_test_only": True},
    )
    root = tmp_path / "private"
    b = seal_packet(root, "B", prediction.model_dump())
    a = seal_packet(root, "A", packet.model_dump())
    return source, family, packet, prediction, root, a, b


@pytest.mark.parametrize(
    "field",
    [
        "independently_human_reviewed",
        "official_eval_entry_contribution",
        "held_out_benchmark",
        "full_corpus_freeze",
        "production_accuracy_certification",
        "training_authorized",
    ],
)
def test_no_official_or_training_policy(field: str) -> None:
    with pytest.raises(ValidationError):
        Policy.model_validate({field: True})


def test_source_packet_excludes_predictions(packets: tuple) -> None:
    _, _, packet, _, _, _, _ = packets
    data = packet.model_dump()
    assert all("claims" not in entry for entry in data["inventory"])
    assert packet.excerpts[0].numbered_excerpt.startswith("1: import helper")
    for poisoned in [
        {**data, "predictions": []},
        {**data, "inventory": [{**data["inventory"][0], "verdict": "verified"}]},
    ]:
        with pytest.raises(ValueError):
            BlindPacket.model_validate(poisoned)


@pytest.mark.parametrize("problem", ["pin", "rights", "missing", "range", "modified"])
def test_blind_source_intake_failures(path_case: tuple, problem: str) -> None:
    source, family, _ = path_case
    manifest = filter_sources(source, family.repository, family.commit_sha, "a" * 64)
    rights = {
        "repository": family.repository,
        "commit_sha": family.commit_sha,
        "decision": "PERMITTED_INTERNAL_EXPLORATORY",
        "summary": "test",
    }
    selected = {"main.py": (1, None)}
    if problem == "pin":
        rights["commit_sha"] = "b" * 40
    if problem == "rights":
        rights["decision"] = "PENDING"
    if problem == "missing":
        selected = {"missing.py": (1, None)}
    if problem == "range":
        selected = {"main.py": (1, 999)}
    if problem == "modified":
        (source / "main.py").write_bytes(b"changed\n")
    with pytest.raises(ValueError):
        blind_packet(source, family.repository, family.commit_sha, manifest, rights, selected)


def test_sealed_predictions_cannot_be_silently_replaced(packets: tuple) -> None:
    _, _, _, prediction, root, _, b = packets
    body = checked_bytes(root, b["path"], b["sha256"])
    assert json.loads(body)["reference_included"] is False
    with pytest.raises(ValueError, match="already_sealed"):
        seal_packet(root, "B", prediction.model_dump())
    (root / b["path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sealed_content_changed"):
        checked_bytes(root, b["path"], b["sha256"])


def reference(packets: tuple, capture: str) -> AIReference:
    _, family, _, _, _, a, b = packets
    from repovox.evaluation.gold import GoldEvaluation

    gold = GoldEvaluation.model_validate(
        family.model_dump(include=set(GoldEvaluation.model_fields))
    )
    return AIReference(
        schema_version="exploratory-ai-reference-1.0",
        policy=Policy(),
        reviewer="ChatGPT",
        blind_packet_sha256=a["sha256"],
        prediction_packet_sha256=b["sha256"],
        response_capture_sha256=capture,
        gold=gold,
        semantic_observations=[],
        limitations=["SIMULATED REVIEW TEST; no actual independent AI reference"],
    )


def test_reference_needs_original_capture_and_chronology(packets: tuple) -> None:
    _, _, _, _, root, _, _ = packets
    ref = reference(packets, "a" * 64)
    with pytest.raises(FileNotFoundError):
        seal_packet(root, "REFERENCE", ref.model_dump())
    capture = capture_response(root, b"SIMULATED TEST response; not an actual review")
    ref = reference(packets, capture)
    seal_packet(root, "REFERENCE", ref.model_dump())
    event = root / "review/capture-event.json"
    event.write_bytes(serialize({"sha256": capture, "recorded_at": "1900-01-01"}))
    with pytest.raises(ValueError, match="chronology"):
        seal_packet(root, "REFERENCE", ref.model_dump())
    for identity in ["Actual Human", "Codex"]:
        with pytest.raises(ValidationError):
            AIReference.model_validate({**ref.model_dump(), "reviewer": identity})


def test_existing_scorer_requires_full_pairing(packets: tuple) -> None:
    source, _, packet, prediction, root, _, _ = packets
    ref = reference(packets, capture_response(root, b"Synthetic reference test capture"))
    seal_packet(root, "REFERENCE", ref.model_dump())
    report = compare_reference(ref, packet, prediction, source, root)
    assert report["score"]["pairing_status"] == "COMPLETE"
    assert report["independent_acceptance"] == "REVIEW_REQUIRED"
    previous_digest = checksum(serialize(ref.model_dump()))
    ref.gold.claims.pop()
    ref.revision = 2
    ref.supersedes_sha256 = previous_digest
    ref.correction_explanation = "Synthetic correction test: deliberately incomplete reference"
    ref.correction_citations = ref.gold.claims[0].citations
    seal_packet(root, "REFERENCE", ref.model_dump())
    assert (
        compare_reference(ref, packet, prediction, source, root)["score"]["pairing_status"]
        == "INCOMPLETE"
    )
    assert checksum(serialize(prediction.model_dump())) == ref.prediction_packet_sha256


def test_unsealed_reference_cannot_score(packets: tuple) -> None:
    source, _, packet, prediction, root, _, _ = packets
    ref = reference(packets, "a" * 64)
    with pytest.raises(FileNotFoundError):
        compare_reference(ref, packet, prediction, source, root)


def test_silent_reference_correction_rejected(packets: tuple) -> None:
    _, _, _, _, root, _, _ = packets
    ref = reference(packets, capture_response(root, b"Synthetic test review capture only"))
    seal_packet(root, "REFERENCE", ref.model_dump())
    ref.gold.claims.pop()
    with pytest.raises(ValueError, match="correction_lineage"):
        seal_packet(root, "REFERENCE", ref.model_dump())


def test_prediction_cross_repository_contamination_rejected(packets: tuple) -> None:
    _, _, _, prediction, _, _, _ = packets
    data = prediction.model_dump()
    data["repository"] = "synthetic/other"
    with pytest.raises(ValidationError, match="snapshot_mismatch"):
        PredictionPacket.model_validate(data)


@pytest.mark.parametrize("problem", ["forged_evidence", "duplicate", "unknown_subject"])
def test_scope_cannot_hide_forged_predictions(packets: tuple, problem: str) -> None:
    _, _, packet, prediction, _, _, _ = packets
    payload = deepcopy(prediction.verified_payload)
    if problem == "forged_evidence":
        payload["knowledge"]["claims"][0]["evidence_ids"] = ["forged"]
    if problem == "duplicate":
        payload["knowledge"]["claims"].append(payload["knowledge"]["claims"][0])
    if problem == "unknown_subject":
        payload["knowledge"]["claims"][0]["subject_id"] = "invented"
    with pytest.raises(ValueError):
        scoped_prediction(payload, packet)


def test_pinned_blob_inventory_detects_source_changes(path_case: tuple) -> None:
    import hashlib

    source, _, _ = path_case
    tree = {
        "truncated": False,
        "tree": [
            {
                "path": p.name,
                "type": "blob",
                "sha": hashlib.sha1(
                    f"blob {len(p.read_bytes())}\0".encode() + p.read_bytes()
                ).hexdigest(),
            }
            for p in source.iterdir()
        ],
    }
    validate_pinned_tree(source, tree)
    (source / "main.py").write_bytes(b"changed after pin")
    with pytest.raises(ValueError, match="pinned_source_blob_changed"):
        validate_pinned_tree(source, tree)
    tree["truncated"] = True
    with pytest.raises(ValueError):
        validate_pinned_tree(source, tree)


def test_scope_preserves_hashes_and_default_pipeline(path_case: tuple) -> None:
    from repovox.analysis.runner import AnalysisRunner

    source, family, _ = path_case
    manifest = filter_sources(source, family.repository, family.commit_sha, "a" * 64)
    assert AnalysisRunner(None, None).preparation_filter(manifest) is manifest
    scoped = restrict_source_scope(manifest, frozenset({"main.py"}))
    assert scoped["eligible_files"] == 1 and manifest["eligible_files"] == 2
    assert [f["file_sha256"] for f in scoped["files"]] == [
        f["file_sha256"] for f in manifest["files"]
    ]
    assert "outside_selected_scope" in scoped["files"][0]["reason"]
    with pytest.raises(ValueError):
        restrict_source_scope(manifest, frozenset({"absent.py"}))


def test_nested_immutable_permissions_and_traversal(tmp_path: Path) -> None:
    root = tmp_path / "private"
    write_immutable(root, "nested/deep/object.json", b"test")
    if os.name == "posix":
        assert all(p.stat().st_mode & 0o077 == 0 for p in [root, *root.rglob("*")])
    with pytest.raises(FileExistsError):
        write_immutable(root, "nested/deep/object.json", b"replace")
    with pytest.raises(AnalysisError):
        write_immutable(root, "../escape", b"test")

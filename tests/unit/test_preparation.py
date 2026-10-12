"""Synthetic algorithm tests only. No real rights, human review or corpus admission.

Even the full-sized freeze payload uses conspicuously synthetic identities/evidence.
It never enters the official manifest or counts as independently reviewed gold.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from repovox.analysis.filtering import filter_sources
from repovox.evaluation.corpus import (
    Appointment,
    Corpus,
    Family,
    checksum,
    counts,
    freeze,
    serialize,
    validate_labels,
    withdraw,
)
from repovox.evaluation.preparation import (
    Candidate,
    Catalog,
    GatePacket,
    ReviewSeal,
    VariantReview,
    annotation_digest,
    grouping_suggestions,
    human_id,
    language_slice,
    readiness,
    source_fingerprints,
    verify_boundary,
)


def empty() -> Corpus:
    return Corpus.model_validate_json(Path("docs/ai/evaluation-corpus.manifest.json").read_bytes())


def candidate() -> dict:
    return json.loads(Path("docs/ai/evaluation-candidates.json").read_bytes())["candidates"][0]


@pytest.mark.parametrize("name", ["", "Codex", "ChatGPT", "assistant-rater", "AI", "bot"])
def test_nonhuman_reviewer_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="actual_human"):
        human_id(name)


@pytest.mark.parametrize("status", ["rights_reviewed", "owner_approved"])
def test_rights_intake_requires_real_permission_evidence(status: str) -> None:
    record = candidate()
    record["rights_status"] = status
    with pytest.raises(ValidationError, match="rights_evidence"):
        Candidate.model_validate(record)


def test_missing_reviewer_permission_rejected() -> None:
    record = candidate()
    record.update(
        rights_status="owner_approved",
        rights_review_sha256="a" * 64,
        owner_approval_sha256="b" * 64,
        permission_evidence_sha256="c" * 64,
    )
    with pytest.raises(ValidationError, match="owner_permission"):
        Candidate.model_validate(record)


def test_candidate_pending_or_rejected_never_counts_approved() -> None:
    record = candidate()
    for status in ["pending", "rejected"]:
        record["rights_status"] = status
        catalog = Catalog(
            schema_version="evaluation-candidates-1.0",
            captured_on="test",
            candidates=[Candidate.model_validate(record)],
        )
        report = readiness(empty(), catalog)
        assert report["candidate_owner_approved_records"] == 0
        assert not any(report["verified_approved_counts"].values())
        assert not report["freeze_eligible"]


def test_duplicate_candidate_family_rejected() -> None:
    record = Candidate.model_validate(candidate())
    with pytest.raises(ValidationError, match="duplicate_candidate"):
        Catalog(
            schema_version="evaluation-candidates-1.0",
            captured_on="test",
            candidates=[record, record],
        )


@pytest.mark.parametrize("model", [ReviewSeal, VariantReview])
def test_same_preparer_reviewer_forbidden(model: type) -> None:
    base = {
        "family_id": "synthetic",
        "preparer_id": "SyntheticHuman",
        "reviewer_id": "synthetichuman",
        "approval_sha256": "a" * 64,
    }
    if model is ReviewSeal:
        base.update(annotation_sha256="b" * 64, claim_ids=[], edge_ids=[])
    else:
        base.update(
            id="variant",
            parent_commit_sha="a" * 40,
            recipe_sha256="b" * 64,
            materialized_manifest_sha256="c" * 64,
            expected_outcome="abstention",
            expectations_sha256="d" * 64,
        )
    with pytest.raises(ValidationError, match="self_review"):
        model.model_validate(base)


def test_language_classification_uses_screened_source() -> None:
    def manifest(*languages: str) -> dict:
        return {"files": [{"language": language, "status": "eligible"} for language in languages]}

    assert language_slice(manifest("python")) == "python"
    assert language_slice(manifest("typescript")) == "javascript_typescript"
    assert language_slice(manifest("python", "javascript")) == "mixed"
    with pytest.raises(ValueError, match="no_supported"):
        language_slice(manifest("rust"))


def test_official_readiness_stays_zero() -> None:
    catalog = Catalog.model_validate_json(Path("docs/ai/evaluation-candidates.json").read_bytes())
    report = readiness(empty(), catalog)
    assert report["candidate_families"] == 7
    assert report["reviewer_appointment"] == "PENDING"
    assert not report["freeze_eligible"]
    assert sum(report["verified_approved_counts"].values()) == 0


def test_contamination_suggestions_do_not_modify_original_citations(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "app.py").write_bytes(b"def small(x): return x\n")
    (second / "app.py").write_bytes(b"def small(x):\n    return x\n")
    a, b = source_fingerprints(first), source_fingerprints(second)
    assert a[0]["original_sha256"] != b[0]["original_sha256"]
    assert a[0]["whitespace_normalized_sha256"] == b[0]["whitespace_normalized_sha256"]
    assert grouping_suggestions({"one": a, "two": b}) == [["one", "two"]]


def synthetic_case(root: Path, size: int = 80) -> tuple[Corpus, dict[str, Path], Path, Path]:
    """Generate trusted TEST inputs and simulated approvals, never human-authored works."""
    root.mkdir(mode=0o700)
    proof = root / "provenance"
    proof.mkdir(mode=0o700)

    def put(value: object) -> str:
        body = serialize(value)
        digest = checksum(body)
        file = proof / digest
        if not file.exists():
            file.write_bytes(body)
        file.chmod(0o600)
        return digest

    generic = put({"synthetic_algorithm_test_only": True, "no_actual_human_approval": True})
    corpus = empty()
    corpus.version = "synthetic-freeze-algorithm-test"
    corpus.appointment = Appointment.model_validate(
        {
            "reviewer_id": "synthetic-reviewer",
            "type": "actual_human",
            "owner_appointment_sha256": generic,
            "rights_access_sha256": generic,
        }
    )
    corpus.reviewer_status = "SYNTHETIC ALGORITHM TEST ONLY"
    corpus.access_policy_sha256 = corpus.contamination_manifest_sha256 = generic
    corpus.deletion_policy_sha256 = generic
    corpus.dependent_reports = ["synthetic-report"]
    packet = {
        "schema_version": "eval-entry-preparation-1.0",
        "catalog": {
            "schema_version": "evaluation-candidates-1.0",
            "captured_on": "test",
            "candidates": [],
        },
        "reviews": [],
        "variants": [],
        "hidden_authorship": [],
        "worker_uid": 10002 if getattr(os, "getuid", lambda: -1)() != 10002 else 10003,
        "operational_access_review_sha256": generic,
        "budget_approval_sha256": generic,
        "retention_access_approval_sha256": generic,
    }
    sources = {}
    for index in range(size):
        family_id = f"synthetic-family-{index}"
        directory = root / family_id
        directory.mkdir(mode=0o700)
        source = directory / "source"
        source.mkdir(mode=0o700)
        sources[family_id] = source
        sha = f"{index + 1:040x}"  # Synthetic snapshot, not an actual repository SHA.
        slice_name = "python" if index < 40 else "javascript_typescript" if index < 60 else "mixed"
        paths = ["main.py"] if slice_name == "python" else ["main.js"]
        if slice_name == "mixed":
            paths = ["main.py", "main.js"]
        symbols = []
        for path in paths:
            python = path.endswith(".py")
            body = (
                "\n".join(
                    f"def function_{index}_{j}(value): return value + {j}"
                    if python
                    else f"function function_{index}_{j}(value) {{ return value + {j}; }}"
                    for j in range(8)
                ).encode()
                + b"\n"
            )
            (source / path).write_bytes(body)
            for j in range(8):
                symbols.append(
                    {
                        "id": f"symbol-{path}-{j}",
                        "path": path,
                        "file_sha256": checksum(body),
                        "start_line": j + 1,
                        "end_line": j + 1,
                        "kind": "function",
                        "name": f"function_{index}_{j}",
                        "language": "python" if python else "javascript",
                        "rule": "declaration-v1",
                        "attributes": {"parameters": ["value"]},
                    }
                )
        manifest = serialize(filter_sources(source, f"synthetic/{family_id}", sha, generic))
        (directory / "source_manifest.json").write_bytes(manifest)
        identities = [{k: v for k, v in s.items() if k != "id"} for s in symbols]
        # Two static syntax relationships manually specified, not copied from an analyzer.
        # Test-only support; semantic adjudication is explicitly outside this algorithm test.
        edges = [
            {
                "id": f"edge-{j}",
                "source": identities[0],
                "target": identities[j + 1],
                "relationship": "synthetic_test_relation",
                "classification": "declared",
                "support": [identities[j + 1]],
                "supported": True,
                "citations": [
                    {
                        k: identities[j + 1][k]
                        for k in ["path", "file_sha256", "start_line", "end_line"]
                    }
                ],
            }
            for j in range(2)
        ]
        claims = [
            {
                "id": f"claim-{j}",
                "text": "Synthetic test syntax; no runtime assertion.",
                "status": "verified",
                "fact": {"type": "symbol_syntax", "symbol": identity},
                "citations": [
                    {k: identity[k] for k in ["path", "file_sha256", "start_line", "end_line"]}
                ],
            }
            for j, identity in enumerate(identities)
        ]
        family = Family.model_validate(
            {
                "gold_schema_version": "gold-evaluation-1.0",
                "repository": f"synthetic/{family_id}",
                "commit_sha": sha,
                "annotation_scope": "complete",
                "symbols": symbols,
                "entrypoints": [],
                "edges": edges,
                "claims": claims,
                "safety_observations": {"test": "SYNTHETIC; no actual reviewer or official gold"},
                "id": family_id,
                "language_slice": slice_name,
                "split": "EVAL_DEV" if index < 20 else "EVAL_TEST",
                "hidden": 20 <= index < 30,
                "newly_owner_authored": 20 <= index < 30,
                "derivatives": [],
                "family_grouping_evidence_sha256": generic,
                "source_manifest_sha256": checksum(manifest),
                "content_fingerprints": sorted(
                    {f["file_sha256"] for f in json.loads(manifest)["files"]}
                ),
                "rights": {
                    "basis": "explicit_evaluation_permission",
                    "license_id": "SYNTHETIC TEST",
                    "license_text_sha256": generic,
                    "permission_evidence_sha256": generic,
                    "attribution": "Test algorithm only",
                    "retention_days": 1,
                    "reviewer_access_permitted": True,
                    "redistribution_permitted": False,
                    "approved_by_owner": True,
                },
                "screening": "clear",
                "adversarial_variants": [],
                "gold_review": {
                    "preparer_id": "synthetic-preparer",
                    "reviewer_id": "synthetic-reviewer",
                    "source_review_sha256": generic,
                    "adjudication_sha256": generic,
                    "approval_evidence_sha256": generic,
                    "approved": True,
                },
            }
        )
        if 20 <= index < 40:
            for variant_index in range(5):
                variant_id = f"synthetic-variant-{index}-{variant_index}"
                family.adversarial_variants.append(variant_id)
                variant_source = directory / "variants" / variant_id / "source"
                variant_source.mkdir(parents=True, mode=0o700)
                variant_body = (
                    f"# synthetic adversarial workflow case {index} {variant_index}\n".encode()
                )
                (variant_source / "main.py").write_bytes(variant_body)
                materialized = put(
                    {
                        "parent_commit_sha": sha,
                        "files": [{"path": "main.py", "file_sha256": checksum(variant_body)}],
                    }
                )
                packet["variants"].append(
                    {
                        "id": variant_id,
                        "family_id": family_id,
                        "parent_commit_sha": sha,
                        "recipe_sha256": generic,
                        "materialized_manifest_sha256": materialized,
                        "expected_outcome": "abstention",
                        "expectations_sha256": generic,
                        "preparer_id": "synthetic-preparer",
                        "reviewer_id": "synthetic-reviewer",
                        "approval_sha256": generic,
                    }
                )
        record = candidate()
        record.update(
            family_id=family_id,
            repository=family.repository,
            url=f"https://github.com/{family.repository}",
            commit_sha=sha,
            language_slice=slice_name,
            license_text_sha256=generic,
            permission_evidence_sha256=generic,
            reviewer_access="permitted",
            rights_status="owner_approved",
            rights_review_sha256=generic,
            owner_approval_sha256=generic,
        )
        packet["catalog"]["candidates"].append(record)
        seal = {
            "family_id": family_id,
            "annotation_sha256": annotation_digest(family),
            "preparer_id": "synthetic-preparer",
            "reviewer_id": "synthetic-reviewer",
            "claim_ids": [c.id for c in family.claims],
            "edge_ids": [e.id for e in family.edges],
        }
        approval = put(
            {
                **seal,
                "schema_version": "gold-review-receipt-1.0",
                "source_checked": True,
                "approved": True,
                "unresolved_disagreements": 0,
            }
        )
        family.gold_review.approval_evidence_sha256 = approval
        packet["reviews"].append({**seal, "approval_sha256": approval})
        if family.newly_owner_authored:
            packet["hidden_authorship"].append(
                {
                    "family_id": family_id,
                    "author_id": "Stevemeg",
                    "genuinely_owner_authored": True,
                    "newly_authored": True,
                    "provenance_sha256": generic,
                    "owner_declaration_sha256": generic,
                    "reviewer_confirmation_sha256": generic,
                }
            )
        corpus.families.append(family)
    corpus = Corpus.model_validate(corpus.model_dump())
    packet_file = root / "preparation.json"
    packet_file.write_bytes(serialize(GatePacket.model_validate(packet).model_dump()))
    for path in root.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    return corpus, sources, proof, packet_file


@pytest.fixture
def full_case(tmp_path: Path) -> tuple:
    if os.name != "posix":
        pytest.skip("Actual POSIX freeze is exercised by the mandatory Linux service/CI suite.")
    return synthetic_case(tmp_path / "protected")


def test_successful_full_sized_synthetic_freeze_only(full_case: tuple) -> None:
    frozen = freeze(*full_case)
    assert frozen.status == "FROZEN" and frozen.freeze_sha256
    assert frozen.version == "synthetic-freeze-algorithm-test"
    actual = counts(frozen)
    assert actual["development"] == 20 and actual["held_out"] == 60
    assert actual["adversarial_variants"] == 100 and actual["gold_claims"] >= 600
    assert empty().status == "UNFROZEN" and not empty().families
    reloaded = Corpus.model_validate_json(serialize(frozen.model_dump()))
    withdrawn = withdraw(reloaded, "synthetic-family-20")
    assert withdrawn.status == "WITHDRAWN" and withdrawn.invalidated_reports == ["synthetic-report"]
    with pytest.raises(ValueError):
        freeze(withdrawn, *full_case[1:])
    corpus, sources, provenance, preparation = full_case
    manifest = provenance.parent / "synthetic-manifest.json"
    manifest.write_bytes(serialize(corpus.model_dump()))
    manifest.chmod(0o600)
    output = provenance.parent / "synthetic-frozen-record.json"
    command = [
        sys.executable,
        "tools/phase2_corpus.py",
        str(manifest),
        "--action",
        "freeze",
        "--source",
        str(provenance.parent),
        "--provenance",
        str(provenance),
        "--preparation",
        str(preparation),
        "--output",
        str(output),
    ]
    subprocess.run(command, check=True, capture_output=True)
    record = json.loads(output.read_bytes())
    assert record["schema_version"] == "eval-entry-freeze-record-1.0"
    assert record["preparation_sha256"] == checksum(preparation.read_bytes())
    assert record["corpus"]["freeze_sha256"] == frozen.freeze_sha256
    assert subprocess.run(command, capture_output=True).returncode == 2
    draft_family = provenance.parent / "synthetic-draft-family.json"
    draft_family.write_bytes(serialize(corpus.families[0].model_dump()))
    draft_family.chmod(0o600)
    worksheet = subprocess.run(
        [
            sys.executable,
            "tools/phase2_preparation.py",
            "--worksheet",
            str(draft_family),
            "--output",
            str(provenance.parent / "worksheet.json"),
        ],
        check=True,
        capture_output=True,
    )
    worksheet_key = json.loads(worksheet.stdout)["protected_worksheet_key"]
    draft = json.loads((provenance.parent / worksheet_key).read_bytes())
    assert draft["preparer_id"] is None and draft["reviewer_id"] is None
    assert all(row["decision"] is None for row in draft["rows"])
    private_catalog = provenance.parent / "synthetic-catalog.json"
    private_catalog.write_bytes(serialize(json.loads(preparation.read_bytes())["catalog"]))
    private_catalog.chmod(0o600)
    verified_report = subprocess.run(
        [
            sys.executable,
            "tools/phase2_preparation.py",
            "--verify",
            "--catalog",
            str(private_catalog),
            "--manifest",
            str(manifest),
            "--source",
            str(provenance.parent),
            "--provenance",
            str(provenance),
            "--preparation",
            str(preparation),
        ],
        check=True,
        capture_output=True,
    )
    report = json.loads(verified_report.stdout)
    assert report["freeze_eligible"] and report["verified_human_reviewed_families"] == 80
    assert report["independent_approval"] == "PENDING"
    mismatched_catalog = subprocess.run(
        [
            sys.executable,
            "tools/phase2_preparation.py",
            "--verify",
            "--catalog",
            "docs/ai/evaluation-candidates.json",
            "--manifest",
            str(manifest),
            "--source",
            str(provenance.parent),
            "--provenance",
            str(provenance),
            "--preparation",
            str(preparation),
        ],
        capture_output=True,
    )
    assert mismatched_catalog.returncode == 2


@pytest.mark.parametrize(
    "problem,expected",
    [
        ("self-review", "independent_gold_review"),
        ("wrong-reviewer", "independent_gold_review"),
        ("missing-evidence", "provenance_hash"),
        ("duplicate-family", "family_overlap"),
        ("derivative", "family_overlap"),
        ("cross-split", "contamination_or_family_overlap"),
        ("partial", "partial_gold"),
        ("forged-citation", "gold_invalid_citation"),
        ("source-change", "intake_source_changed"),
        ("wrong-language", "candidate_family_mismatch"),
        ("label-change", "review_seal_changed"),
        ("missing-packet", "protected_preparation_packet"),
        ("missing-hidden", "hidden_owner_authorship"),
        ("changed-variant", "variant_source_changed"),
        ("rights-pending", "rights_or_screening"),
        ("duplicate-edge", "duplicate_graph_or_entrypoint_fact"),
        ("insufficient-counts", "eval_entry_counts_incomplete"),
    ],
)
def test_freeze_rejects_invalid_preparation(full_case: tuple, problem: str, expected: str) -> None:
    corpus, sources, provenance, packet_path = full_case
    family = corpus.families[0]
    packet = json.loads(packet_path.read_bytes())
    if problem == "self-review":
        family.gold_review.reviewer_id = family.gold_review.preparer_id
    elif problem == "wrong-reviewer":
        family.gold_review.reviewer_id = "different-reviewer"
    elif problem == "missing-evidence":
        (provenance / family.gold_review.approval_evidence_sha256).unlink()
    elif problem == "duplicate-family":
        corpus.families.append(family.model_copy(deep=True))
    elif problem == "derivative":
        corpus.families[1].derivatives.append(family.id)
    elif problem == "cross-split":
        shared = (sources[family.id] / "main.py").read_bytes()
        other = corpus.families[20]
        (sources[other.id] / "shared.py").write_bytes(shared)
        (sources[other.id] / "shared.py").chmod(0o600)
        manifest = serialize(
            filter_sources(sources[other.id], other.repository, other.commit_sha, "a" * 64)
        )
        (sources[other.id].parent / "source_manifest.json").write_bytes(manifest)
        other.source_manifest_sha256 = checksum(manifest)
        other.content_fingerprints = sorted(
            {f["file_sha256"] for f in json.loads(manifest)["files"]}
        )
    elif problem == "partial":
        family.annotation_scope = "partial"
    elif problem == "forged-citation":
        family.claims[0].citations[0].end_line = 99999
        family.claims[0].fact.symbol.end_line = 99999
    elif problem == "source-change":
        (sources[family.id] / "main.py").write_bytes(b"modified after review\n")
    elif problem == "wrong-language":
        family.language_slice = "mixed"
    elif problem == "label-change":
        family.claims[0].status = "unsupported"
    elif problem == "missing-packet":
        packet_path = None
    elif problem == "missing-hidden":
        packet["hidden_authorship"] = []
    elif problem == "changed-variant":
        (
            sources["synthetic-family-20"].parent
            / "variants"
            / "synthetic-variant-20-0"
            / "source"
            / "main.py"
        ).write_bytes(b"modified variant\n")
    elif problem == "rights-pending":
        family.rights.approved_by_owner = False
    elif problem == "duplicate-edge":
        family.edges[1] = family.edges[0].model_copy(update={"id": "duplicated-edge"}, deep=True)
    elif problem == "insufficient-counts":
        removed = corpus.families.pop()
        packet["reviews"] = [r for r in packet["reviews"] if r["family_id"] != removed.id]
    if packet_path:
        packet_path.write_bytes(serialize(packet))
    with pytest.raises(ValueError, match=expected):
        freeze(corpus, sources, provenance, packet_path)


def test_no_duplicate_gold_or_conflicting_review(full_case: tuple) -> None:
    corpus, _, _, packet_path = full_case
    family = corpus.families[0].model_dump()
    family["claims"].append({**family["claims"][0], "id": "duplicate-atom"})
    with pytest.raises(ValidationError, match="duplicate_gold_fact"):
        Family.model_validate(family)
    packet = json.loads(packet_path.read_bytes())
    packet["reviews"].append(packet["reviews"][0])
    packet_path.write_bytes(serialize(packet))
    with pytest.raises(ValueError, match="duplicate_preparation_approval"):
        freeze(*full_case)


def test_protected_storage_rejects_real_bad_modes(full_case: tuple, tmp_path: Path) -> None:
    _, _, provenance, packet_path = full_case
    packet_path.chmod(0o644)
    with pytest.raises(ValueError, match="protected_store_permissions"):
        verify_boundary(provenance.parent, tmp_path / "git", 10002)


def test_cross_repository_reference_and_actual_language(full_case: tuple) -> None:
    corpus, sources, _, packet_path = full_case
    family = corpus.families[0]
    packet = json.loads(packet_path.read_bytes())
    packet["catalog"]["candidates"][0]["language_slice"] = "mixed"
    family.language_slice = "mixed"
    packet_path.write_bytes(serialize(packet))
    with pytest.raises(ValueError, match="incorrect_language_slice"):
        freeze(*full_case)
    family.language_slice = "python"
    packet["catalog"]["candidates"][0]["language_slice"] = "python"
    packet_path.write_bytes(serialize(packet))
    manifest_file = sources[family.id].parent / "source_manifest.json"
    manifest = json.loads(manifest_file.read_bytes())
    manifest["repository"] = "synthetic/other"
    manifest_file.write_bytes(serialize(manifest))
    family.source_manifest_sha256 = checksum(manifest_file.read_bytes())
    with pytest.raises(ValueError, match="cross_repository_source"):
        freeze(*full_case)


def test_missing_approval_evidence_is_not_self_supplied(full_case: tuple) -> None:
    corpus, _, _, packet_path = full_case
    packet = json.loads(packet_path.read_bytes())
    packet["catalog"]["candidates"][0]["owner_approval_sha256"] = "f" * 64
    packet_path.write_bytes(serialize(packet))
    with pytest.raises(ValueError, match="preparation_evidence_missing"):
        freeze(*full_case)
    assert corpus.status == "UNFROZEN"


def test_non_posix_storage_is_fail_closed(tmp_path: Path) -> None:
    if os.name == "posix":
        pytest.skip("Host Windows rejection covered in the Windows unit run.")
    with pytest.raises(ValueError, match="protected_posix"):
        verify_boundary(tmp_path, tmp_path / "repo", 10002)


def test_wrong_line_range_or_modified_original(full_case: tuple) -> None:
    corpus, sources, _, _ = full_case
    family = corpus.families[0]
    family.claims[0].citations[0].end_line = 999
    family.claims[0].fact.symbol.end_line = 999
    with pytest.raises(ValueError, match="gold_invalid_citation"):
        validate_labels(family, sources[family.id])

"""Manually specified v2 evaluation fixtures, independent of production extraction.

These source facts and judgments are test expectations, never official/AI-reviewed gold.
"""

import subprocess
import sys

import pytest
from pydantic import ValidationError
from repovox.analysis.facts import CanonicalFact, SemanticSymbol
from repovox.evaluation.gold import Citation
from repovox.evaluation.scoring_v2 import Score, aggregate, score
from repovox.evaluation.v2 import (
    Judgment,
    Observation,
    Policy,
    PredictedFact,
    Prediction,
    Provenance,
    Reference,
    Scope,
    SourceFile,
    Window,
    decode,
    digest,
    serialize,
    validate_reference,
)

SHA = "c" * 40
OWNER = "12345678-1234-1234-1234-123456789abc"
FILES = {
    "main.py": (
        b"from .cargo import Crate as Box\nclass Vessel:\n    pass\n"
        b"def launch():\n    return Box()\n"
        b'if __name__ == "__main__":\n    launch()\n'
    ),
    "cargo.py": b"class Crate:\n    pass\n",
}


def symbol(path: str, snippet: bytes, category: str, name: str, **extra) -> SemanticSymbol:
    body = FILES[path]
    start = body.index(snippet)
    end = start + len(snippet)
    return SemanticSymbol(
        path=path,
        file_sha256=digest(body),
        start_byte=start,
        end_byte=end,
        start_line=body[:start].count(b"\n") + 1,
        end_line=body[: end - 1].count(b"\n") + 1,
        category=category,
        language="python",
        source_name=name,
        qualified_name=name,
        **extra,
    )


def authored_fact(category: str = "syntax") -> CanonicalFact:
    subject = symbol("main.py", b"def launch():\n    return Box()", "function", "launch")
    if category == "relationship":
        subject = symbol("main.py", b"Box()", "call", "Box", dispatch="named")
    if category == "entrypoint":
        subject = symbol(
            "main.py", b'if __name__ == "__main__":\n    launch()', "entrypoint", "__main__"
        )
    target = symbol("cargo.py", b"class Crate:\n    pass", "class", "Crate")

    def citation(s):
        return Citation.model_validate({k: getattr(s, k) for k in Citation.model_fields})

    return CanonicalFact(
        repository="synthetic/harbor",
        commit_sha=SHA,
        category=category,
        subject=subject,
        target=target if category == "relationship" else None,
        relationship="instantiates" if category == "relationship" else None,
        classification="resolved_static" if category == "relationship" else "declared",
        support=[citation(subject), citation(target)]
        if category == "relationship"
        else [citation(subject)],
        entrypoint_category="executable_application" if category == "entrypoint" else None,
        entrypoint_target="main:launch" if category == "entrypoint" else None,
        parser_rules=["independently-authored-test-rule"],
    )


@pytest.fixture
def case(tmp_path):
    for name, body in FILES.items():
        (tmp_path / name).write_bytes(body)
    proofs = {
        digest(b): b
        for b in [
            b"SYNTHETIC RIGHTS ONLY",
            b"SYNTHETIC PIN VERIFICATION ONLY",
            b"SYNTHETIC RAW RESPONSE ONLY",
            b"SYNTHETIC SOURCE ONLY ATTESTATION",
        ]
    }
    keys = list(proofs)
    scope = Scope(
        policy=Policy(),
        usage="SYNTHETIC_FIXTURE",
        tenant_id="tenant-a",
        analysis_owner_id=OWNER,
        family_id="harbor",
        repository="synthetic/harbor",
        commit_sha=SHA,
        rights_decision="PERMITTED_INTERNAL_EXPLORATORY",
        rights_evidence_sha256=keys[0],
        snapshot_verification_sha256=keys[1],
        files=[
            SourceFile(
                path=p,
                file_sha256=digest(b),
                language="python",
                size=len(b),
                windows=[
                    Window(
                        path=p,
                        file_sha256=digest(b),
                        start_line=1,
                        end_line=b[:-1].count(b"\n") + 1,
                        start_byte=0,
                        end_byte=len(b),
                    )
                ],
            )
            for p, b in FILES.items()
        ],
        limitations=["Synthetic source fixtures; complete means selected scope only."],
    )
    from repovox.evaluation.custody_v2 import source_packet

    packet = source_packet(serialize(scope), digest(serialize(scope)), tmp_path, proofs)
    packet_body = serialize(packet)
    proofs[digest(packet_body)] = packet_body
    fact = authored_fact()
    ref = Reference(
        policy=Policy(),
        tenant_id=scope.tenant_id,
        family_id=scope.family_id,
        repository=scope.repository,
        commit_sha=SHA,
        scope_sha256=digest(serialize(scope)),
        blind_source_sha256=digest(packet_body),
        prediction_commitment_sha256="e" * 64,
        annotation_scope="complete",
        scope_description="Single specified declaration fact in these synthetic files.",
        limitations=["No runtime claims."],
        provenance=Provenance(
            author_role="SYNTHETIC_TEST_AUTHOR",
            source_only_attestation_sha256=keys[3],
            response_capture_sha256=keys[2],
            identity_basis="synthetic_fixture",
        ),
        assertions=[
            Judgment(
                id="reference-a",
                fact=fact.model_copy(deep=True),
                expected_status="verified",
                evidence_entailment="supported",
                rationale="The fixture explicitly declares launch.",
            )
        ],
        observations=[],
        revision=1,
        supersedes_sha256=None,
        correction_reason=None,
        correction_citations=[],
    )
    pred = Prediction(
        policy=Policy(),
        tenant_id=scope.tenant_id,
        family_id=scope.family_id,
        repository=scope.repository,
        commit_sha=SHA,
        scope_sha256=ref.scope_sha256,
        analysis_sha256=digest(b"SYNTHETIC PREDICTIONS"),
        engineering_commit="d" * 40,
        projection_version="synthetic-fixture-2.0",
        facts=[
            PredictedFact(
                id="unrelated-prediction-z",
                fact=fact,
                status="verified",
                verdict_origin="synthetic_fixture",
                claim_id=None,
                evidence=fact.support,
            )
        ],
        unprojected_claims=[],
        selected_entrypoint=None,
    )
    ref.prediction_commitment_sha256 = digest(serialize(pred))
    return tmp_path, scope, proofs, ref, pred


def run(case):
    root, scope, proofs, ref, pred = case
    ref.prediction_commitment_sha256 = digest(serialize(pred))
    rb, pb, sb = serialize(ref), serialize(pred), serialize(scope)
    return score(rb, digest(rb), pb, digest(pb), sb, digest(sb), root, proofs)


def test_exact_alignment_is_not_ids_or_parser_labels(case):
    case[4].facts[0].fact = (
        case[4].facts[0].fact.model_copy(update={"parser_rules": ["totally-different-parser"]})
    )
    report = run(case)
    assert report.summary["counts"]["matched"] == 1
    assert report.completeness == {
        "pairing_status": "COMPLETE",
        "acceptance_status": "REVIEW_REQUIRED",
        "incomplete_reasons": [],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("qualified_name", "other.launch"),
        ("dispatch", "dynamic"),
        ("alias", "Other"),
        ("type_only", True),
    ],
)
def test_meaningful_symbol_differences_never_pair(case, field, value):
    p = case[4].facts[0]
    p.fact = p.fact.model_copy(update={"subject": p.fact.subject.model_copy(update={field: value})})
    report = run(case)
    assert report.summary["counts"]["matched"] == 0
    assert report.summary["counts"]["false_verified_predictions"] == 0
    assert report.summary["counts"]["unscored_verified_predictions"] == 1


@pytest.mark.parametrize("member,binding", [("Other", "Box"), ("Crate", "Crate")])
def test_qualified_import_member_and_binding_identity(case, member, binding):
    s = symbol(
        "main.py",
        b"from .cargo import Crate as Box",
        "import_member",
        ".cargo.Crate",
        import_module=".cargo",
        imported_member="Crate",
        local_binding="Box",
        alias="Box",
    )
    f = authored_fact().model_copy(
        update={
            "subject": s,
            "support": [Citation.model_validate({k: getattr(s, k) for k in Citation.model_fields})],
        }
    )
    case[3].assertions[0].fact = f
    p = case[4].facts[0]
    altered = s.model_copy(
        update={
            "imported_member": member,
            "qualified_name": ".cargo." + member,
            "local_binding": binding,
            "alias": binding,
        }
    )
    p.fact = f.model_copy(update={"subject": altered})
    p.evidence = f.support
    assert run(case).summary["counts"]["matched"] == 0


def test_different_valid_original_ranges_do_not_pair(case):
    p = case[4].facts[0]
    s = symbol("main.py", b"    return Box()", "function", "launch")
    p.fact = p.fact.model_copy(
        update={
            "subject": s,
            "support": [Citation.model_validate({k: getattr(s, k) for k in Citation.model_fields})],
        }
    )
    p.evidence = p.fact.support
    assert run(case).summary["counts"]["matched"] == 0


@pytest.mark.parametrize(
    "category,field,value",
    [
        ("relationship", "relationship", "inherits"),
        ("relationship", "classification", "unresolved"),
        ("entrypoint", "entrypoint_category", "library_export"),
        ("entrypoint", "entrypoint_target", "other:launch"),
    ],
)
def test_relationship_and_entrypoint_distinctions(case, category, field, value):
    f = authored_fact(category)
    case[3].assertions[0].fact = f
    case[4].facts[0].fact = f.model_copy(update={field: value})
    case[4].facts[0].evidence = f.support
    report = run(case)
    assert report.summary["counts"]["matched"] == 0
    assert report.completeness["acceptance_status"] == "INCOMPLETE"
    if field != "relationship":
        assert report.diagnostics[0]["field"] == field


def test_support_permutation_equivalent_but_missing_support_rejected(case):
    f = authored_fact("relationship")
    case[3].assertions[0].fact = f
    case[4].facts[0].fact = f.model_copy(update={"support": list(reversed(f.support))})
    case[4].facts[0].evidence = list(reversed(f.support))
    assert run(case).summary["counts"]["matched"] == 1
    case[4].facts[0].fact.support = []
    with pytest.raises(ValidationError):
        run(case)


@pytest.mark.parametrize(
    "gold_status,pred_status,correct,false_verified",
    [
        ("inferred", "verified", 0, 1),
        ("documentation_only", "verified", 0, 1),
        ("unsupported", "verified", 0, 1),
        ("unsupported", "unsupported", 1, 0),
        ("documentation_only", "documentation_only", 1, 0),
        ("unreviewed", "verified", 0, 0),
        ("verified", "unreviewed", 0, 0),
    ],
)
def test_verdicts_unknowns_and_false_verification(
    case, gold_status, pred_status, correct, false_verified
):
    g = case[3].assertions[0]
    g.expected_status = gold_status
    g.evidence_entailment = (
        "unreviewed"
        if gold_status == "unreviewed"
        else "unsupported"
        if gold_status == "unsupported"
        else "supported"
    )
    case[4].facts[0].status = pred_status
    report = run(case)
    c = report.summary["counts"]
    assert (c["correct_verdicts"], c["false_verified_predictions"]) == (correct, false_verified)
    if "unreviewed" in (gold_status, pred_status):
        assert (
            c["judged_matches"] == 0
            and report.summary["ratios"]["matched_verdict_correctness"] is None
        )
    elif false_verified:
        assert report.completeness["acceptance_status"] == "REJECTED"


def test_partial_never_complete_even_all_pairs(case):
    case[3].annotation_scope = "partial"
    assert run(case).completeness["acceptance_status"] == "INCOMPLETE"


def test_empty_denominators_are_null(case):
    case[3].assertions = []
    case[4].facts = []
    r = run(case)
    assert all(value is None for value in r.summary["ratios"].values())
    assert r.completeness["pairing_status"] == "INCOMPLETE"


@pytest.mark.parametrize(
    "problem",
    [
        "hash",
        "commit",
        "repository",
        "byte",
        "line",
        "outside",
        "evidence",
        "version",
        "entry_category",
        "duplicate_fact",
        "duplicate_id",
        "scope",
        "capture",
        "snapshot",
        "rights",
    ],
)
def test_adversarial_inputs_fail_closed(case, problem):
    root, scope, proofs, ref, pred = case
    if problem == "hash":
        pred.facts[0].fact.subject.file_sha256 = "f" * 64
    elif problem == "commit":
        pred.facts[0].fact.commit_sha = "f" * 40
    elif problem == "repository":
        pred.facts[0].fact.repository = "synthetic/other"
    elif problem == "byte":
        pred.facts[0].fact.subject.end_byte = 9999
    elif problem == "line":
        pred.facts[0].fact.subject.start_line = 100
    elif problem == "outside":
        scope.files = scope.files[1:]
    elif problem == "evidence":
        pred.facts[0].evidence = []
    elif problem == "version":
        pred.facts[0].fact.schema_version = "source-fact-1.0"
    elif problem == "entry_category":
        pred.facts[0].fact = authored_fact("entrypoint").model_copy(
            update={"entrypoint_category": "runtime_success"}
        )
    elif problem == "duplicate_fact":
        pred.facts.append(pred.facts[0].model_copy(update={"id": "other"}))
    elif problem == "duplicate_id":
        pred.facts.append(pred.facts[0])
    elif problem == "scope":
        pred.scope_sha256 = "f" * 64
    elif problem == "capture":
        proofs.pop(ref.provenance.response_capture_sha256)
    elif problem == "snapshot":
        (root / "main.py").write_bytes(b"changed")
    elif problem == "rights":
        proofs.pop(scope.rights_evidence_sha256)
    reason = {
        "hash": "canonical_endpoint_missing_support",
        "commit": "v2_prediction_snapshot_mismatch",
        "repository": "v2_prediction_snapshot_mismatch",
        "byte": "v2_byte_range_invalid",
        "line": "invalid_gold_source_range",
        "outside": "v2_reference_scope_binding",
        "evidence": "List should have at least 1 item",
        "version": "source-fact-2.0",
        "entry_category": "v2_invalid_entrypoint_category",
        "duplicate_fact": "v2_duplicate_prediction",
        "duplicate_id": "v2_duplicate_prediction",
        "scope": "v2_prediction_scope_binding",
        "capture": "v2_capture_or_attestation_missing",
        "snapshot": "v2_source_hash_mismatch",
        "rights": "v2_rights_or_snapshot_evidence_missing",
    }[problem]
    with pytest.raises((ValueError, ValidationError), match=reason):
        run(case)


@pytest.mark.parametrize("target", ["reference", "prediction", "scope"])
def test_original_commitment_tampering(case, target):
    root, scope, proofs, ref, pred = case
    rb, pb, sb = serialize(ref), serialize(pred), serialize(scope)
    originals = [digest(rb), digest(pb), digest(sb)]
    if target == "reference":
        rb += b" "
    elif target == "prediction":
        pb += b" "
    else:
        sb += b" "
    with pytest.raises(ValueError, match="commitment_mismatch"):
        score(rb, originals[0], pb, originals[1], sb, originals[2], root, proofs)


def test_revision_lineage_preserves_original_and_checks_gap(case):
    root, scope, proofs, ref, _ = case
    original = serialize(ref)
    ref.revision = 2
    ref.revision_context = "source_only_correction"
    approval = b"SYNTHETIC CORRECTION APPROVAL"
    proofs[digest(approval)] = approval
    ref.correction_approval_sha256 = digest(approval)
    ref.supersedes_sha256 = digest(original)
    ref.correction_reason = "Synthetic source-cited clarification; original bytes retained."
    s = ref.assertions[0].fact.subject
    ref.correction_citations = [
        Window.model_validate({k: getattr(s, k) for k in Window.model_fields})
    ]
    body = serialize(ref)
    with pytest.raises(ValueError, match="predecessor_missing"):
        validate_reference(body, digest(body), scope, ref.scope_sha256, root, proofs)
    assert (
        validate_reference(
            body, digest(body), scope, ref.scope_sha256, root, proofs, {digest(original): original}
        ).revision
        == 2
    )
    ref.revision = 4
    body = serialize(ref)
    with pytest.raises(ValueError, match="revision_gap"):
        validate_reference(
            body, digest(body), scope, ref.scope_sha256, root, proofs, {digest(original): original}
        )


def test_micro_aggregation_and_report_integrity(case):
    first = run(case)
    case[1].family_id = "second"
    case[1].repository = "synthetic/second"
    for obj in [case[3], case[4]]:
        obj.family_id = "second"
        obj.repository = "synthetic/second"
        obj.scope_sha256 = digest(serialize(case[1]))
    for a in [case[3].assertions[0], case[4].facts[0]]:
        a.fact.repository = "synthetic/second"
    case[4].facts = []
    from repovox.evaluation.custody_v2 import source_packet

    packet_body = serialize(
        source_packet(serialize(case[1]), digest(serialize(case[1])), case[0], case[2])
    )
    case[2][digest(packet_body)] = packet_body
    case[3].blind_source_sha256 = digest(packet_body)
    second = run(case)
    inputs = [(serialize(r), digest(serialize(r))) for r in [first, second]]
    combined = aggregate(inputs)
    assert combined.counts["gold"] == 2 and combined.ratios["gold_matching_coverage"] == 0.5
    assert combined.ratios["prediction_matching_coverage"] == 1.0
    assert combined.acceptance_status == "INCOMPLETE"
    with pytest.raises(ValueError, match="duplicate_aggregate"):
        aggregate([inputs[0], inputs[0]])
    broken = first.model_dump()
    broken["summary"]["counts"]["matched"] = 999
    with pytest.raises(ValueError, match="recomputation"):
        decode(serialize(broken), digest(serialize(broken)), Score)
    with pytest.raises(ValueError):
        aggregate(
            [
                (
                    b'{"schema_version":"evaluation-score-1.0"}',
                    digest(b'{"schema_version":"evaluation-score-1.0"}'),
                )
            ]
        )


def test_import_independence():
    code = """
import sys, importlib.abc
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname in {"repovox.analysis.parser", "repovox.analysis.graph",
                  "repovox.analysis.grounding", "repovox.analysis.bindings",
                  "repovox.analysis.relationships"}:
   raise AssertionError("Evaluator imported extraction or verifier authority: " + fullname)
sys.meta_path.insert(0,Deny())
from repovox.evaluation.scoring_v2 import score, aggregate
from repovox.evaluation.v2 import validate_reference
from repovox.evaluation.projection_v2 import project_analysis
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_wrong_graph_target_is_not_paired(case):
    f = authored_fact("relationship")
    case[3].assertions[0].fact = f
    target = symbol("main.py", b"class Vessel:\n    pass", "class", "Vessel")
    anchor = Citation.model_validate({k: getattr(target, k) for k in Citation.model_fields})
    p = case[4].facts[0]
    p.fact = f.model_copy(update={"target": target, "support": [f.support[0], anchor]})
    p.evidence = p.fact.support
    assert run(case).summary["counts"]["relationship_matched_supported"] == 0


def test_extra_support_is_identity_bearing(case):
    p = case[4].facts[0]
    extra = authored_fact("relationship").support[1]
    p.fact = p.fact.model_copy(update={"support": [*p.fact.support, extra]})
    p.evidence = p.fact.support
    assert run(case).summary["counts"]["matched"] == 0


@pytest.mark.parametrize("status", ["PASS", "executed", "unknown_verified"])
def test_invalid_verdict_status(case, status):
    case[3].assertions[0].expected_status = status
    with pytest.raises(ValueError):
        run(case)


def test_mixed_reference_versions_and_json_duplicates(case):
    body = serialize(case[3]).replace(b"gold-evaluation-2.0", b"gold-evaluation-1.0")
    with pytest.raises(ValueError):
        decode(body, digest(body), Reference)
    body = b'{"schema_version":"gold-evaluation-2.0","schema_version":"gold-evaluation-2.0"}'
    with pytest.raises(ValueError, match="duplicate_json_key"):
        decode(body, digest(body), Reference)


def test_aggregate_tenant_boundary(case):
    first = run(case)
    other = first.model_copy(deep=True)
    other.tenant_id = "tenant-b"
    other.family_id = "different-family"
    other.repository = "synthetic/other"
    for row in other.rows:
        if row.gold:
            row.gold.fact.repository = other.repository
        if row.prediction:
            row.prediction.fact.repository = other.repository
    with pytest.raises(ValueError, match="cross_tenant"):
        aggregate([(serialize(r), digest(serialize(r))) for r in [first, other]])


def test_source_scopes_and_no_fake_pilot_origin(case):
    case[1].usage = "FUTURE_BLIND_PILOT"
    case[3].scope_sha256 = case[4].scope_sha256 = digest(serialize(case[1]))
    from repovox.evaluation.custody_v2 import source_packet

    packet_body = serialize(
        source_packet(serialize(case[1]), digest(serialize(case[1])), case[0], case[2])
    )
    case[2][digest(packet_body)] = packet_body
    case[3].blind_source_sha256 = digest(packet_body)
    with pytest.raises(ValueError, match="synthetic_input_in_pilot"):
        run(case)


def test_semantic_observations_are_retained_and_prevent_completion(case):
    s = case[3].assertions[0].fact.subject
    case[3].observations = [
        Observation(
            id="runtime-success",
            assertion="Construction always succeeds at runtime.",
            status="unsupported",
            citations=[Window.model_validate({k: getattr(s, k) for k in Window.model_fields})],
        )
    ]
    result = run(case)
    assert result.reference_observations == case[3].observations
    assert result.summary["counts"]["unscored_reference_observations"] == 1
    assert result.completeness["acceptance_status"] == "INCOMPLETE"


def test_unknown_gold_does_not_enter_false_verification_denominator(case):
    case[3].assertions[0].expected_status = "unreviewed"
    case[3].assertions[0].evidence_entailment = "unreviewed"
    r = run(case)
    assert r.summary["counts"]["matched_verified_predictions"] == 1
    assert r.summary["counts"]["reviewed_verified_predictions"] == 0
    assert r.summary["ratios"]["false_verification_rate_on_reviewed_matches"] is None


@pytest.mark.parametrize("field,value", [("category", "runtime_success"), ("dispatch", "executed")])
def test_unknown_symbol_classification_rejected(case, field, value):
    setattr(case[4].facts[0].fact.subject, field, value)
    with pytest.raises(ValueError, match="v2_empty_symbol_identity"):
        run(case)


def test_scope_byte_window_does_not_authorize_excluded_line(case):
    from repovox.evaluation.v2 import validate_citation

    scope = case[1].model_copy(deep=True)
    window = scope.files[0].windows[0]
    window.start_byte = 5
    citation = Citation(
        path="main.py", file_sha256=digest(FILES["main.py"]), start_line=1, end_line=1
    )
    with pytest.raises(ValueError, match="citation_excluded_range"):
        validate_citation(citation, scope, FILES)


def test_forged_blind_source_packet_rejected(case):
    from repovox.evaluation.custody_v2 import SourcePacket

    packet = decode(case[2][case[3].blind_source_sha256], case[3].blind_source_sha256, SourcePacket)
    packet.excerpts[0].numbered_source = "1: invented implementation"
    body = serialize(packet)
    case[2][digest(body)] = body
    case[3].blind_source_sha256 = digest(body)
    with pytest.raises(ValueError, match="blind_source_content_mismatch"):
        run(case)


def test_utf8_split_range_rejected():
    from repovox.evaluation.v2 import check_range

    body = "aé\n".encode()
    c = Window(
        path="unicode.py",
        file_sha256=digest(body),
        start_line=1,
        end_line=1,
        start_byte=1,
        end_byte=2,
    )
    with pytest.raises(UnicodeDecodeError):
        check_range(c, body)


def test_unapproved_correction_is_rejected(case):
    ref = case[3]
    ref.revision = 2
    ref.revision_context = "post_reveal_correction"
    ref.supersedes_sha256 = "a" * 64
    ref.correction_reason = "Unsupported unapproved edit"
    s = ref.assertions[0].fact.subject
    ref.correction_citations = [
        Window.model_validate({k: getattr(s, k) for k in Window.model_fields})
    ]
    with pytest.raises(ValueError, match="correction_lineage_required"):
        run(case)
    ref.correction_approval_sha256 = "b" * 64
    with pytest.raises(ValueError, match="correction_approval_missing"):
        run(case)


def test_scoring_does_not_call_extraction_or_verification(case, monkeypatch):
    import builtins

    original = builtins.__import__
    forbidden = {
        "repovox.analysis.parser",
        "repovox.analysis.graph",
        "repovox.analysis.grounding",
        "repovox.analysis.bindings",
        "repovox.analysis.relationships",
    }

    def guarded(name, *args, **kwargs):
        assert name not in forbidden, "Production authority imported while scoring"
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert run(case).summary["counts"]["matched"] == 1


def test_supported_graph_counts_and_unresolved_lexical_distinction(case):
    f = authored_fact("relationship")
    case[3].assertions[0].fact = f.model_copy(deep=True)
    p = case[4].facts[0]
    p.fact, p.evidence = f, f.support
    r = run(case)
    assert r.summary["counts"]["relationship_matched_supported"] == 1
    assert r.summary["ratios"]["relationship_recall_against_annotated_subset"] == 1
    p.fact = f.model_copy(update={"classification": "unresolved"})
    r = run(case)
    assert r.summary["counts"]["relationship_matched_supported"] == 0
    assert r.diagnostics[0]["field"] == "classification"


def test_schema_exports_validate_synthetic_reports(case):
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    r = run(case)
    a = aggregate([(serialize(r), digest(serialize(r)))])
    for record in [case[1], case[3], case[4], r, a]:
        path = Path(__file__).parents[2] / "docs/ai" / (record.schema_version + ".schema.json")
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(record.model_dump(mode="json"))


def test_excluded_file_cannot_support_assertion(case):
    from repovox.evaluation.v2 import validate_fact

    scope = case[1].model_copy(deep=True)
    scope.files = [f for f in scope.files if f.path != "main.py"]
    with pytest.raises(ValueError, match="citation_outside_scope_or_hash"):
        validate_fact(case[3].assertions[0].fact, scope, FILES)


def test_type_only_import_is_not_a_runtime_import(case):
    from repovox.evaluation.custody_v2 import source_packet

    body = b"import type {Crate as Box} from './cargo';\n"
    (case[0] / "types.ts").write_bytes(body)
    w = Window(
        path="types.ts",
        file_sha256=digest(body),
        start_line=1,
        end_line=1,
        start_byte=0,
        end_byte=len(body),
    )
    case[1].files.append(
        SourceFile(
            path="types.ts",
            file_sha256=digest(body),
            language="typescript",
            size=len(body),
            windows=[w],
        )
    )
    scope_hash = digest(serialize(case[1]))
    case[3].scope_sha256 = case[4].scope_sha256 = scope_hash
    packet = serialize(source_packet(serialize(case[1]), scope_hash, case[0], case[2]))
    case[2][digest(packet)] = packet
    case[3].blind_source_sha256 = digest(packet)
    s = SemanticSymbol(
        **w.model_dump(),
        category="import_member",
        language="typescript",
        source_name="Crate",
        qualified_name="./cargo.Crate",
        import_module="./cargo",
        imported_member="Crate",
        local_binding="Box",
        alias="Box",
        type_only=True,
    )
    anchor = Citation.model_validate({k: getattr(s, k) for k in Citation.model_fields})
    f = authored_fact().model_copy(update={"subject": s, "support": [anchor]})
    case[3].assertions[0].fact = f.model_copy(deep=True)
    case[4].facts[0].fact = f.model_copy(
        update={"subject": s.model_copy(update={"type_only": False})}
    )
    case[4].facts[0].evidence = [anchor]
    assert run(case).summary["counts"]["matched"] == 0


def test_package_export_target_disagreement_is_unpaired(case):
    from repovox.evaluation.custody_v2 import source_packet

    body = b'{"exports":"./index.js"}\n'
    (case[0] / "package.json").write_bytes(body)
    w = Window(
        path="package.json",
        file_sha256=digest(body),
        start_line=1,
        end_line=1,
        start_byte=0,
        end_byte=len(body),
    )
    case[1].files.append(
        SourceFile(
            path=w.path, file_sha256=w.file_sha256, language="json", size=len(body), windows=[w]
        )
    )
    scope_hash = digest(serialize(case[1]))
    case[3].scope_sha256 = case[4].scope_sha256 = scope_hash
    packet = serialize(source_packet(serialize(case[1]), scope_hash, case[0], case[2]))
    case[2][digest(packet)] = packet
    case[3].blind_source_sha256 = digest(packet)
    s = SemanticSymbol(
        **{**w.model_dump(), "start_byte": 1, "end_byte": len(body) - 2},
        category="config_entry",
        language="json",
        source_name="./index.js",
        qualified_name="exports",
    )
    anchor = Citation.model_validate({k: getattr(s, k) for k in Citation.model_fields})
    f = CanonicalFact(
        repository=case[1].repository,
        commit_sha=SHA,
        category="entrypoint",
        subject=s,
        classification="declared",
        support=[anchor],
        entrypoint_category="library_export",
        entrypoint_target="./index.js",
        parser_rules=["manual-json-property"],
    )
    case[3].assertions[0].fact = f
    case[4].facts[0].fact = f.model_copy(update={"entrypoint_target": "./wrong.js"})
    case[4].facts[0].evidence = [anchor]
    r = run(case)
    assert r.summary["counts"]["entrypoint_matched_supported"] == 0
    assert r.diagnostics[0]["field"] == "entrypoint_target"


@pytest.mark.parametrize("nested", [False, True])
def test_serialized_versions_must_be_explicit(case, nested):
    value = case[3].model_dump()
    if nested:
        del value["assertions"][0]["fact"]["schema_version"]
    else:
        del value["schema_version"]
    body = serialize(value)
    with pytest.raises(ValueError, match="v2_explicit"):
        decode(body, digest(body), Reference)

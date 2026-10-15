"""Independent synthetic reproductions of review findings C-02 through C-04."""

from pathlib import Path

import pytest
from repovox.evaluation.scoring_v2 import Row, Score, aggregate, completeness, metrics, score
from repovox.evaluation.v2 import (
    Judgment,
    PredictedFact,
    SourceFile,
    Window,
    check_range,
    decode,
    digest,
    serialize,
    validate_citation,
    validate_fact,
)
from test_evaluation_v2 import authored_fact, run
from test_evaluation_v2 import case as case


@pytest.mark.parametrize("category", ["syntax", "relationship", "entrypoint"])
def test_c02_partial_overlap_is_not_independent_precision(category):
    fact = authored_fact(category)
    gold = Judgment(
        id="g",
        fact=fact,
        expected_status="verified",
        evidence_entailment="supported",
        rationale="Synthetic declaration.",
    )
    predictions = []
    for i in range(100):
        other = fact.model_copy(deep=True)
        other.subject.qualified_name = f"synthetic_{i}"
        predictions.append(
            PredictedFact(
                id=f"p{i}",
                fact=other,
                status="unreviewed",
                verdict_origin="synthetic_fixture",
                claim_id=None,
                evidence=other.support,
            )
        )
    predictions[0].fact = fact
    predictions[0].status = "verified"
    rows = [Row(gold=gold, prediction=predictions[0])]
    rows += [Row(gold=None, prediction=p) for p in predictions[1:]]
    result = metrics(rows, [], [])
    assert result["counts"][category + "_matched_supported"] == 1
    assert result["counts"][category + "_reviewed_predictions"] == 1
    assert result["ratios"][category + "_supported_overlap_fraction"] == 0.01
    assert result["ratios"][category + "_independently_reviewed_precision"] is None
    assert not any("precision_against_annotated_subset" in k for k in result["ratios"])


@pytest.mark.parametrize("partial", [True, False])
@pytest.mark.parametrize("unknown", [True, False])
def test_c02_precision_requires_reviewed_predictions_not_complete_gold(case, partial, unknown):
    case[3].annotation_scope = "partial" if partial else "complete"
    if unknown:
        case[3].assertions[0].expected_status = "unreviewed"
        case[3].assertions[0].evidence_entailment = "unreviewed"
    report = run(case)
    assert report.summary["ratios"]["syntax_independently_reviewed_precision"] == (
        None if unknown else 1.0
    )
    assert report.summary["ratios"]["relationship_independently_reviewed_precision"] is None
    assert report.completeness["acceptance_status"] == (
        "INCOMPLETE" if partial or unknown else "REVIEW_REQUIRED"
    )


def test_c02_known_unsupported_denominator_and_micro_aggregation(case):
    first = run(case)
    second = first.model_dump()
    second["family_id"] = "another-family"
    second["commit_sha"] = "b" * 40
    second["annotation_scope"] = "partial"
    # Independent source judgments: one supported and one unsupported, both reviewed.
    extra = second["rows"][0].copy()
    import copy

    extra = copy.deepcopy(extra)
    for row in [*second["rows"], extra]:
        for side in ["gold", "prediction"]:
            row[side]["fact"]["commit_sha"] = second["commit_sha"]
    extra["gold"]["id"] = "additional-gold"
    extra["prediction"]["id"] = "additional-prediction"
    for side in ["gold", "prediction"]:
        extra[side]["fact"]["subject"]["qualified_name"] = "another_declaration"
    extra["gold"]["expected_status"] = "unsupported"
    extra["gold"]["evidence_entailment"] = "unsupported"
    second["rows"].append(extra)
    second = recompute(second)
    result = aggregate([(serialize(r), digest(serialize(r))) for r in [first, second]])
    assert result.ratios["syntax_independently_reviewed_precision"] == 2 / 3
    assert result.counts["syntax_reviewed_predictions"] == 3
    assert result.acceptance_status == "INCOMPLETE"
    # Removing one judgment must preserve diagnostic overlap but null aggregate precision.
    second = second.model_dump()
    second["rows"][-1]["gold"] = None
    second = recompute(second)
    result = aggregate([(serialize(r), digest(serialize(r))) for r in [first, second]])
    assert result.ratios["syntax_supported_overlap_fraction"] == 2 / 3
    assert result.ratios["syntax_independently_reviewed_precision"] is None


def recompute(data):
    """Explicit synthetic report authoring; production analyzer never supplies judgments."""
    from repovox.evaluation.scoring_v2 import diagnostic_differences, eligibility

    rows = [Row.model_validate(r) for r in data["rows"]]
    data["summary"] = metrics(rows, [], [])
    data["completeness"] = completeness(
        rows, data["annotation_scope"], [], [], data["revision_context"]
    )
    data["eligibility"] = eligibility(data["revision_context"], data["completeness"]).model_dump()
    data["diagnostics"] = diagnostic_differences(rows)
    return Score.model_validate(data)


@pytest.mark.parametrize("offset", [0, 1, 2])
def test_c03_empty_window_rejected(offset):
    with pytest.raises(ValueError, match="v2_empty_byte_range"):
        window = Window(
            path="tiny.py",
            file_sha256="a" * 64,
            start_line=1,
            end_line=1,
            start_byte=offset,
            end_byte=offset,
        )
        check_range(window, b"ab")


def test_c04_post_reveal_cannot_qualify():
    result = completeness([], "complete", [], [], revision_context="post_reveal_correction")
    assert "post_reveal_diagnostic_only" in result["incomplete_reasons"]


@pytest.mark.parametrize("location", ["subject", "target"])
@pytest.mark.parametrize("boundary", ["model", "source"])
def test_c03_empty_semantic_span_rejected_at_evaluation_boundary(case, location, boundary):
    fact = authored_fact("relationship")
    symbol = getattr(fact, location)
    symbol.end_byte = symbol.start_byte
    symbol.end_line = symbol.start_line
    for citation in fact.support:
        if citation.path == symbol.path and citation.start_line == symbol.start_line:
            citation.end_line = symbol.end_line
    if boundary == "model":
        with pytest.raises(ValueError, match="v2_empty_byte_range"):
            Judgment(
                id="empty",
                fact=fact,
                expected_status="verified",
                evidence_entailment="supported",
                rationale="Must not pass.",
            )
        with pytest.raises(ValueError, match="v2_empty_byte_range"):
            PredictedFact(
                id="empty",
                fact=fact,
                status="unreviewed",
                claim_id=None,
                verdict_origin="no_verdict_available",
                evidence=fact.support,
            )
    else:
        with pytest.raises(ValueError, match="v2_empty_byte_range"):
            validate_fact(
                fact, case[1], {f.path: (case[0] / f.path).read_bytes() for f in case[1].files}
            )


def test_c03_zero_length_file_cannot_supply_evidence():
    # Bypass only the window constructor to prove the SourceFile boundary independently.
    window = Window.model_construct(
        path="empty.py", file_sha256=digest(b""), start_line=1, end_line=1, start_byte=0, end_byte=0
    )
    with pytest.raises(ValueError, match="v2_empty_byte_range|v2_scope_window"):
        SourceFile(
            path="empty.py", file_sha256=digest(b""), language="python", size=0, windows=[window]
        )
    with pytest.raises(ValueError, match="v2_empty_byte_range"):
        check_range(window, b"")


@pytest.mark.parametrize(
    "body,start,end,start_line,end_line,reason",
    [
        (b"abc", 0, 3, 1, 1, None),
        (b"abc\n", 3, 4, 1, 1, None),
        (b"abc", 3, 4, 1, 1, "byte_range_invalid"),
        (b"a\nb", 2, 3, 2, 2, None),
        (b"a\nb", 2, 3, 1, 1, "byte_range_invalid"),
        (b"a\nb", 0, 3, 1, 1, "byte_range_invalid"),
        (b"a\nb", 0, 1, 0, 1, "greater_than_equal"),
        (b"a\nb", 0, 1, 1, 4, "line_range_invalid"),
        ("a\u00e9\n".encode(), 1, 3, 1, 1, None),
        ("a\u00e9\n".encode(), 2, 3, 1, 1, "utf-8"),
        ("a\u00e9\n".encode(), 1, 2, 1, 1, "utf-8"),
    ],
)
def test_c03_nonempty_original_bytes_and_utf8(body, start, end, start_line, end_line, reason):
    def validate():
        window = Window(
            path="example.py",
            file_sha256=digest(body),
            start_line=start_line,
            end_line=end_line,
            start_byte=start,
            end_byte=end,
        )
        check_range(window, body)

    if reason:
        with pytest.raises(ValueError, match=reason):
            validate()
    else:
        validate()


def test_c03_empty_trailing_line_is_not_support(case):
    from repovox.evaluation.gold import Citation

    body = (case[0] / "main.py").read_bytes()
    c = Citation(
        path="main.py",
        file_sha256=digest(body),
        start_line=body.count(b"\n") + 1,
        end_line=body.count(b"\n") + 1,
    )
    with pytest.raises(ValueError, match="v2_empty_byte_range"):
        validate_citation(c, case[1], {"main.py": body})


def revise(case, context, expected_status=None):
    root, scope, proofs, ref, pred = case
    # Retain exact predecessor and approval bytes; no source or prediction edits.
    original = serialize(ref)
    if expected_status is not None:
        ref.assertions[0].expected_status = expected_status
    ref.revision += 1
    ref.revision_context = context
    approval = b"SYNTHETIC CORRECTION APPROVAL"
    proofs[digest(approval)] = approval
    ref.correction_approval_sha256 = digest(approval)
    ref.supersedes_sha256 = digest(original)
    ref.correction_reason = "Independent source-backed diagnostic revision."
    s = ref.assertions[0].fact.subject
    ref.correction_citations = [
        Window.model_validate({k: getattr(s, k) for k in Window.model_fields})
    ]
    rb, pb, sb = serialize(ref), serialize(pred), serialize(scope)
    return score(
        rb, digest(rb), pb, digest(pb), sb, digest(sb), root, proofs, {digest(original): original}
    )


@pytest.mark.parametrize("disagreement", [False, True])
def test_c04_exact_post_reveal_revision_is_diagnostic_only(case, disagreement):
    initial = run(case)
    original = serialize(case[3])
    revised = revise(case, "post_reveal_correction", "inferred" if disagreement else None)
    assert revised.summary["counts"]["matched"] == 1
    assert revised.summary["counts"]["incorrect_verdicts"] == int(disagreement)
    assert revised.eligibility.diagnostic_only is True
    assert revised.eligibility.blind_result_eligible is False
    assert revised.completeness["acceptance_status"] == "INCOMPLETE"
    assert initial.eligibility.blind_result_eligible is True
    assert initial.eligibility.diagnostic_only is False
    assert initial.reference_sha256 == digest(original)
    assert case[3].supersedes_sha256 == initial.reference_sha256
    result = aggregate([(serialize(revised), digest(serialize(revised)))])
    assert result.eligibility.diagnostic_only is True
    assert result.eligibility.blind_result_eligible is False
    assert result.acceptance_status == "INCOMPLETE"
    assert result.families[0]["revision_context"] == "post_reveal_correction"
    assert result.families[0]["eligibility"]["diagnostic_only"] is True
    tampered = revised.model_dump()
    tampered["eligibility"]["blind_result_eligible"] = True
    with pytest.raises(ValueError, match="recomputation"):
        decode(serialize(tampered), digest(serialize(tampered)), Score)


def test_c04_source_only_revision_retains_blind_candidate_eligibility(case):
    report = revise(case, "source_only_correction")
    assert not report.eligibility.diagnostic_only
    assert report.eligibility.blind_result_eligible
    assert report.completeness["acceptance_status"] == "REVIEW_REQUIRED"


def test_c04_mixed_aggregate_cannot_hide_diagnostic_family(case):
    first = run(case)
    diagnostic = revise(case, "post_reveal_correction").model_dump()
    diagnostic["family_id"] = "diagnostic-family"
    diagnostic["commit_sha"] = "b" * 40
    for side in ["gold", "prediction"]:
        diagnostic["rows"][0][side]["fact"]["commit_sha"] = diagnostic["commit_sha"]
    diagnostic = Score.model_validate(diagnostic)
    combined = aggregate([(serialize(r), digest(serialize(r))) for r in [first, diagnostic]])
    assert combined.counts["matched"] == 2
    assert combined.eligibility.diagnostic_only
    assert not combined.eligibility.blind_result_eligible
    assert combined.acceptance_status == "INCOMPLETE"
    assert combined.families[0]["eligibility"]["blind_result_eligible"]
    assert combined.families[1]["eligibility"]["diagnostic_only"]
    assert "post_reveal_diagnostic_only" in combined.eligibility.reasons


@pytest.mark.parametrize("key", ["summary", "completeness", "eligibility"])
def test_corrected_report_rejects_forged_metrics_or_eligibility(case, key):
    report = run(case).model_dump()
    if key == "summary":
        report[key]["counts"]["syntax_reviewed_predictions"] = 0
    elif key == "completeness":
        report[key]["acceptance_status"] = "REJECTED"
    else:
        report[key]["diagnostic_only"] = True
    with pytest.raises(ValueError, match="recomputation"):
        decode(serialize(report), digest(serialize(report)), Score)


def test_c04_post_reveal_lineage_cannot_be_relabelled_blind(case):
    from repovox.evaluation.v2 import validate_reference

    original = serialize(case[3])
    revise(case, "post_reveal_correction")
    predecessor = serialize(case[3])
    case[3].revision = 3
    case[3].supersedes_sha256 = digest(predecessor)
    case[3].revision_context = "source_only_correction"
    current = serialize(case[3])
    with pytest.raises(ValueError, match="correction_context_regression"):
        validate_reference(
            current,
            digest(current),
            case[1],
            case[3].scope_sha256,
            case[0],
            case[2],
            {digest(original): original, digest(predecessor): predecessor},
        )


def test_legacy_v20_readers_and_schemas_remain_explicit(case):
    from repovox.evaluation import scoring_v20

    report = run(case).model_dump()
    report["schema_version"] = "evaluation-score-2.0"
    report["scorer_version"] = "exact-v2-1.0"
    del report["eligibility"]
    rows = [scoring_v20.Row.model_validate(r) for r in report["rows"]]
    report["summary"] = scoring_v20.metrics(rows, [], [])
    report["completeness"] = scoring_v20.completeness(rows, "complete", [], [])
    old = decode(serialize(report), digest(serialize(report)), scoring_v20.Score)
    assert old.summary["ratios"]["syntax_precision_against_annotated_subset"] == 1.0
    with pytest.raises(ValueError):
        aggregate([(serialize(old), digest(serialize(old)))])
    for name, sha in [
        (
            "evaluation-score-2.0",
            "fa5f9cd2c568aae56f3a836f1f9edbf04c4d5c504b2d795dff267771b01caefc",
        ),
        (
            "evaluation-aggregate-2.0",
            "e198d01516d46e0e56e993f637b6d6ecaa5bb4bb165e29b941bd913c602d04ce",
        ),
    ]:
        path = Path(__file__).parents[2] / "docs/ai" / (name + ".schema.json")
        # Commitments cover the unchanged Git LF bytes, independent of checkout newlines.
        assert digest(path.read_text(encoding="utf-8").encode()) == sha

"""Frozen 2.0 report readers and recomputation; never emit new legacy scores.

Historical overlap metrics retain their original names, not corrected precision semantics.
Use scoring_v2 for 2.1 evaluation; no implicit report conversion is permitted.
"""

from collections import defaultdict
from typing import Any, Literal

from pydantic import Field, model_validator

from repovox.evaluation.gold import ID, SHA, Hash, Record
from repovox.evaluation.v2 import (
    Judgment,
    Observation,
    Policy,
    PredictedFact,
    Unprojected,
    fact_key,
    serialize,
)


class Row(Record):
    gold: Judgment | None
    prediction: PredictedFact | None

    @model_validator(mode="after")
    def exact(self) -> "Row":
        if self.gold is None and self.prediction is None:
            raise ValueError("v2_empty_alignment_row")
        if (
            self.gold
            and self.prediction
            and fact_key(self.gold.fact) != fact_key(self.prediction.fact)
        ):
            raise ValueError("v2_noncanonical_pair")
        return self


def ratio(n: int, d: int) -> float | None:
    return n / d if d else None


def metrics(
    rows: list[Row], unprojected: list[Unprojected], observations: list[Observation]
) -> dict[str, Any]:
    gold = [r.gold for r in rows if r.gold]
    predicted = [r.prediction for r in rows if r.prediction]
    pairs = [(r.gold, r.prediction) for r in rows if r.gold and r.prediction]
    judged = [
        (g, p) for g, p in pairs if g.expected_status != "unreviewed" and p.status != "unreviewed"
    ]
    counts = {
        "gold": len(gold),
        "predictions": len(predicted),
        "matched": len(pairs),
        "unmatched_gold": sum(r.prediction is None for r in rows),
        "unmatched_predictions": sum(r.gold is None for r in rows),
        "judged_matches": len(judged),
        "unscored_predictions": len(predicted) - len(judged),
        "correct_verdicts": sum(g.expected_status == p.status for g, p in judged),
        "incorrect_verdicts": sum(g.expected_status != p.status for g, p in judged),
        "gold_verified": sum(g.expected_status == "verified" for g in gold),
        "matched_verified_predictions": sum(p.status == "verified" for g, p in pairs),
        "reviewed_verified_predictions": sum(p.status == "verified" for g, p in judged),
        "correct_verified_predictions": sum(
            g.expected_status == p.status == "verified" for g, p in judged
        ),
        "false_verified_predictions": sum(
            p.status == "verified" and g.expected_status != "verified" for g, p in judged
        ),
        "unscored_verified_predictions": sum(p.status == "verified" for p in predicted)
        - sum(p.status == "verified" for g, p in judged),
        "gold_unsupported": sum(g.expected_status == "unsupported" for g in gold),
        "unsupported_rejections": sum(
            g.expected_status == p.status == "unsupported" for g, p in judged
        ),
        "unprojected_claims": len(unprojected),
        "unscored_reference_observations": len(observations),
        "unprojected_verified_claims": sum(c.status == "verified" for c in unprojected),
        "prediction_citations": sum(len(p.evidence) for p in predicted)
        + sum(len(c.citations) for c in unprojected),
        "reviewed_evidence_supported": sum(g.evidence_entailment == "supported" for g, p in pairs),
        "reviewed_evidence_unsupported": sum(
            g.evidence_entailment == "unsupported" for g, p in pairs
        ),
        "unreviewed_evidence": len(predicted)
        - sum(g.evidence_entailment != "unreviewed" for g, p in pairs),
    }
    for status in ["verified", "inferred", "documentation_only", "unsupported", "unreviewed"]:
        counts["verdict_" + status] = sum(p.status == status for p in predicted)
    counts["valid_citations"] = counts["prediction_citations"]
    counts["source_commit_agreements"] = len(predicted)
    counts["full_file_hash_agreements"] = counts["prediction_citations"]
    counts["source_boundary_compliant_citations"] = counts["prediction_citations"]
    counts["valid_original_byte_ranges"] = sum(1 + (p.fact.target is not None) for p in predicted)
    counts.update(
        invalid_citations=0,
        source_sha_mismatches=0,
        invalid_ranges=0,
        missing_evidence=0,
        scope_violations=0,
    )
    for category in ["syntax", "relationship", "entrypoint"]:
        supported = {
            fact_key(g.fact)
            for g in gold
            if g.fact.category == category and g.evidence_entailment == "supported"
        }
        actual = {fact_key(p.fact) for p in predicted if p.fact.category == category}
        counts[category + "_gold_supported"] = len(supported)
        counts[category + "_predicted"] = len(actual)
        counts[category + "_matched_supported"] = len(supported & actual)
        counts[category + "_missing_supported"] = len(supported - actual)
        counts[category + "_additional"] = len(actual - supported)
    return {"counts": counts, "ratios": ratios(counts)}


def ratios(c: dict[str, int]) -> dict[str, float | None]:
    result = {
        "gold_matching_coverage": ratio(c["matched"], c["gold"]),
        "prediction_matching_coverage": ratio(c["matched"], c["predictions"]),
        "matched_verdict_correctness": ratio(c["correct_verdicts"], c["judged_matches"]),
        "false_verification_rate_on_reviewed_matches": ratio(
            c["false_verified_predictions"], c["reviewed_verified_predictions"]
        ),
        "verified_recall": ratio(c["correct_verified_predictions"], c["gold_verified"]),
        "unsupported_rejection_recall": ratio(c["unsupported_rejections"], c["gold_unsupported"]),
    }
    for category in ["syntax", "relationship", "entrypoint"]:
        result[category + "_precision_against_annotated_subset"] = ratio(
            c[category + "_matched_supported"], c[category + "_predicted"]
        )
        result[category + "_recall_against_annotated_subset"] = ratio(
            c[category + "_matched_supported"], c[category + "_gold_supported"]
        )
    return result


def completeness(
    rows: list[Row],
    annotation_scope: str,
    unprojected: list[Unprojected],
    observations: list[Observation],
) -> dict[str, Any]:
    reasons = []
    if annotation_scope != "complete":
        reasons.append("partial_reference_scope")
    if not rows or any(r.gold is None or r.prediction is None for r in rows):
        reasons.append("requires_nonempty_100_percent_pairing_both_directions")
    if any(
        (
            r.gold
            and (
                r.gold.expected_status == "unreviewed" or r.gold.evidence_entailment == "unreviewed"
            )
        )
        or (r.prediction and r.prediction.status == "unreviewed")
        for r in rows
    ):
        reasons.append("unreviewed_judgments_or_verdicts")
    if unprojected:
        reasons.append("unprojected_semantic_claims")
    if observations:
        reasons.append("reference_observations_require_semantic_review")
    mismatch = any(
        r.gold and r.prediction and r.gold.expected_status != r.prediction.status for r in rows
    )
    return {
        "pairing_status": "INCOMPLETE" if reasons else "COMPLETE",
        "acceptance_status": "INCOMPLETE"
        if reasons
        else "REJECTED"
        if mismatch
        else "REVIEW_REQUIRED",
        "incomplete_reasons": reasons,
    }


def diagnostic_differences(rows: list[Row]) -> list[dict[str, str]]:
    """One-field differences are diagnostic only; never used to create scoring pairs."""
    gold = [r.gold for r in rows if r.gold and r.prediction is None]
    predicted = [r.prediction for r in rows if r.prediction and r.gold is None]
    result = []
    for field, category in [
        ("relationship", "relationship"),
        ("classification", "relationship"),
        ("entrypoint_category", "entrypoint"),
        ("entrypoint_target", "entrypoint"),
    ]:

        def reduced(a: Judgment | PredictedFact, field: str = field) -> bytes:
            import json

            from repovox.analysis.facts import identity

            value = json.loads(identity(a.fact))
            value.pop(field)
            return serialize(value)

        expected: dict[bytes, list[Judgment]] = defaultdict(list)
        actual: dict[bytes, list[PredictedFact]] = defaultdict(list)
        for g in gold:
            if g.fact.category == category:
                expected[reduced(g)].append(g)
        for p in predicted:
            if p.fact.category == category:
                actual[reduced(p)].append(p)
        for key in sorted(expected.keys() & actual.keys()):
            if len(expected[key]) == len(actual[key]) == 1:
                result.append(
                    {
                        "gold_id": expected[key][0].id,
                        "prediction_id": actual[key][0].id,
                        "field": field,
                        "disposition": "REQUIRES_INDEPENDENT_REVIEW_NOT_A_PAIR",
                    }
                )
    return result


class Score(Record):
    schema_version: Literal["evaluation-score-2.0"] = "evaluation-score-2.0"
    scorer_version: Literal["exact-v2-1.0"] = "exact-v2-1.0"
    policy: Policy
    tenant_id: ID
    family_id: ID
    repository: str
    commit_sha: SHA
    scope_sha256: Hash
    reference_sha256: Hash
    reference_revision: int = Field(ge=1, le=100)
    revision_context: Literal["initial_blind", "source_only_correction", "post_reveal_correction"]
    prediction_sha256: Hash
    annotation_scope: Literal["complete", "partial"]
    rows: list[Row] = Field(max_length=50000)
    reference_observations: list[Observation]
    unprojected_claims: list[Unprojected]
    selected_entrypoint: Hash | None
    selection_interpretation: Literal[
        "not_selected", "unique_static_candidate", "ambiguous_static_candidates"
    ]
    limitations: list[str] = Field(min_length=1)
    summary: dict[str, Any]
    completeness: dict[str, Any]
    diagnostics: list[dict[str, str]]

    @model_validator(mode="after")
    def consistent(self) -> "Score":
        gold_keys = {fact_key(r.gold.fact) for r in self.rows if r.gold}
        prediction_keys = {fact_key(r.prediction.fact) for r in self.rows if r.prediction}
        paired_keys = {fact_key(r.gold.fact) for r in self.rows if r.gold and r.prediction}
        if gold_keys & prediction_keys != paired_keys:
            raise ValueError("v2_report_hidden_pair")
        claim_ids = [u.id for u in self.unprojected_claims]
        claim_ids += [
            r.prediction.claim_id for r in self.rows if r.prediction and r.prediction.claim_id
        ]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("v2_report_duplicate_claim")
        if (self.selection_interpretation == "unique_static_candidate") != (
            self.selected_entrypoint is not None
        ) or (
            self.selected_entrypoint is not None
            and self.selected_entrypoint
            not in {
                fact_key(r.prediction.fact)
                for r in self.rows
                if r.prediction and r.prediction.fact.category == "entrypoint"
            }
        ):
            raise ValueError("v2_report_selection_mismatch")
        for attr in ["gold", "prediction"]:
            values = [getattr(r, attr) for r in self.rows if getattr(r, attr)]
            if len({v.id for v in values}) != len(values) or len(
                {fact_key(v.fact) for v in values}
            ) != len(values):
                raise ValueError("v2_duplicate_report_row")
            if any(
                (v.fact.repository, v.fact.commit_sha) != (self.repository, self.commit_sha)
                for v in values
            ):
                raise ValueError("v2_report_snapshot_mismatch")
        if (
            self.summary != metrics(self.rows, self.unprojected_claims, self.reference_observations)
            or self.completeness
            != completeness(
                self.rows,
                self.annotation_scope,
                self.unprojected_claims,
                self.reference_observations,
            )
            or self.diagnostics != diagnostic_differences(self.rows)
        ):
            raise ValueError("v2_report_recomputation_mismatch")
        return self


class Aggregate(Record):
    schema_version: Literal["evaluation-aggregate-2.0"] = "evaluation-aggregate-2.0"
    policy: Policy
    tenant_id: ID
    report_sha256: list[Hash]
    families: list[dict[str, Any]]
    counts: dict[str, int]
    ratios: dict[str, float | None]
    acceptance_status: Literal["INCOMPLETE", "REVIEW_REQUIRED", "REJECTED"]
    limitations: list[str]

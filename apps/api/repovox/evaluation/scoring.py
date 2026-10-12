"""Independent source-fact evaluator; never imports the analyzer or its verifier."""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from repovox.evaluation.gold import (
    ID,
    SHA,
    Attributes,
    Citation,
    Classification,
    EdgeFact,
    EdgeIdentity,
    Fact,
    GoldEvaluation,
    Record,
    Status,
    SymbolFact,
    SymbolIdentity,
    identity,
    source_valid,
    validate_gold_source,
)

COUNT_KEYS = [
    "gold_count",
    "prediction_count",
    "matched_count",
    "unmatched_gold_count",
    "unmatched_prediction_count",
    "correct_verdicts",
    "gold_verified_count",
    "matched_verified_predictions",
    "correct_verified_predictions",
    "false_verified_predictions",
    "unscored_verified_predictions",
    "gold_unsupported_count",
    "matched_unsupported_gold",
    "unsupported_rejected",
    "unscored_predictions_requiring_human_review",
]


class Input(Record):
    # Read a documented projection of analysis 2.2; retain independence from its implementation.
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class Symbol(Input, Citation):
    model_config = Input.model_config
    id: ID
    kind: str
    name: str
    parser_language: str
    rule: str
    parameters: list[str] | None = None
    alias: str | None = None
    imported_name: str | None = None
    binding: str | None = None
    dispatch: str | None = None

    def grounded(self) -> SymbolIdentity:
        data = self.model_dump()
        attributes = {key: data.pop(key) for key in Attributes.model_fields}
        data.pop("id")
        data["language"] = data.pop("parser_language")
        return SymbolIdentity(**data, attributes=Attributes(**attributes))


class Edge(Input):
    id: ID
    source: ID
    target: ID
    relationship: str
    classification: Classification
    support_ids: list[ID] = Field(min_length=1)
    rule: str


class Claim(Input):
    id: ID
    text: str
    status: Status
    evidence_ids: list[ID] = Field(min_length=1)
    subject_id: ID
    rule: str


class Evidence(Input, Citation):
    model_config = Input.model_config
    id: ID
    commit_sha: SHA
    symbol_id: ID


class Verdict(Input):
    claim_id: ID
    status: Status
    evidence_ids: list[ID] = Field(min_length=1)
    rule: str


class Candidate(Input):
    path: str
    rule: str
    target: str | None = None
    symbol_id: ID
    support_ids: list[ID] = Field(min_length=1)


class Entrypoints(Input):
    candidates: list[Candidate]


class Repository(Input):
    repository: str
    commit_sha: SHA


class Knowledge(Input):
    repository: Repository
    symbols: list[Symbol] = Field(max_length=10000)
    edges: list[Edge] = Field(max_length=10000)
    entrypoints: Entrypoints
    claims: list[Claim] = Field(max_length=20000)
    coverage: dict[str, Any]


class Catalog(Input):
    items: list[Evidence] = Field(max_length=10000)


class Ledger(Input):
    verdicts: list[Verdict] = Field(max_length=20000)
    conflicts: list[str]


class Prediction(Input):
    knowledge: Knowledge
    evidence: Catalog
    verification: Ledger


def compare(expected: set[tuple[Any, ...]], predicted: set[tuple[Any, ...]]) -> dict[str, Any]:
    true = len(expected & predicted)
    return {
        "true_positive": true,
        "predicted": len(predicted),
        "gold": len(expected),
        "precision": true / len(predicted) if predicted else None,
        "recall": true / len(expected) if expected else None,
    }


def valid_citation(item: dict[str, Any], source: Path, commit_sha: str) -> bool:
    try:
        citation = Citation.model_validate({key: item[key] for key in Citation.model_fields})
        return item["commit_sha"] == commit_sha and source_valid(citation, source)
    except (ValueError, KeyError, TypeError, OSError):
        return False


def unique(items: list[Any], field: str = "id") -> dict[str, Any]:
    keyed = {getattr(item, field): item for item in items}
    if len(keyed) != len(items):
        raise ValueError("duplicate_prediction_id")
    return keyed


def symbol_statement(symbol: Symbol) -> str:
    """Versioned assertion grammar, independently specified in evaluation-gold.md."""
    path, name, kind = symbol.path, symbol.name, symbol.kind
    if kind == "module":
        return f"{path} is a successfully parsed {symbol.parser_language} source file."
    if kind == "documentation":
        return f"{path} mentions {name}; this is documentation-only."
    if kind == "declared_dependency":
        return f"{path} declares dependency constraint {name}; no locked version is asserted."
    if kind == "config_entry":
        return f"{path} declares entry target {name}; it has not been executed."
    if kind == "import":
        return f"{path} contains an import of {name}."
    if kind == "call":
        return f"{path} contains the call expression {name}; runtime execution is unknown."
    if kind == "entrypoint":
        return f"{path} contains a Python __main__ guard."
    if kind == "function" and name == "anonymous":
        return f"{path} contains anonymous function syntax."
    if kind == "export" and name == "export":
        return f"{path} contains export syntax."
    return f"{path} contains {kind} syntax named {name}."


def edge_fact(edge: Edge, symbols: dict[str, Symbol]) -> EdgeFact:
    return EdgeFact(
        type="static_relationship",
        edge=EdgeIdentity(
            source=symbols[edge.source].grounded(),
            target=symbols[edge.target].grounded(),
            relationship=edge.relationship,
            classification=edge.classification,
            support=[symbols[s].grounded() for s in edge.support_ids],
        ),
    )


def ratios(counts: dict[str, int]) -> dict[str, float | None]:
    def ratio(numerator: str, denominator: str) -> float | None:
        return counts[numerator] / counts[denominator] if counts[denominator] else None

    return {
        "gold_matching_coverage": ratio("matched_count", "gold_count"),
        "prediction_matching_coverage": ratio("matched_count", "prediction_count"),
        "verdict_accuracy_on_matches": ratio("correct_verdicts", "matched_count"),
        "reviewed_verified_precision": ratio(
            "correct_verified_predictions", "matched_verified_predictions"
        ),
        "verified_recall": ratio("correct_verified_predictions", "gold_verified_count"),
        "false_verification_rate_on_matches": ratio(
            "false_verified_predictions", "matched_verified_predictions"
        ),
        "unsupported_rejection_recall": ratio("unsupported_rejected", "gold_unsupported_count"),
    }


def score(
    gold: GoldEvaluation | dict[str, Any], result: dict[str, Any], source: Path
) -> dict[str, Any]:
    # A validated Family inherits GoldEvaluation. Revalidate its explicit gold projection.
    data = (
        gold.model_dump(include=set(GoldEvaluation.model_fields))
        if isinstance(gold, GoldEvaluation)
        else gold
    )
    if isinstance(data, dict) and "split" in data:
        from repovox.evaluation.corpus import Family

        family = Family.model_validate(data)
        data = family.model_dump(include=set(GoldEvaluation.model_fields))
    expected = GoldEvaluation.model_validate(data)
    validate_gold_source(expected, source)
    prediction = Prediction.model_validate(result)
    structure = prediction.knowledge
    if (
        structure.repository.repository != expected.repository
        or structure.repository.commit_sha != expected.commit_sha
    ):
        raise ValueError("prediction_snapshot_mismatch")
    symbols: dict[str, Symbol] = unique(structure.symbols)
    edges: dict[str, Edge] = unique(structure.edges)
    claims: dict[str, Claim] = unique(structure.claims)
    evidence: dict[str, Evidence] = unique(prediction.evidence.items)
    verdicts: dict[str, Verdict] = unique(prediction.verification.verdicts, "claim_id")
    if set(claims) != set(verdicts):
        raise ValueError("prediction_ledger_claim_mismatch")
    for edge in edges.values():
        if not {edge.source, edge.target, *edge.support_ids} <= symbols.keys():
            raise ValueError("prediction_edge_reference_missing")
        if len(set(edge.support_ids)) != len(edge.support_ids):
            raise ValueError("duplicate_prediction_support")
    for candidate in structure.entrypoints.candidates:
        if not {candidate.symbol_id, *candidate.support_ids} <= symbols.keys():
            raise ValueError("prediction_entrypoint_reference_missing")
    for item in evidence.values():
        if item.symbol_id not in symbols or anchor_tuple(item) != anchor_tuple(
            symbols[item.symbol_id]
        ):
            raise ValueError("prediction_evidence_symbol_mismatch")
    valid_evidence = {
        key
        for key, item in evidence.items()
        if item.commit_sha == expected.commit_sha and source_valid(item, source)
    }
    prediction_keys: dict[str, list[str]] = defaultdict(list)
    unscored: dict[str, str] = {}
    for cid, claim in claims.items():
        verdict = verdicts[cid]
        if (
            claim.status != verdict.status
            or claim.rule != verdict.rule
            or set(claim.evidence_ids) != set(verdict.evidence_ids)
        ):
            raise ValueError("prediction_ledger_content_mismatch")
        if len(set(claim.evidence_ids)) != len(claim.evidence_ids):
            raise ValueError("duplicate_prediction_evidence")
        if not set(claim.evidence_ids) <= evidence.keys():
            raise ValueError("prediction_evidence_missing")
        fact: Fact | None = None
        support: list[str] = []
        if claim.rule == "symbol-fact-v1" and claim.subject_id in symbols:
            symbol = symbols[claim.subject_id]
            if claim.text == symbol_statement(symbol):
                fact = SymbolFact(type="symbol_syntax", symbol=symbol.grounded())
                support = [symbol.id]
        elif claim.rule == "edge-fact-v1" and claim.subject_id in edges:
            edge = edges[claim.subject_id]
            statement = (
                f"Static {edge.relationship} relationship {edge.source} -> {edge.target} "
                f"has classification {edge.classification}; runtime execution is unknown."
            )
            if claim.text == statement and edge.rule == "graph-syntax-v1":
                fact = edge_fact(edge, symbols)
                support = edge.support_ids
        if fact is None:
            unscored[cid] = (
                "Unsupported assertion grammar or subject; human mapping review required."
            )
        elif {evidence[e].symbol_id for e in claim.evidence_ids} != set(support):
            raise ValueError("prediction_claim_support_mismatch")
        elif not set(claim.evidence_ids) <= valid_evidence:
            unscored[cid] = "Invalid original source citation; pairing unavailable."
        else:
            # Gold verdicts never depend on this assertion adapter or a predicted verdict.
            prediction_keys[identity(fact, expected.repository, expected.commit_sha)].append(cid)

    pairs: list[tuple[str, str]] = []
    for gold_claim in expected.claims:
        candidates = prediction_keys.get(
            identity(gold_claim.fact, expected.repository, expected.commit_sha), []
        )
        if len(candidates) == 1:
            pairs.append((gold_claim.id, candidates[0]))
        elif len(candidates) > 1:
            for cid in candidates:
                unscored[cid] = "Ambiguous duplicate source-fact predictions; no arbitrary pairing."
    paired_gold = {gid for gid, _ in pairs}
    paired_prediction = {cid for _, cid in pairs}
    for cid in claims.keys() - paired_prediction:
        unscored.setdefault(
            cid, "No independently authored matching gold fact; human review required."
        )
    gold_claims = {c.id: c for c in expected.claims}
    verified = [(gid, cid) for gid, cid in pairs if verdicts[cid].status == "verified"]
    counts = {
        "gold_count": len(gold_claims),
        "prediction_count": len(claims),
        "matched_count": len(pairs),
        "unmatched_gold_count": len(gold_claims) - len(pairs),
        "unmatched_prediction_count": len(claims) - len(pairs),
        "correct_verdicts": sum(gold_claims[g].status == verdicts[c].status for g, c in pairs),
        "gold_verified_count": sum(c.status == "verified" for c in expected.claims),
        "matched_verified_predictions": len(verified),
        "correct_verified_predictions": sum(
            gold_claims[g].status == "verified" for g, _ in verified
        ),
        "false_verified_predictions": sum(gold_claims[g].status != "verified" for g, _ in verified),
        "unscored_verified_predictions": sum(verdicts[c].status == "verified" for c in unscored),
        "gold_unsupported_count": sum(c.status == "unsupported" for c in expected.claims),
        "matched_unsupported_gold": sum(gold_claims[g].status == "unsupported" for g, _ in pairs),
        "unsupported_rejected": sum(
            gold_claims[g].status == verdicts[c].status == "unsupported" for g, c in pairs
        ),
        "unscored_predictions_requiring_human_review": len(unscored),
    }
    incomplete = []
    if expected.annotation_scope != "complete":
        incomplete.append("partial_gold_annotation_scope")
    if not pairs or len(pairs) != len(claims) or len(pairs) != len(gold_claims):
        incomplete.append("insufficient_pairing_coverage_requires_100_percent_both_sides")
    if len(valid_evidence) != len(evidence) or not all(
        source_valid(s, source) for s in symbols.values()
    ):
        incomplete.append("invalid_prediction_source_evidence")
    graph_gold = {
        identity(
            EdgeFact(
                type="static_relationship",
                edge=EdgeIdentity.model_validate(
                    e.model_dump(exclude={"id", "supported", "citations"})
                ),
            ),
            expected.repository,
            expected.commit_sha,
        )
        for e in expected.edges
        if e.supported
    }
    graph_prediction = {
        identity(edge_fact(e, symbols), expected.repository, expected.commit_sha)
        for e in edges.values()
    }
    import_gold = {
        identity(
            EdgeFact(
                type="static_relationship",
                edge=EdgeIdentity.model_validate(
                    e.model_dump(exclude={"id", "supported", "citations"})
                ),
            ),
            expected.repository,
            expected.commit_sha,
        )
        for e in expected.edges
        if e.supported and e.relationship == "imports" and e.classification == "resolved_static"
    }
    import_prediction = {
        identity(edge_fact(e, symbols), expected.repository, expected.commit_sha)
        for e in edges.values()
        if e.relationship == "imports" and e.classification == "resolved_static"
    }
    return {
        "schema_version": "evaluation-score-1.0",
        "alignment_version": "source-fact-1.0",
        "repository": expected.repository,
        "commit_sha": expected.commit_sha,
        "pairing_status": "INCOMPLETE" if incomplete else "COMPLETE",
        "acceptance_status": "INCOMPLETE"
        if incomplete
        else "REJECTED"
        if counts["false_verified_predictions"]
        else "REVIEW_REQUIRED",
        "incomplete_reasons": incomplete,
        "claims": {**counts, **ratios(counts)},
        "alignment": {
            "pairs": [{"gold_id": g, "prediction_id": c} for g, c in sorted(pairs)],
            "unmatched_gold_ids": sorted(gold_claims.keys() - paired_gold),
            "unmatched_prediction_ids": sorted(claims.keys() - paired_prediction),
            "unscored_predictions": [
                {"claim_id": c, "reason": unscored[c]} for c in sorted(unscored)
            ],
        },
        "graph": compare({(key,) for key in graph_gold}, {(key,) for key in graph_prediction}),
        "import_graph": compare(
            {(key,) for key in import_gold}, {(key,) for key in import_prediction}
        ),
        "symbols": compare(
            {
                (
                    identity(
                        SymbolFact(
                            type="symbol_syntax",
                            symbol=SymbolIdentity.model_validate(s.model_dump(exclude={"id"})),
                        ),
                        expected.repository,
                        expected.commit_sha,
                    ),
                )
                for s in expected.symbols
            },
            {
                (
                    identity(
                        SymbolFact(type="symbol_syntax", symbol=s.grounded()),
                        expected.repository,
                        expected.commit_sha,
                    ),
                )
                for s in symbols.values()
            },
        ),
        "entrypoints": compare(
            {(c.path, c.rule, c.target) for c in expected.entrypoints},
            {(c.path, c.rule, c.target) for c in structure.entrypoints.candidates},
        ),
        "citations": {"denominator": len(evidence), "valid": len(valid_evidence)},
        "coverage": structure.coverage,
        "parse_errors": [
            f for f in structure.coverage.get("files", []) if f.get("reason") == "parse_error"
        ],
        "conflicts_reported": len(prediction.verification.conflicts),
        "safety_observations": expected.safety_observations,
        "limitations": [
            "No semantic fuzzy matching or analyzer-ID equality establishes alignment.",
            "Reviewed precision uses only matched verified predictions; "
            "unscored claims remain unknown.",
            "COMPLETE pairing is not independent human review, "
            "corpus freeze or an acceptance PASS.",
        ],
    }


def anchor_tuple(item: Citation) -> tuple[str, str, int, int]:
    return item.path, item.file_sha256, item.start_line, item.end_line


def aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for report in reports:
        if report["schema_version"] != "evaluation-score-1.0":
            raise ValueError("unsupported_score_report_version")
        for metric in ["graph", "import_graph", "symbols", "entrypoints"]:
            for key in ["true_positive", "predicted", "gold"]:
                totals[f"{metric}.{key}"] += report[metric][key]
        for key in COUNT_KEYS:
            counts[key] += report["claims"][key]
    return {
        "schema_version": "evaluation-aggregate-1.0",
        "repositories": len(reports),
        "pairing_status": "COMPLETE"
        if reports and all(r["pairing_status"] == "COMPLETE" for r in reports)
        else "INCOMPLETE",
        "acceptance_status": "INCOMPLETE"
        if not reports or any(r["acceptance_status"] == "INCOMPLETE" for r in reports)
        else "REJECTED"
        if any(r["acceptance_status"] == "REJECTED" for r in reports)
        else "REVIEW_REQUIRED",
        "denominators_and_counts": dict(totals),
        "claims": {**counts, **ratios(dict(counts))} if reports else {},
        "aggregation": "Micro counts; incomplete families cannot be hidden by an aggregate. "
        "No acceptance PASS.",
    }

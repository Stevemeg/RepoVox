"""Versioned prediction-side adapter. Never authors gold or computes expected verdicts."""

from collections import Counter
from typing import Any

from repovox.analysis.contracts import Envelope, Verified
from repovox.analysis.facts import CanonicalFact, semantic_symbol
from repovox.evaluation.gold import Citation
from repovox.evaluation.scoring import Symbol, symbol_statement
from repovox.evaluation.v2 import (
    Policy,
    PredictedFact,
    Prediction,
    Scope,
    Unprojected,
    decode,
    digest,
    fact_key,
    serialize,
)


def unique(items: list[dict[str, Any]], key: str = "id") -> dict[str, dict[str, Any]]:
    result = {item[key]: item for item in items}
    if len(result) != len(items):
        raise ValueError("v2_projection_duplicate_id")
    return result


def project_analysis(
    body: bytes, expected_hash: str, scope: Scope, scope_hash: str, engineering_commit: str
) -> Prediction:
    # Explicit 2.3 envelope; legacy records cannot enter implicitly.
    envelope = decode(body, expected_hash, Envelope)
    if str(envelope.owner_id) != scope.analysis_owner_id:
        raise ValueError("v2_projection_owner_mismatch")
    if envelope.kind != "verify" or envelope.commit_sha != scope.commit_sha:
        raise ValueError("v2_projection_requires_verify_snapshot")
    result = Verified.model_validate(envelope.payload).model_dump(mode="json", by_alias=True)
    knowledge = result["knowledge"]
    if (knowledge["repository"]["repository"], knowledge["repository"]["commit_sha"]) != (
        scope.repository,
        scope.commit_sha,
    ) or knowledge["versions"]["schema"] != "analysis-2.3":
        raise ValueError("v2_projection_snapshot_mismatch")
    symbols = unique(knowledge["symbols"])
    edges = unique(knowledge["edges"])
    claims = unique(knowledge["claims"])
    ledger = unique(result["verification"]["verdicts"], "claim_id")
    evidence = unique(result["evidence"]["items"])
    if knowledge["versions"]["rules"] != "static-rules-v2" or (
        knowledge["versions"]["pipeline"] != envelope.pipeline_version
        or result["verification"]["verifier_version"] != "static-rules-v2"
    ):
        raise ValueError("v2_projection_version_mismatch")
    if set(claims) != set(ledger):
        raise ValueError("v2_projection_ledger_missing")
    actual_counts = Counter(v["status"] for v in ledger.values())
    if any(
        count != actual_counts[status] for status, count in result["verification"]["counts"].items()
    ) or any(status not in result["verification"]["counts"] for status in actual_counts):
        raise ValueError("v2_projection_ledger_counts_mismatch")
    for e in evidence.values():
        if (
            e["symbol_id"] not in symbols
            or e["commit_sha"] != scope.commit_sha
            or str(e["snapshot_id"]) != str(envelope.snapshot_id)
            or e["validation_status"] != "valid"
        ):
            raise ValueError("v2_projection_evidence_invalid")
        if any(e[k] != symbols[e["symbol_id"]][k] for k in Citation.model_fields):
            raise ValueError("v2_projection_evidence_anchor_mismatch")
    for c in claims.values():
        v = ledger[c["id"]]
        if (
            any(c[k] != v[k] for k in ["status", "rule", "evidence_ids"])
            or len(set(c["evidence_ids"])) != len(c["evidence_ids"])
            or not set(c["evidence_ids"]) <= evidence.keys()
        ):
            raise ValueError("v2_projection_ledger_or_evidence_mismatch")
    base: dict[str, Any] = {"repository": scope.repository, "commit_sha": scope.commit_sha}

    def anchors(ids: list[str]) -> list[Citation]:
        if not set(ids) <= symbols.keys():
            raise ValueError("v2_projection_subject_missing")
        values = [{k: symbols[i][k] for k in Citation.model_fields} for i in ids]
        return [Citation.model_validate(v) for v in {serialize(v): v for v in values}.values()]

    associations: dict[str, tuple[CanonicalFact, str | None, str | None, list[str]]] = {}
    for s in symbols.values():
        f = CanonicalFact(
            **base,
            category="syntax",
            subject=semantic_symbol(s),
            classification="declared",
            support=anchors([s["id"]]),
            parser_rules=[s["rule"]],
        )
        associations[fact_key(f)] = (
            f,
            s["id"],
            symbol_statement(Symbol.model_validate(s)),
            [s["id"]],
        )
    for e in edges.values():
        support = [e["source"], e["target"], *e["support_ids"]]
        citations = anchors(support)
        f = CanonicalFact(
            **base,
            category="relationship",
            subject=semantic_symbol(symbols[e["source"]]),
            target=semantic_symbol(symbols[e["target"]]),
            relationship=e["relationship"],
            classification=e["classification"],
            support=citations,
            parser_rules=[e["rule"]],
        )
        statement = (
            f"Static {e['relationship']} relationship {e['source']} -> {e['target']} "
            f"has classification {e['classification']}; runtime execution is unknown."
        )
        associations[fact_key(f)] = (f, e["id"], statement, e["support_ids"])
    for e in knowledge["entrypoints"]["candidates"]:
        citations = anchors(e["support_ids"])
        f = CanonicalFact(
            **base,
            category="entrypoint",
            subject=semantic_symbol(symbols[e["symbol_id"]]),
            classification="declared",
            support=citations,
            parser_rules=[e["rule"]],
            entrypoint_category=e["category"],
            entrypoint_target=e["target"],
        )
        associations[fact_key(f)] = (f, None, None, [])
    facts = [CanonicalFact.model_validate(f) for f in knowledge["canonical_facts"]]
    if (
        {fact_key(f) for f in facts} != set(associations)
        or len(facts) != len(associations)
        or len(associations)
        != len(symbols) + len(edges) + len(knowledge["entrypoints"]["candidates"])
    ):
        raise ValueError("v2_projection_canonical_subject_mismatch")
    consumed = set()
    projected = []
    selected_candidates = []
    catalog_anchors = {
        serialize({k: item[k] for k in Citation.model_fields}) for item in evidence.values()
    }
    for f in facts:
        if not {serialize(c) for c in f.support} <= catalog_anchors:
            raise ValueError("v2_projection_fact_evidence_missing")
        key = fact_key(f)
        _, subject, expected_statement, support = associations[key]
        candidates = [c for c in claims.values() if c["subject_id"] == subject]
        bound = None
        if len(candidates) == 1:
            c = candidates[0]
            rule = "symbol-fact-v1" if f.category == "syntax" else "edge-fact-v1"
            if c["text"] == expected_statement and c["rule"] == rule:
                if {evidence[e]["symbol_id"] for e in c["evidence_ids"]} != set(support):
                    raise ValueError("v2_projection_claim_support_mismatch")
                bound = c
                consumed.add(c["id"])
        projected.append(
            PredictedFact(
                id="fact-" + key,
                fact=f,
                status=bound["status"] if bound else "unreviewed",
                verdict_origin="bound_analysis_ledger" if bound else "no_verdict_available",
                claim_id=bound["id"] if bound else None,
                evidence=f.support,
            )
        )
        chosen = knowledge["entrypoints"]["selected"]
        if chosen and f.category == "entrypoint" and semantic_symbol(symbols[chosen]) == f.subject:
            selected_candidates.append(key)
    unprojected = [
        Unprojected(
            id=c["id"],
            status=c["status"],
            reason=(
                "Assertion is outside the documented static grammar "
                "or lacks a unique subject binding."
            ),
            citations=[
                Citation.model_validate({k: evidence[e][k] for k in Citation.model_fields})
                for e in c["evidence_ids"]
            ],
        )
        for c in claims.values()
        if c["id"] not in consumed
    ]
    if knowledge["entrypoints"]["selected"] and not selected_candidates:
        raise ValueError("v2_selected_candidate_binding_missing")
    return Prediction(
        policy=Policy(),
        tenant_id=scope.tenant_id,
        family_id=scope.family_id,
        repository=scope.repository,
        commit_sha=scope.commit_sha,
        scope_sha256=scope_hash,
        analysis_sha256=digest(body),
        engineering_commit=engineering_commit,
        projection_version="analysis-2.3-verdict-projection-1.0",
        facts=projected,
        unprojected_claims=unprojected,
        selected_entrypoint=selected_candidates[0] if len(selected_candidates) == 1 else None,
        selection_interpretation="not_selected"
        if not selected_candidates
        else "unique_static_candidate"
        if len(selected_candidates) == 1
        else "ambiguous_static_candidates",
    )

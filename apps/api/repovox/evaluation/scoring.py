"""Independent CPU evaluator: no imports from the repository-understanding implementation."""

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any


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
    path = (source / item["path"]).resolve()
    if not path.is_relative_to(source.resolve()) or not path.is_file() or path.is_symlink():
        return False
    body = path.read_bytes()
    return bool(
        item["commit_sha"] == commit_sha
        and hashlib.sha256(body).hexdigest() == item["file_sha256"]
        and 1 <= item["start_line"] <= item["end_line"] <= len(body.split(b"\n"))
    )


def score(gold: dict[str, Any], result: dict[str, Any], source: Path) -> dict[str, Any]:
    structure = result["knowledge"]
    modules = {n["id"]: n["path"] for n in structure["nodes"] if n["kind"] == "module"}
    graph = compare(
        {(e["source"], e["target"], e["relationship"]) for e in gold["edges"] if e["supported"]},
        {
            (
                modules.get(e["source"], e["source"]),
                modules.get(e["target"], e["target"]),
                e["relationship"],
            )
            for e in structure["edges"]
            if e["classification"] == "resolved_static"
        },
    )
    symbols = compare(
        {
            (s["path"], s["name"], s["kind"], s["start_line"], s["end_line"])
            for s in gold["symbols"]
        },
        {
            (s["path"], s["name"], s["kind"], s["start_line"], s["end_line"])
            for s in structure["symbols"]
        },
    )
    entries = compare(
        {tuple(e) for e in gold["entrypoints"]},
        {(c["path"], c["rule"]) for c in structure["entrypoints"]["candidates"]},
    )
    expected = {c["id"]: c["status"] for c in gold["claims"]}
    verdicts = result["verification"]["verdicts"]
    paired = [v for v in verdicts if v["claim_id"] in expected]
    verified = [v for v in paired if v["status"] == "verified"]
    unscored_verified = [
        v for v in verdicts if v["status"] == "verified" and v["claim_id"] not in expected
    ]
    rejected = [v for v in paired if expected[v["claim_id"]] == "unsupported"]
    citations = result["evidence"]["items"]
    return {
        "repository": gold["repository"],
        "graph": graph,
        "symbols": symbols,
        "entrypoints": entries,
        "claims": {
            "paired": len(paired),
            "gold": len(expected),
            "predicted": len(verdicts),
            "correct": sum(v["status"] == expected[v["claim_id"]] for v in paired),
            "verified_denominator": len(verified),
            "false_verified": sum(expected[v["claim_id"]] != "verified" for v in verified),
            "unscored_verified": len(unscored_verified),
            "unsupported_denominator": len(rejected),
            "unsupported_rejected": sum(v["status"] == "unsupported" for v in rejected),
        },
        "citations": {
            "denominator": len(citations),
            "valid": sum(valid_citation(e, source, gold["commit_sha"]) for e in citations),
        },
        "coverage": structure["coverage"],
        "parse_errors": [f for f in structure["coverage"]["files"] if f["reason"] == "parse_error"],
        "conflicts_reported": len(result["verification"]["conflicts"]),
        "safety_observations": gold.get("safety_observations", {}),
        "limitations": [
            "Gold labels must be independently reviewed; status validity alone is not entailment.",
            "Unscored claims require independent review before "
            "an acceptance result can be assigned.",
        ],
    }


def aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    for report in reports:
        for metric in ["graph", "symbols", "entrypoints"]:
            for key in ["true_positive", "predicted", "gold"]:
                totals[f"{metric}.{key}"] += report[metric][key]
        for key, value in report["claims"].items():
            totals[f"claims.{key}"] += value
    return {
        "repositories": len(reports),
        "denominators_and_counts": dict(totals),
        "aggregation": (
            "Micro counts; family-level confidence intervals require a frozen independent corpus."
        ),
    }

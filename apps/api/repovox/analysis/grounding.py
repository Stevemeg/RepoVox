import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from repovox.analysis.common import PARSER_VERSION, PIPELINE, RULES, AnalysisError, digest, stable
from repovox.analysis.documentation import context_symbols
from repovox.analysis.graph import configuration, entrypoints, infer, qualified_flows
from repovox.analysis.parser import parse_file
from repovox.analysis.privacy import redact


def evidence_kind(symbol: dict[str, Any]) -> str:
    if symbol["kind"] == "documentation":
        return "documentation"
    if symbol["kind"] in {"config_entry", "declared_dependency"}:
        return "manifest"
    return "source"


def permalink(snapshot: dict[str, Any], symbol: dict[str, Any]) -> str:
    prefix = f"{snapshot['canonical_url']}/blob/{snapshot['commit_sha']}"
    path = quote(symbol["path"], safe="/")
    return f"{prefix}/{path}#L{symbol['start_line']}-L{symbol['end_line']}"


def symbol_text(symbol: dict[str, Any]) -> str:
    kind, name, path = symbol["kind"], symbol["name"], symbol["path"]
    if kind == "module":
        return f"{path} is a successfully parsed {symbol['parser_language']} source file."
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


def edge_text(edge: dict[str, Any]) -> str:
    return (
        f"Static {edge['relationship']} relationship {edge['source']} -> {edge['target']} "
        f"has classification {edge['classification']}; runtime execution is unknown."
    )


def claim_for(subject: dict[str, Any], relation: bool = False) -> dict[str, Any]:
    rule = "edge-fact-v1" if relation else "symbol-fact-v1"
    return {
        "id": stable("claim", rule, subject),
        "text": edge_text(subject) if relation else symbol_text(subject),
        "status": "inferred",
        "evidence_ids": [],
        "reason": "Awaiting deterministic verification.",
        "rule": rule,
        "subject_id": subject["id"],
    }


def knowledge(
    snapshot: dict[str, Any],
    manifest: dict[str, Any],
    structural: dict[str, Any],
    graph: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    claims = [claim_for(s) for s in structural["symbols"]]
    edges = deepcopy(graph["edges"])
    for edge in edges:
        subject = deepcopy(edge)
        claim = claim_for(subject, True)
        edge["claim_ids"] = [claim["id"]]
        claims.append(claim)
    return {
        "repository": snapshot,
        "scope": graph["entrypoints"]["scope"],
        "stack": sorted(
            {s["parser_language"] for s in structural["symbols"] if s["kind"] == "module"}
        ),
        "frameworks": graph["entrypoints"]["frameworks"],
        "purpose_candidates": [],
        "modules": sorted(s["path"] for s in structural["symbols"] if s["kind"] == "module"),
        "symbols": structural["symbols"],
        "nodes": graph["nodes"],
        "edges": edges,
        "entrypoints": graph["entrypoints"],
        "execution_flows": qualified_flows(graph),
        "dependencies": config["dependencies"],
        "claims": claims,
        "coverage": manifest,
        "limitations": graph["limitations"]
        + graph["entrypoints"]["uncertainty"]
        + [
            "Project purpose requires independent semantic review; no purpose is invented.",
            "Whole-file parse errors are excluded from verified evidence and coverage.",
            "Documentation assertions cannot establish runtime or implementation behavior.",
        ],
        "versions": {
            "parser": PARSER_VERSION,
            "pipeline": PIPELINE,
            "rules": RULES,
            "schema": "analysis-1.0",
        },
    }


def catalog(
    root: Path,
    snapshot: dict[str, Any],
    snapshot_id: str,
    pkm: dict[str, Any],
) -> dict[str, Any]:
    symbols = {s["id"]: s for s in pkm["symbols"]}
    evidence: dict[str, dict[str, Any]] = {}
    for symbol in symbols.values():
        body = (root / symbol["path"]).read_bytes()
        if digest(body) != symbol["file_sha256"]:
            raise AnalysisError("source_changed")
        lines = body.decode("utf-8").split("\n")
        start, end = symbol["start_line"], symbol["end_line"]
        if not 1 <= start <= end <= len(lines):
            raise AnalysisError("invalid_evidence_range")
        excerpt, redactions = redact("\n".join(lines[start - 1 : min(end, start + 19)]))
        for redaction in redactions:
            redaction["start_line"] = int(redaction["start_line"]) + start - 1
            redaction["end_line"] = int(redaction["end_line"]) + start - 1
        item = {
            "id": stable("e", snapshot_id, snapshot["commit_sha"], symbol),
            "snapshot_id": snapshot_id,
            "commit_sha": snapshot["commit_sha"],
            "path": symbol["path"],
            "start_line": start,
            "end_line": end,
            "file_sha256": symbol["file_sha256"],
            "symbol_id": symbol["id"],
            "kind": evidence_kind(symbol),
            "rule": symbol["rule"],
            "redacted": bool(redactions),
            "redactions": redactions,
            "excerpt": excerpt[:4096],
            "excerpt_end_line": min(end, start + 19),
            "permalink": permalink(snapshot, symbol),
            "validation_status": "pending",
            "last_checked_at": datetime.now(UTC).isoformat(),
        }
        evidence[symbol["id"]] = item
    edges = {e["id"]: e for e in pkm["edges"]}
    for claim in pkm["claims"]:
        support = (
            [claim["subject_id"]]
            if claim["rule"] == "symbol-fact-v1"
            else edges[claim["subject_id"]]["support_ids"]
        )
        claim["evidence_ids"] = [evidence[s]["id"] for s in support if s in evidence]
    return {"items": sorted(evidence.values(), key=lambda e: e["id"])}


def verify(
    root: Path,
    snapshot: dict[str, Any],
    snapshot_id: str,
    manifest: dict[str, Any],
    pkm: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    # Re-extract original bytes; candidate symbols/edges/status/confidence are never authority.
    actual: dict[str, dict[str, Any]] = {}
    if (
        pkm["repository"] != snapshot
        or pkm["coverage"] != manifest
        or manifest["commit_sha"] != snapshot["commit_sha"]
    ):
        raise AnalysisError("insufficient_evidence")
    for file in manifest["files"]:
        path = (root / file["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or path.is_symlink():
            raise AnalysisError("source_changed")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != file["file_sha256"]:
                raise AnalysisError("source_changed")
        if file["status"] != "parsed":
            continue
        if not path.is_file() or digest(path.read_bytes()) != file["file_sha256"]:
            raise AnalysisError("source_changed")
        found, errors = parse_file(file["path"], path.read_bytes(), file["language"])
        if errors:
            raise AnalysisError("insufficient_evidence")
        actual.update((s["id"], s) for s in found)
    actual.update((s["id"], s) for s in context_symbols(root, manifest))
    if {s["id"]: s for s in pkm["symbols"]} != actual:
        raise AnalysisError("insufficient_evidence")
    expected_config = configuration(root, manifest)
    expected_entries = entrypoints({"symbols": list(actual.values())}, expected_config, manifest)
    if (
        pkm["entrypoints"] != expected_entries
        or pkm["frameworks"] != expected_entries["frameworks"]
    ):
        raise AnalysisError("insufficient_evidence")
    if pkm["modules"] != sorted(s["path"] for s in actual.values() if s["kind"] == "module"):
        raise AnalysisError("insufficient_evidence")
    if pkm["dependencies"] != expected_config["dependencies"]:
        raise AnalysisError("insufficient_evidence")
    graph = infer({"symbols": list(actual.values())}, pkm["entrypoints"])
    if pkm["execution_flows"] != qualified_flows(graph):
        raise AnalysisError("insufficient_evidence")
    actual_edges = {e["id"]: e for e in graph["edges"]}
    candidates = {e["id"]: {k: v for k, v in e.items() if k != "claim_ids"} for e in pkm["edges"]}
    if candidates != actual_edges or pkm["nodes"] != graph["nodes"]:
        raise AnalysisError("insufficient_evidence")
    items = evidence["items"]
    if len({e["id"] for e in items}) != len(items) or len({c["id"] for c in pkm["claims"]}) != len(
        pkm["claims"]
    ):
        raise AnalysisError("duplicate_grounding_id")
    valid: dict[str, dict[str, Any]] = {}
    for item in items:
        symbol = actual.get(item["symbol_id"])
        ok = symbol is not None and (
            item["snapshot_id"] == snapshot_id
            and item["commit_sha"] == snapshot["commit_sha"]
            and item["id"] == stable("e", snapshot_id, snapshot["commit_sha"], symbol)
            and all(
                item[key] == symbol[key]
                for key in ["path", "start_line", "end_line", "file_sha256", "rule"]
            )
            and item["kind"] == evidence_kind(symbol)
        )
        if ok and symbol is not None:
            original = (root / symbol["path"]).read_bytes().decode().split("\n")
            safe, spans = redact(
                "\n".join(
                    original[
                        symbol["start_line"] - 1 : min(
                            symbol["end_line"], symbol["start_line"] + 19
                        )
                    ]
                )
            )
            for span in spans:
                span["start_line"] = int(span["start_line"]) + symbol["start_line"] - 1
                span["end_line"] = int(span["end_line"]) + symbol["start_line"] - 1
            expected_url = permalink(snapshot, symbol)
            ok = (
                item["excerpt"] == safe[:4096]
                and item["redactions"] == spans
                and item["redacted"] == bool(spans)
                and item["permalink"] == expected_url
                and item["excerpt_end_line"] == min(symbol["end_line"], symbol["start_line"] + 19)
            )
        item["validation_status"] = "valid" if ok else "invalid"
        item["last_checked_at"] = datetime.now(UTC).isoformat()
        if ok:
            valid[item["id"]] = item
    verdicts: list[dict[str, Any]] = []
    for claim in pkm["claims"]:
        subject = (
            actual.get(claim["subject_id"])
            if claim["rule"] == "symbol-fact-v1"
            else actual_edges.get(claim["subject_id"])
        )
        relation = claim["rule"] == "edge-fact-v1"
        status, reason = "unsupported", "Missing or mismatched deterministic structural support."
        support_ids = subject["support_ids"] if subject and relation else [claim["subject_id"]]
        expected_evidence = {
            stable("e", snapshot_id, snapshot["commit_sha"], actual[s])
            for s in support_ids
            if s in actual
        }
        if (
            subject is not None
            and claim["rule"] in {"symbol-fact-v1", "edge-fact-v1"}
            and (
                claim["id"] == claim_for(subject, relation)["id"]
                and claim["text"] == (edge_text(subject) if relation else symbol_text(subject))
                and expected_evidence
                and set(claim["evidence_ids"]) == expected_evidence
                and all(e in valid for e in expected_evidence)
            )
        ):
            status = (
                "inferred" if relation and subject["classification"] == "unresolved" else "verified"
            )
            if subject.get("kind") == "documentation":
                status = "documentation_only"
            reason = (
                "Checked original SHA/path/hash/range and exact static rule; no runtime assertion."
            )
            if status == "inferred":
                reason = "Observed syntax; target binding/dynamic behavior remains unresolved."
            if subject.get("qualification") == "redacted_syntax" or any(
                actual[s].get("qualification") == "redacted_syntax"
                for s in support_ids
                if s in actual
            ):
                status, reason = (
                    "unsupported",
                    "Redacted symbol material cannot support factual claims.",
                )
        claim["status"], claim["reason"] = status, reason
        verdicts.append(
            {
                "claim_id": claim["id"],
                "status": status,
                "evidence_ids": claim["evidence_ids"],
                "rule": claim["rule"],
                "reason": reason,
                "conflict_ids": [],
            }
        )
    if not any(v["status"] == "verified" for v in verdicts):
        raise AnalysisError("insufficient_evidence")
    docs = {s["name"] for s in actual.values() if s["kind"] == "documentation"}
    imports = {s["name"] for s in actual.values() if s["kind"] == "import"}
    frameworks = imports & {"fastapi", "flask", "express"}
    conflicts = [
        f"Documentation mentions {name} while implementation imports "
        f"{', '.join(sorted(frameworks))}; "
        "potential scope conflict requires independent review."
        for name in sorted(docs - imports)
        if frameworks
    ]
    return {
        "verifier_version": RULES,
        "verdicts": verdicts,
        "counts": {
            s: sum(v["status"] == s for v in verdicts)
            for s in ["verified", "inferred", "documentation_only", "unsupported"]
        },
        "conflicts": conflicts,
        "scope": "Deterministic static facts; semantic claims require independent review.",
    }

import json
import posixpath
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from repovox.analysis.common import RULES, AnalysisError, digest, stable
from repovox.analysis.privacy import redact

# Rules require an imported binding and an application construction, not a README word.
FRAMEWORKS = {"fastapi": {"FastAPI"}, "flask": {"Flask"}, "express": {"express"}}
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "route", "options", "head"}


def safe_text(value: str) -> str:
    result = redact(value)[0]
    if len(result) > 1024:
        raise AnalysisError("analysis_fact_limit")
    return result


def configuration(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    dependencies: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    for file in manifest["files"]:
        if file["status"] != "context" or file["classification"] != "configuration":
            continue
        path = file["path"]
        body = (root / path).read_bytes()
        if digest(body) != file["file_sha256"]:
            raise AnalysisError("source_changed")
        try:
            config = (
                json.loads(body) if path.endswith("package.json") else tomllib.loads(body.decode())
            )
            # Declarative readers only. Reject deeply nested JSON instead of recursive processing.
            stack = [(config, 0)]
            while stack:
                value, depth = stack.pop()
                if depth > 32:
                    raise ValueError
                if isinstance(value, dict):
                    stack.extend((v, depth + 1) for v in value.values())
                elif isinstance(value, list):
                    stack.extend((v, depth + 1) for v in value)
            if path.endswith("package.json"):
                for name, constraint in config.get("dependencies", {}).items():
                    if isinstance(name, str) and isinstance(constraint, str):
                        dependencies.append(
                            {
                                "name": safe_text(name),
                                "declared_constraint": safe_text(constraint),
                                "locked_version": None,
                                "path": path,
                            }
                        )
                for field in ["main", "module", "bin"]:
                    value = config.get(field)
                    values = value.values() if isinstance(value, dict) else [value]
                    for target in values:
                        if isinstance(target, str) and len(target) <= 255:
                            entries.append(
                                {
                                    "path": path,
                                    "target": safe_text(target),
                                    "rule": "package-entry-v1",
                                }
                            )
                # Lifecycle scripts are never executed or exposed as commands.
            else:
                project = config.get("project", {})
                for constraint in project.get("dependencies", []):
                    if isinstance(constraint, str):
                        match = re.match(r"[A-Za-z0-9_.-]+", constraint)
                        if match:
                            dependencies.append(
                                {
                                    "name": match.group().lower(),
                                    "declared_constraint": safe_text(constraint),
                                    "locked_version": None,
                                    "path": path,
                                }
                            )
                for name, target in project.get("scripts", {}).items():
                    if isinstance(name, str) and isinstance(target, str):
                        entries.append(
                            {
                                "path": path,
                                "target": safe_text(target),
                                "rule": "pyproject-cli-v1",
                            }
                        )
        except (ValueError, TypeError, AttributeError, RecursionError):
            errors.append(path)
    return {"dependencies": dependencies, "config_entries": entries, "config_errors": errors}


def entrypoints(
    structural: dict[str, Any], config: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    symbols = sorted(structural["symbols"], key=lambda s: s["id"])
    candidates: list[dict[str, Any]] = []
    frameworks: list[dict[str, Any]] = []
    tests = {f["path"] for f in manifest["files"] if f["classification"] == "test"}
    for symbol in symbols:
        if symbol["kind"] in {"documentation", "config_entry", "declared_dependency"}:
            continue
        if symbol["kind"] == "entrypoint":
            candidates.append(
                {
                    "symbol_id": symbol["id"],
                    "path": symbol["path"],
                    "rule": symbol["rule"],
                    "support_ids": [symbol["id"]],
                    "rank": 100 if symbol["path"] not in tests else 10,
                }
            )
        if symbol["kind"] != "import" or symbol["name"] not in FRAMEWORKS:
            continue
        framework = symbol["name"]
        frameworks.append(
            {"name": framework, "symbol_id": symbol["id"], "qualification": "import_observed"}
        )
        alias = symbol.get("alias", "")
        if framework == "express":
            match = re.fullmatch(r"([A-Za-z_$][\w$]*)", alias)
            alias = match.group(1) if match else ""
        for call in symbols:
            if (
                call["path"] == symbol["path"]
                and call["kind"] == "call"
                and call["name"] == alias
                and alias
            ):
                # Python from-import name must be an explicitly recognized constructor.
                if (
                    framework != "express"
                    and symbol.get("imported_name") not in FRAMEWORKS[framework]
                ):
                    continue
                candidates.append(
                    {
                        "symbol_id": call["id"],
                        "path": call["path"],
                        "rule": "framework-construction-v1",
                        "support_ids": [symbol["id"], call["id"]],
                        "rank": 90 if call["path"] not in tests else 9,
                    }
                )
                binding = call.get("binding")
                for route in symbols:
                    method = route["name"].removeprefix(str(binding) + ".")
                    if (
                        binding
                        and route["path"] == call["path"]
                        and route["kind"] == "call"
                        and route["name"] == f"{binding}.{method}"
                        and method in ROUTE_METHODS | {"listen"}
                    ):
                        candidates.append(
                            {
                                "symbol_id": route["id"],
                                "path": route["path"],
                                "rule": "framework-route-v1"
                                if method != "listen"
                                else "server-listen-v1",
                                "support_ids": [symbol["id"], call["id"], route["id"]],
                                "rank": 8 if route["path"] in tests else 80,
                                "qualification": "Candidate binding; runtime behavior unresolved.",
                            }
                        )
    for entry in config["config_entries"]:
        modules = {s["path"]: s for s in symbols if s["kind"] == "module"}
        if entry["rule"] == "package-entry-v1":
            target_path = posixpath.normpath(
                posixpath.join(posixpath.dirname(entry["path"]), entry["target"])
            )
        else:
            target_path = entry["target"].split(":")[0].replace(".", "/") + ".py"
        resolved = target_path in modules
        candidates.append(
            {
                "symbol_id": next(
                    s["id"]
                    for s in symbols
                    if s["kind"] == "config_entry"
                    and s["path"] == entry["path"]
                    and s["name"] == entry["target"]
                ),
                "path": entry["path"],
                "rule": entry["rule"],
                "support_ids": [
                    s["id"]
                    for s in symbols
                    if s["kind"] == "config_entry"
                    and s["path"] == entry["path"]
                    and s["name"] == entry["target"]
                ],
                "target": entry["target"],
                "rank": 70 if resolved else 40,
                "qualification": "Declared target exists."
                if resolved
                else "Declared target unresolved.",
            }
        )
    candidates.sort(key=lambda c: (-c["rank"], c["path"], c["symbol_id"]))
    selected = next((c["symbol_id"] for c in candidates if c["rank"] >= 70), None)
    return {
        "candidates": candidates,
        "selected": selected,
        "frameworks": frameworks,
        "scope": (
            "All eligible supported source; tests deprioritized; selection is a static candidate."
        ),
        "uncertainty": [] if selected else ["No reliable entrypoint was identified."],
    }


def resolve_import(path: str, target: str, lang: str, modules: dict[str, str]) -> str | None:
    if lang == "python":
        if target.startswith("."):
            count = len(target) - len(target.lstrip("."))
            parent = PurePosixPath(path).parent
            for _ in range(count - 1):
                parent = parent.parent
            stem = (parent / target[count:].replace(".", "/")).as_posix()
        else:
            stem = target.replace(".", "/")
        possibilities = [stem + ".py", stem + "/__init__.py"]
    elif target.startswith("."):
        stem = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
        possibilities = (
            [stem]
            + [stem + ext for ext in [".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"]]
            + [stem + "/index" + ext for ext in [".js", ".ts", ".tsx"]]
        )
    else:
        return None
    found = [modules[p] for p in possibilities if p in modules]
    return found[0] if len(found) == 1 else None


def infer(structural: dict[str, Any], entries: dict[str, Any]) -> dict[str, Any]:
    symbols = sorted(structural["symbols"], key=lambda s: s["id"])
    modules = {s["path"]: s["id"] for s in symbols if s["kind"] == "module"}
    nodes = [
        {"id": s["id"], "kind": s["kind"], "path": s["path"], "name": s["name"]} for s in symbols
    ]
    edges: list[dict[str, Any]] = []
    for symbol in symbols:
        target: str | None = None
        relationship = "contains"
        classification = "declared"
        if symbol["kind"] in {"module", "documentation", "config_entry", "declared_dependency"}:
            continue
        if symbol["kind"] == "import":
            relationship = "imports"
            target = resolve_import(
                symbol["path"], symbol["name"], symbol["parser_language"], modules
            )
            classification = "resolved_static" if target else "unresolved"
        elif symbol["kind"] == "call":
            relationship = "call_expression"
            # No lexical binding/dataflow analysis in v1: even matching names stay unresolved.
            classification = "unresolved"
        if target is None:
            target = symbol["id"]
        edges.append(
            {
                "id": stable("edge", modules[symbol["path"]], target, relationship, symbol["id"]),
                "source": modules[symbol["path"]],
                "target": target,
                "relationship": relationship,
                "classification": classification,
                "support_ids": [symbol["id"]],
                "rule": "graph-syntax-v1",
                "qualification": "Static syntax only; no runtime execution asserted.",
            }
        )
    return {
        "nodes": nodes,
        "edges": sorted(edges, key=lambda e: e["id"]),
        "entrypoints": entries,
        "rule_version": RULES,
        "limitations": [
            "Call targets remain unresolved without lexical binding and dataflow proof.",
            (
                "Import resolution uses literal local paths; aliases, package"
                " search paths and dynamic imports remain uncertain."
            ),
            "No runtime, correctness, performance or security conclusions are supported.",
            "External-service strings are not certified as successful connections.",
        ],
    }


def qualified_flows(graph: dict[str, Any]) -> list[dict[str, Any]]:
    modules = {n["path"]: n["id"] for n in graph["nodes"] if n["kind"] == "module"}
    flows: list[dict[str, Any]] = []
    for candidate in graph["entrypoints"]["candidates"][:8]:
        if candidate["rank"] < 70:
            continue
        path = candidate["path"]
        if path not in modules and candidate.get("target"):
            path = posixpath.normpath(posixpath.join(posixpath.dirname(path), candidate["target"]))
        start = modules.get(path)
        if start is None:
            continue
        reached = {start}
        edges: set[str] = set()
        frontier = [start]
        for _ in range(8):
            following = []
            for edge in graph["edges"]:
                if (
                    edge["source"] in frontier
                    and edge["relationship"] == "imports"
                    and edge["classification"] == "resolved_static"
                ):
                    edges.add(edge["id"])
                    if edge["target"] not in reached and len(reached) < 64:
                        reached.add(edge["target"])
                        following.append(edge["target"])
            frontier = sorted(following)
            if not frontier:
                break
        flows.append(
            {
                "id": stable("flow", candidate["symbol_id"], sorted(edges)),
                "entrypoint_id": candidate["symbol_id"],
                "module_id": start,
                "node_ids": sorted(reached),
                "edge_ids": sorted(edges),
                "qualification": "Static import reachability from a candidate module; "
                "execution order and call binding are unknown.",
            }
        )
    return flows

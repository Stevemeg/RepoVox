"""Qualified relationships supported by bounded lexical and local-module syntax."""

from typing import Any

from repovox.analysis.common import stable


def qualified_edges(symbols: list[dict[str, Any]], modules: dict[str, str]) -> list[dict[str, Any]]:
    from repovox.analysis.graph import resolve_import

    indexed = {s["id"]: s for s in symbols}
    imports = [s for s in symbols if s["kind"] == "import"]
    adjacency: dict[str, set[str]] = {}
    imported_modules: dict[str, str] = {}
    for s in imports:
        target = resolve_import(s["path"], s["name"], s["parser_language"], modules)
        if target:
            imported_modules[s["id"]] = target
            adjacency.setdefault(modules[s["path"]], set()).add(target)

    def cyclic(source: str, target: str) -> bool:
        visited: set[str] = set()
        pending = [target]
        while pending:
            current = pending.pop()
            if current == source or len(visited) > 1024:
                return True
            if current not in visited:
                visited.add(current)
                pending.extend(adjacency.get(current, set()) - visited)
        return False

    resolved: dict[str, str] = {}
    edges: list[dict[str, Any]] = []

    def edge(source: str, target: str, relation: str, support: list[str]) -> None:
        support = sorted(set(support))
        edges.append(
            {
                "id": stable("edge", source, target, relation, support),
                "source": source,
                "target": target,
                "relationship": relation,
                "classification": "resolved_static",
                "support_ids": support,
                "rule": "qualified-binding-v2",
                "qualification": "Unique local static binding; runtime execution is unknown.",
            }
        )

    for s in imports:
        meta = s["syntax"]
        module = imported_modules.get(s["id"])
        if (
            not module
            or meta["unsafe_binding"]
            or meta["type_only"]
            or not meta["imported_member"]
            or cyclic(modules[s["path"]], module)
        ):
            continue
        member = meta["imported_member"]
        found = [
            candidate
            for candidate in symbols
            if candidate["path"] == indexed[module]["path"]
            and candidate["kind"] in {"class", "function"}
            and not candidate["syntax"]["scope"]
            and not candidate["syntax"]["unsafe_binding"]
            and (
                (
                    candidate["name"] == member
                    and (s["parser_language"] == "python" or candidate["syntax"]["exported"])
                )
                or (member == "default" and candidate["syntax"]["default_export"])
            )
        ]
        if len(found) == 1:
            target = found[0]["id"]
            resolved[s["id"]] = target
            edge(s["id"], target, "imports_symbol", [s["id"], target])
    for s in symbols:
        meta = s["syntax"]
        lexical = meta["lexical_target_id"]
        enclosing = meta["enclosing_symbol_id"]
        target = resolved.get(lexical, lexical)
        if not target or not enclosing or indexed[target]["syntax"]["unsafe_binding"]:
            continue
        support = [s["id"], enclosing, target]
        if lexical != target:
            support.append(lexical)
        if (
            s["kind"] == "base_reference"
            and indexed[target]["kind"] == "class"
            and target != enclosing
        ):
            edge(enclosing, target, "inherits", support)
        elif s["kind"] == "call" and not meta["unsafe_binding"]:
            if meta["constructor"] and indexed[target]["kind"] == "class":
                edge(enclosing, target, "instantiates", support)
            elif not meta["constructor"] and indexed[target]["kind"] == "function":
                edge(enclosing, target, "calls_lexically", support)
    return edges

"""Conservative lexical bindings from syntax; never runtime dataflow proof."""

import time
from collections import defaultdict
from typing import Any

from tree_sitter import Node

from repovox.analysis.common import AnalysisError
from repovox.analysis.facts import Syntax

DECL = {
    "function_definition",
    "function_declaration",
    "generator_function_declaration",
    "arrow_function",
    "function_expression",
    "method_definition",
    "class_definition",
    "class_declaration",
}
CONDITIONAL = {
    "if_statement",
    "for_statement",
    "while_statement",
    "try_statement",
    "switch_case",
    "catch_clause",
    "conditional_expression",
    "with_statement",
}


def annotate(root: Node, body: bytes, lang: str, symbols: list[dict[str, Any]]) -> None:
    # Imported lazily to keep parser helpers and lexical analysis in one bounded parse.
    from repovox.analysis.parser import parameter_names, text, walk

    deadline = time.monotonic() + 2

    def checkpoint() -> None:
        if time.monotonic() >= deadline:
            raise AnalysisError("parser_resource_limit")

    nodes = {(n.start_byte, n.end_byte): n for n in walk(root)}
    declarations = {
        s["start_byte"]: s for s in symbols if s["kind"] in {"function", "method", "class"}
    }

    def ancestors(n: Node) -> list[Node]:
        checkpoint()
        result: list[Node] = []
        p = n.parent
        while p:
            if len(result) >= 512:
                raise AnalysisError("parser_resource_limit")
            result.append(p)
            p = p.parent
        return result

    def scope(n: Node) -> tuple[int, ...]:
        return tuple(
            reversed(
                [
                    p.start_byte
                    for p in ancestors(n)
                    if p.type in DECL or (lang != "python" and p.type == "statement_block")
                ]
            )
        )

    bindings: dict[tuple[tuple[int, ...], str], list[str | None]] = defaultdict(list)
    indexed = {s["id"]: s for s in symbols}
    for s in symbols:
        node = nodes[(s["start_byte"], s["end_byte"])]
        parents = ancestors(node)
        enclosing = next(
            (
                declarations[p.start_byte]
                for p in parents
                if p.start_byte in declarations and p.type in DECL
            ),
            None,
        )
        names = [
            declarations[p.start_byte]["name"]
            for p in reversed(parents)
            if p.type in DECL and p.start_byte in declarations
        ]
        export_parent = None
        for parent in parents:
            if parent.type == "export_statement":
                export_parent = parent
                break
            if parent.type in DECL or parent.type in {"object", "pair", "statement_block"}:
                break
        meta = Syntax(
            category=s["kind"],
            qualified_name=".".join([*names, s["name"]]),
            scope=[str(x) for x in scope(node)],
            enclosing_symbol_id=enclosing["id"] if enclosing else None,
            unsafe_binding=any(
                p.type in CONDITIONAL or p.type == "decorated_definition" for p in parents
            )
            or node.type == "function_expression",
            constructor=node.type == "new_expression",
            exported=export_parent is not None,
            default_export=any(
                p.type == "export_statement" and any(c.type == "default" for c in p.children)
                for p in [node, *([export_parent] if export_parent else [])]
            ),
        )
        if s["kind"] == "import":
            member = s.get("imported_name")
            if lang == "python" and node.type == "import_statement":
                member = None
            meta.category = "import_member" if member else "import_module"
            meta.import_module = s["name"]
            meta.imported_member = member
            meta.local_binding = s.get("alias") or None
            meta.type_only = any(c.type == "type" for c in node.children) or bool(
                s.pop("_type_only", False)
            )
        if s["kind"] in {"function", "class", "import"}:
            name = meta.local_binding if s["kind"] == "import" else s["name"]
            if name and name != "anonymous":
                bindings[(scope(node), name)].append(s["id"])
        s["syntax"] = meta.model_dump()

    # All writes block resolution, including writes occurring after a call. This is
    # deliberately conservative; no control-flow execution order is assumed.
    written_names: set[str] = set()
    complex_parameters = False
    for n in nodes.values():
        checkpoint()
        if n.type in DECL:
            params = n.child_by_field_name("parameters") or n.child_by_field_name("parameter")
            inner = (*scope(n), n.start_byte)
            block = n.child_by_field_name("body")
            if lang != "python" and block and block.type == "statement_block":
                inner = (*inner, block.start_byte)
            for name in parameter_names(params, body):
                bindings[(inner, name)].append(None)
                if not name.isidentifier():
                    complex_parameters = True
        if n.type in {
            "assignment",
            "augmented_assignment",
            "assignment_expression",
            "augmented_assignment_expression",
            "variable_declarator",
            "update_expression",
            "for_in_statement",
            "for_statement",
            "named_expression",
            "delete_statement",
        }:
            target = (
                n.child_by_field_name("left")
                or n.child_by_field_name("name")
                or n.child_by_field_name("argument")
            )
            value = n.child_by_field_name("value") or n.child_by_field_name("right")
            # Function-valued lexical declarations already registered above.
            if value and value.type in DECL and n.type == "variable_declarator":
                continue
            if target:
                for ident in walk(target):
                    if ident.type in {"identifier", "shorthand_property_identifier_pattern"}:
                        bindings[(scope(n), text(ident, body))].append(None)
                        written_names.add(text(ident, body))
        if n.type in {"global_statement", "nonlocal_statement"}:
            for child in n.named_children:
                bindings[(scope(n), text(child, body))].append(None)

    # eval/with and star imports prevent safe lexical conclusions in this file.
    hazardous = complex_parameters or any(
        n.type
        in {
            "with_statement",
            "lambda",
            "lambda_expression",
            "list_comprehension",
            "dictionary_comprehension",
            "set_comprehension",
            "generator_expression",
            "except_clause",
            "match_statement",
        }
        for n in nodes.values()
    )
    hazardous |= any(
        s["kind"] == "call"
        and s["name"] in {"eval", "exec", "globals", "locals"}
        or s.get("imported_name") == "*"
        for s in symbols
    )
    for s in symbols:
        node = nodes[(s["start_byte"], s["end_byte"])]
        meta = s["syntax"]
        binding = meta["local_binding"] if s["kind"] == "import" else s["name"]
        key = (scope(node), binding)
        if s["kind"] in {"function", "class", "import"}:
            meta["unsafe_binding"] |= (
                hazardous or len(bindings[key]) != 1 or binding in written_names
            )
    for s in symbols:
        node = nodes[(s["start_byte"], s["end_byte"])]
        meta = s["syntax"]
        if s["kind"] not in {"call", "base_reference"} or hazardous:
            continue
        if s["kind"] == "call" and s.get("dispatch") != "named":
            continue
        chain = scope(node)
        if s["kind"] == "base_reference" and chain:
            chain = chain[:-1]
        while True:
            values = bindings.get((chain, s["name"]))
            if values:
                bound = indexed.get(values[0] or "") if len(values) == 1 else None
                if (
                    bound
                    and not bound["syntax"]["unsafe_binding"]
                    and not (
                        s["kind"] == "base_reference" and bound["start_byte"] >= s["start_byte"]
                    )
                ):
                    meta["lexical_target_id"] = bound["id"]
                break
            if not chain:
                break
            chain = chain[:-1]
            # A Python class namespace is not a function's lexical closure.
            if (
                lang == "python"
                and chain
                and chain[-1] in declarations
                and declarations[chain[-1]]["kind"] == "class"
            ):
                chain = chain[:-1]
    for s in symbols:
        meta = s["syntax"]
        checkpoint()
        if s["kind"] == "plugin_registration" and not meta["scope"]:
            meta["candidate_category"] = "plugin"
        if (
            lang == "python"
            and s["kind"] == "function"
            and not meta["scope"]
            and s["name"]
            in {
                "_jupyter_server_extension_points",
                "_jupyter_server_extension_paths",
                "_jupyter_labextension_paths",
                "_jupyter_nbextension_paths",
            }
        ):
            meta["candidate_category"] = "packaging_hook"
        if lang == "python" and s["kind"] in {"decorator", "call"}:
            head = s["name"].lstrip("@").split("(")[0]
            for imported in symbols:
                im = imported["syntax"]
                if (
                    imported["kind"] != "import"
                    or im["unsafe_binding"]
                    or im["scope"] != meta["scope"]
                ):
                    continue
                module, member, binding = (
                    im["import_module"],
                    im["imported_member"],
                    im["local_binding"],
                )
                if (
                    module == "click"
                    and (
                        (member in {"command", "group"} and head == binding)
                        or (not member and head in {f"{binding}.command", f"{binding}.group"})
                    )
                    and s["kind"] == "decorator"
                ):
                    meta["candidate_category"] = "candidate_command"
                if (
                    module == "setuptools"
                    and (
                        (member == "setup" and head == binding)
                        or (not member and head == f"{binding}.setup")
                    )
                    and s["kind"] == "call"
                ):
                    meta["candidate_category"] = "packaging_hook"
        if s["kind"] == "export" and meta["default_export"]:
            meta["candidate_category"] = "library_export"
            node = nodes[(s["start_byte"], s["end_byte"])]
            value = node.child_by_field_name("value")
            objects = [value] if value and value.type == "object" else []
            if value and value.type == "identifier":
                # Only a unique, unrebound top-level const object can establish registration syntax.
                for n in nodes.values():
                    if (
                        n.type == "variable_declarator"
                        and text(n.child_by_field_name("name"), body) == text(value, body)
                        and not scope(n)
                    ):
                        declaration_parent = n.parent
                        obj = n.child_by_field_name("value")
                        if (
                            declaration_parent
                            and any(c.type == "const" for c in declaration_parent.children)
                            and obj
                            and obj.type == "object"
                            and len(bindings[((), text(value, body))]) == 1
                        ):
                            objects.append(obj)
                            meta["candidate_support_ids"] = [
                                item["id"]
                                for item in symbols
                                if item["kind"] == "plugin_registration"
                                and item["start_byte"] == n.start_byte
                            ]
            for obj in objects:
                keys = {
                    text(c.child_by_field_name("key"), body).strip("\"'")
                    for c in obj.named_children
                    if c.type == "pair"
                }
                if {"id", "activate"} <= keys:
                    meta["candidate_category"] = "plugin"

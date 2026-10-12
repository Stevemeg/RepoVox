import ast
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from repovox.analysis.common import (
    DEFAULT_LIMITS,
    PARSER_VERSION,
    RULES,
    AnalysisError,
    Limits,
    digest,
    stable,
)
from repovox.analysis.privacy import redact

DECLARATIONS = {
    "class_definition": "class",
    "class_declaration": "class",
    "function_definition": "function",
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "method_definition": "method",
    "arrow_function": "function",
    "function_expression": "function",
}


def walk(root: Node) -> Iterator[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.named_children))


def text(node: Node | None, body: bytes) -> str:
    if node is None:
        return ""
    value = body[node.start_byte : node.end_byte].decode("utf-8")
    safe = redact(value)[0]
    if len(safe) > 1024:
        raise AnalysisError("analysis_fact_limit")
    return safe


def locations(node: Node) -> tuple[int, int]:
    start = node.start_point.row + 1
    end = node.end_point.row + (1 if node.end_point.column else 0)
    return start, max(start, end)


def language(name: str) -> Language:
    capsules = {
        "python": tree_sitter_python.language,
        "javascript": tree_sitter_javascript.language,
        "typescript": tree_sitter_typescript.language_typescript,
        "tsx": tree_sitter_typescript.language_tsx,
    }
    return Language(capsules[name]())


def parameter_names(node: Node | None, body: bytes) -> list[str]:
    if node is None:
        return []
    if node.type == "identifier":
        return [text(node, body)]
    result: list[str] = []
    for parameter in node.named_children:
        target: Node | None
        if parameter.type in {"keyword_separator", "positional_separator"}:
            continue
        if parameter.type == "identifier":
            target = parameter
        else:
            target = (
                parameter.child_by_field_name("name")
                or parameter.child_by_field_name("pattern")
                or parameter.child_by_field_name("left")
                or (parameter.named_children[0] if parameter.named_children else None)
            )
        if target:
            result.append(text(target, body))
    return result


def parse_file(
    path: str, body: bytes, lang: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parser = Parser(language(lang), timeout_micros=1_000_000)
    # Native parsing is bounded; the outer container also enforces wall/CPU/memory.
    try:
        tree = parser.parse(body)
    except ValueError:
        raise AnalysisError("parser_timeout") from None
    root = tree.root_node
    if root.has_error:
        errors = []
        for node in walk(root):
            if node.type == "ERROR" or node.is_missing:
                start, end = locations(node)
                errors.append({"path": path, "start_line": start, "end_line": end})
        return [], errors or [
            {"path": path, "start_line": 1, "end_line": max(1, body.count(b"\n"))}
        ]
    symbols: list[dict[str, Any]] = []

    def record(node: Node, kind: str, name: str, rule: str, **extra: Any) -> dict[str, Any]:
        name = redact(name)[0]
        for key, value in extra.items():
            if isinstance(value, str):
                extra[key] = redact(value)[0]
        if len(name) > 1024:
            raise AnalysisError("analysis_fact_limit")
        redacted_name = "[REDACTED]" in name or "[REDACTED]" in str(extra)
        start, end = locations(node)
        item = {
            "id": stable("s", path, node.start_byte, node.end_byte, kind, name, extra),
            "path": path,
            "start_line": start,
            "end_line": end,
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
            "kind": kind,
            "name": name,
            "file_sha256": digest(body),
            "parser_language": lang,
            "parser_version": PARSER_VERSION,
            "rule": rule,
            "qualification": "redacted_syntax" if redacted_name else "observed_syntax",
            **extra,
        }
        symbols.append(item)
        return item

    record(root, "module", path, "module-v1")
    deadline = time.monotonic() + 2
    nodes = 0
    for node in walk(root):
        nodes += 1
        if nodes > 200_000 or time.monotonic() >= deadline:
            raise AnalysisError("parser_resource_limit")
        if node.type in DECLARATIONS:
            name = text(node.child_by_field_name("name"), body)
            if not name and node.parent and node.parent.type == "variable_declarator":
                name = text(node.parent.child_by_field_name("name"), body)
            name = name or "anonymous"
            params = node.child_by_field_name("parameters") or node.child_by_field_name("parameter")
            kind = DECLARATIONS[node.type]
            if lang == "python" and kind == "function":
                parent = node.parent
                while parent and parent.type in {"block", "decorated_definition"}:
                    parent = parent.parent
                if parent and parent.type == "class_definition":
                    kind = "method"
            record(
                node,
                kind,
                name,
                "declaration-v1",
                parameters=parameter_names(params, body),
            )
        elif node.type in {"call", "call_expression", "new_expression"}:
            target = node.child_by_field_name("function") or node.child_by_field_name("constructor")
            parent = node.parent
            binding = ""
            if parent and parent.type in {"assignment", "variable_declarator"}:
                binding = text(
                    parent.child_by_field_name("left") or parent.child_by_field_name("name"), body
                )
            record(
                node,
                "call",
                text(target, body) or "dynamic",
                "call-expression-v1",
                dispatch="named" if target and target.type == "identifier" else "dynamic",
                binding=binding,
            )
            if lang != "python" and text(target, body) == "require":
                args = node.child_by_field_name("arguments")
                if (
                    args
                    and len(args.named_children) == 1
                    and args.named_children[0].type == "string"
                ):
                    record(
                        node,
                        "import",
                        text(args.named_children[0], body)[1:-1],
                        "import-v1",
                        alias=binding,
                    )
        elif node.type in {"import_statement", "import_from_statement"}:
            if lang == "python":
                try:
                    statement = ast.parse(body[node.start_byte : node.end_byte].decode()).body[0]
                    if isinstance(statement, ast.Import):
                        imports = [
                            (a.name, a.asname or a.name.split(".")[0], a.name)
                            for a in statement.names
                        ]
                    elif isinstance(statement, ast.ImportFrom):
                        imports = [
                            (
                                "." * statement.level + (statement.module or ""),
                                a.asname or a.name,
                                a.name,
                            )
                            for a in statement.names
                        ]
                    else:
                        imports = []
                    for import_target, alias, imported in imports:
                        record(
                            node,
                            "import",
                            import_target,
                            "import-v1",
                            alias=alias,
                            imported_name=imported,
                        )
                except (SyntaxError, ValueError):
                    pass
            else:
                source = node.child_by_field_name("source")
                if source:
                    record(
                        node,
                        "import",
                        text(source, body)[1:-1],
                        "import-v1",
                        alias=text(node.named_children[0], body),
                    )
        elif node.type == "export_statement":
            source = node.child_by_field_name("source")
            if source:
                record(node, "import", text(source, body)[1:-1], "import-v1", alias="re-export")
            declared = node.child_by_field_name("declaration")
            record(
                node,
                "export",
                (text(declared.child_by_field_name("name"), body) or "export")
                if declared
                else "export",
                "export-v1",
            )
        elif node.type == "decorator":
            record(node, "decorator", text(node, body), "decorator-v1")
        elif lang == "python" and node.type == "if_statement":
            condition = text(node.child_by_field_name("condition"), body)
            if re.fullmatch(r"__name__\s*==\s*['\"]__main__['\"]", condition):
                record(node, "entrypoint", "__main__", "python-main-v1")
    return symbols, []


def structure(
    root: Path,
    manifest: dict[str, Any],
    limits: Limits = DEFAULT_LIMITS,
    checkpoint: Callable[[], None] = lambda: None,
) -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    parsed = non_test = 0
    for file in manifest["files"]:
        checkpoint()
        if file["status"] != "eligible":
            continue
        body = root.joinpath(file["path"]).read_bytes()
        if digest(body) != file["file_sha256"]:
            raise AnalysisError("source_changed")
        found, failures = parse_file(file["path"], body, file["language"])
        errors.extend(failures)
        if failures:
            file.update(status="failed", reason="parse_error")
        else:
            file.update(status="parsed", reason="parsed_without_errors", parsed_bytes=len(body))
            parsed += len(body)
            non_test += int(file["classification"] == "source")
            symbols.extend(found)
        if len(symbols) > limits.facts or len(errors) > limits.facts:
            raise AnalysisError("analysis_fact_limit")
    manifest["parsed_bytes"] = parsed
    manifest["coverage"] = parsed / manifest["eligible_bytes"] if manifest["eligible_bytes"] else 0
    manifest["parsed_non_test_files"] = non_test
    manifest["language_coverage"] = {}
    for file in manifest["files"]:
        if file["status"] in {"eligible", "parsed", "failed"}:
            totals = manifest["language_coverage"].setdefault(
                file["language"], {"eligible_bytes": 0, "parsed_bytes": 0, "files": 0}
            )
            totals["eligible_bytes"] += file["bytes"]
            totals["parsed_bytes"] += file["parsed_bytes"]
            totals["files"] += 1
    if (
        non_test < 1
        or manifest["eligible_bytes"] == 0
        or parsed * 10 < manifest["eligible_bytes"] * 9
    ):
        raise AnalysisError("insufficient_evidence")
    return {
        "symbols": sorted(symbols, key=lambda s: s["id"]),
        "parse_errors": errors,
        "parser_version": PARSER_VERSION,
        "rule_version": RULES,
    }

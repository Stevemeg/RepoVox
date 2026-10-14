"""Declarative readers with original-byte ranges. No scripts or dependencies run."""

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from repovox.analysis.common import AnalysisError, digest
from repovox.analysis.privacy import redact


def properties(
    body: bytes, json_format: bool
) -> tuple[dict[str, Any], dict[tuple[str, ...], tuple[int, int]]]:
    source = body.decode("utf-8")
    spans: dict[tuple[str, ...], tuple[int, int]] = {}

    def span(start: int, end: int) -> tuple[int, int]:
        return len(source[:start].encode()), len(source[:end].encode())

    if json_format:
        decoder = json.JSONDecoder()

        def whitespace(i: int) -> int:
            while i < len(source) and source[i].isspace():
                i += 1
            return i

        def read(i: int, path: tuple[str, ...], depth: int) -> tuple[Any, int]:
            if depth > 32:
                raise ValueError("config_depth")
            i = whitespace(i)
            if source[i] not in "[{":
                return decoder.raw_decode(source, i)
            is_object = source[i] == "{"
            close = "}" if is_object else "]"
            result: Any = {} if is_object else []
            i = whitespace(i + 1)
            while source[i] != close:
                start = i
                if is_object:
                    key, i = decoder.raw_decode(source, i)
                    if not isinstance(key, str) or key in result:
                        raise ValueError("duplicate_or_invalid_key")
                    i = whitespace(i)
                    if source[i] != ":":
                        raise ValueError("invalid_json")
                    i += 1
                else:
                    key = str(len(result))
                value, i = read(i, (*path, key), depth + 1)
                spans[(*path, key)] = span(start, i)
                if is_object:
                    result[key] = value
                else:
                    result.append(value)
                i = whitespace(i)
                if source[i] == close:
                    break
                if source[i] != ",":
                    raise ValueError("invalid_json")
                i = whitespace(i + 1)
                if source[i] == close:
                    raise ValueError("trailing_comma")
            return result, i + 1

        config, end = read(0, (), 0)
        if source[end:].strip() or not isinstance(config, dict):
            raise ValueError("invalid_json_root")
        return config, spans
    config = tomllib.loads(source)  # Duplicate keys and malformed TOML are rejected here.
    header = ""
    offset = 0
    pending = ""
    start = 0

    def leaves(value: Any, path: tuple[str, ...]) -> list[tuple[str, ...]]:
        if len(path) > 32:
            raise ValueError("config_depth")
        if isinstance(value, dict):
            return [p for k, v in value.items() for p in leaves(v, (*path, k))]
        if isinstance(value, list):
            return [p for i, v in enumerate(value) for p in leaves(v, (*path, str(i)))] or [path]
        return [path]

    for line in source.splitlines(keepends=True):
        stripped = line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            offset += len(line)
            continue
        if not pending and stripped.startswith("["):
            # Array tables are irrelevant to supported packaging properties; skip safely.
            header = line
            offset += len(line)
            continue
        if not pending:
            start = offset
        pending += line
        offset += len(line)
        try:
            piece = tomllib.loads(header + pending)
        except tomllib.TOMLDecodeError:
            continue  # Multiline value; original full document was already validated.
        if not header.lstrip().startswith("[["):
            for key in leaves(piece, ()):
                spans[key] = span(start, offset - len(line) + len(line.rstrip("\r\n")))
        pending = ""
    return config, spans


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
        local_deps: list[dict[str, Any]] = []
        local_entries: list[dict[str, Any]] = []
        try:
            config, spans = properties(body, path.endswith("package.json"))

            def location(
                key: tuple[str, ...],
                spans: dict[tuple[str, ...], tuple[int, int]] = spans,
                path: str = path,
                body: bytes = body,
            ) -> dict[str, Any]:
                begin, end = spans[key]  # No guessed whole-file fallback.
                return {
                    "path": path,
                    "property_path": list(key),
                    "start_byte": begin,
                    "end_byte": end,
                    "start_line": body[:begin].count(b"\n") + 1,
                    "end_line": body[: max(begin, end - 1)].count(b"\n") + 1,
                }

            def safe(value: str) -> str:
                result = redact(value)[0]
                if len(result) > 1024:
                    raise AnalysisError("analysis_fact_limit")
                return result

            def entry(
                key: tuple[str, ...],
                target: Any,
                category: str,
                rule: str,
                local_entries: list[dict[str, Any]] = local_entries,
            ) -> None:
                if isinstance(target, str) and len(target) <= 255:
                    local_entries.append(
                        {
                            **location(key),
                            "target": safe(target),
                            "category": category,
                            "rule": rule,
                        }
                    )

            if path.endswith("package.json"):
                for name, value in config.get("dependencies", {}).items():
                    if isinstance(value, str):
                        local_deps.append(
                            {
                                **location(("dependencies", name)),
                                "name": safe(name),
                                "declared_constraint": safe(value),
                                "locked_version": None,
                            }
                        )
                for field in ["main", "module", "bin", "types", "typings", "exports"]:

                    def targets(value: Any, key: tuple[str, ...], field: str = field) -> None:
                        if isinstance(value, dict):
                            for k, v in value.items():
                                targets(v, (*key, k))
                        elif isinstance(value, list):
                            for i, v in enumerate(value):
                                targets(v, (*key, str(i)))
                        else:
                            category = "candidate_command" if field == "bin" else "library_export"
                            if field in {"types", "typings"} or "types" in key:
                                category = "type_declaration"
                            entry(key, value, category, "package-" + field + "-v2")

                    targets(config.get(field), (field,))
            else:
                project = config.get("project", {})
                for i, value in enumerate(project.get("dependencies", [])):
                    if isinstance(value, str) and (match := re.match(r"[A-Za-z0-9_.-]+", value)):
                        local_deps.append(
                            {
                                **location(("project", "dependencies", str(i))),
                                "name": match.group().lower(),
                                "declared_constraint": safe(value),
                                "locked_version": None,
                            }
                        )
                for name, target in project.get("scripts", {}).items():
                    entry(
                        ("project", "scripts", name),
                        target,
                        "candidate_command",
                        "pyproject-cli-v2",
                    )
                entry(
                    ("build-system", "build-backend"),
                    config.get("build-system", {}).get("build-backend"),
                    "build_system",
                    "python-build-backend-v2",
                )
            dependencies.extend(local_deps)
            entries.extend(local_entries)
        except (ValueError, TypeError, AttributeError, RecursionError, IndexError, KeyError):
            errors.append(path)
    return {"dependencies": dependencies, "config_entries": entries, "config_errors": errors}

"""Documentation mentions are qualified assertions, never implementation proof."""

import re
from pathlib import Path
from typing import Any

from repovox.analysis.common import RULES, digest, stable
from repovox.analysis.facts import Syntax
from repovox.analysis.graph import configuration
from repovox.analysis.privacy import redact

FRAMEWORK_WORDS = ("django", "fastapi", "flask", "express", "react", "nextjs")


def context_symbols(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for file in manifest["files"]:
        if file["status"] != "context" or file["classification"] != "documentation":
            continue
        body = (root / file["path"]).read_bytes()
        offset = 0
        for line_no, line in enumerate(body.split(b"\n"), 1):
            safe = redact(line.decode())[0]
            for name in FRAMEWORK_WORDS:
                if re.search(rf"\b{name}\b", safe, re.IGNORECASE):
                    symbols.append(
                        {
                            "id": stable("doc", file["path"], line_no, name, digest(body)),
                            "path": file["path"],
                            "start_line": line_no,
                            "end_line": line_no,
                            "start_byte": offset,
                            "end_byte": offset + len(line),
                            "kind": "documentation",
                            "name": name,
                            "file_sha256": digest(body),
                            "parser_language": "documentation",
                            "parser_version": RULES,
                            "rule": "documentation-mention-v1",
                            "qualification": "documentation_only",
                        }
                    )
            offset += len(line) + 1
    config = configuration(root, manifest)
    for item, kind in [(entry, "config_entry") for entry in config["config_entries"]] + [
        (dependency, "declared_dependency") for dependency in config["dependencies"]
    ]:
        path = item["path"]
        body = (root / path).read_bytes()
        name = (
            item["target"]
            if kind == "config_entry"
            else f"{item['name']} {item['declared_constraint']}"
        )
        symbols.append(
            {
                "id": stable("config", path, kind, name, item["property_path"], digest(body)),
                "path": path,
                **{k: item[k] for k in ["start_line", "end_line", "start_byte", "end_byte"]},
                "kind": kind,
                "name": name,
                "file_sha256": digest(body),
                "parser_language": "json" if path.endswith(".json") else "toml",
                "parser_version": RULES,
                "rule": "declarative-config-v1",
                "qualification": "declared_only",
                "syntax": Syntax(
                    category=kind,
                    qualified_name=".".join(item["property_path"]),
                    candidate_category=item.get("category"),
                ).model_dump(),
            }
        )
    for symbol in symbols:
        symbol.setdefault(
            "syntax", Syntax(category=symbol["kind"], qualified_name=symbol["name"]).model_dump()
        )
    return sorted({s["id"]: s for s in symbols}.values(), key=lambda s: s["id"])

"""Documentation mentions are qualified assertions, never implementation proof."""

import re
from pathlib import Path
from typing import Any

from repovox.analysis.common import RULES, digest, stable
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
                "id": stable("config", path, kind, name, digest(body)),
                "path": path,
                "start_line": 1,
                "end_line": len(body.rstrip(b"\n").split(b"\n")),
                "start_byte": 0,
                "end_byte": len(body),
                "kind": kind,
                "name": name,
                "file_sha256": digest(body),
                "parser_language": "json" if path.endswith(".json") else "toml",
                "parser_version": RULES,
                "rule": "declarative-config-v1",
                "qualification": "declared_only",
            }
        )
    return sorted({s["id"]: s for s in symbols}.values(), key=lambda s: s["id"])

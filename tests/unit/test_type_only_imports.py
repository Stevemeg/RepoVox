"""A TypeScript `import type {...}` fact must not keep the parser's private marker.

`bindings.annotate` once skipped removing `_type_only` when the import had a `type` keyword,
and the strict 2.3 `Symbol` contract then rejected the Stage 4 payload. Synthetic source only.
"""

from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from repovox.analysis.contracts import PAYLOADS
from repovox.analysis.github import Snapshot
from repovox.analysis.parser import parse_file
from repovox.analysis.sandbox import execute

TYPES = b'import type { Harvest } from "./types";\nimport { type Crate, weigh } from "./scale";\n'
TYPES += b"export function total(h: Harvest, c: Crate): number { return weigh(h, c); }\n"


def test_type_only_imports_carry_no_private_marker() -> None:
    symbols, errors = parse_file("web/total.ts", TYPES, "typescript")
    assert errors == []
    imports = {(s["name"], s["imported_name"]): s for s in symbols if s["kind"] == "import"}
    assert set(imports) == {("./types", "Harvest"), ("./scale", "Crate"), ("./scale", "weigh")}
    assert not [key for s in symbols for key in s if key.startswith("_")]
    assert imports[("./types", "Harvest")]["syntax"]["type_only"] is True
    assert imports[("./scale", "Crate")]["syntax"]["type_only"] is True
    assert imports[("./scale", "weigh")]["syntax"]["type_only"] is False


def test_a_type_only_import_passes_every_stage_contract(tmp_path: Path) -> None:
    files = {
        "web/total.ts": TYPES,
        "web/types.ts": b"export interface Harvest { kg: number }\n",
        "web/scale.ts": b"export type Crate = { kg: number };\n"
        b"export function weigh(h: { kg: number }, c: Crate): number { return h.kg + c.kg; }\n",
    }
    for name, body in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(body)
    request: dict[str, Any] = {
        "snapshot": Snapshot(
            "example/types",
            "https://github.com/example/types",
            1,
            "example",
            "types",
            True,
            "main",
            "a" * 40,
            "2026-11-20T00:00:00Z",
        ).data(),
        "snapshot_id": "11111111-1111-4111-8111-111111111111",
        "archive_hash": "b" * 64,
        "inputs": {},
    }
    stages = {3: "filter", 4: "structure", 5: "entrypoints", 6: "infer"}
    stages |= {7: "knowledge", 8: "evidence", 9: "verify"}
    for ordinal, kind in stages.items():
        payload = execute(ordinal, tmp_path, request)
        TypeAdapter(PAYLOADS[kind]).validate_python(payload)
        request["inputs"][str(ordinal)] = payload

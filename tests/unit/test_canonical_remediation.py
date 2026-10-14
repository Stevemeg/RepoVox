"""Independently specified engineering fixtures; never official or pilot gold.

Names and examples below come from language constructs, not private reference labels.
Expected ranges are literal original lines; SHA checks bind every result to fixture bytes.
"""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from repovox.analysis.common import AnalysisError, digest
from repovox.analysis.configuration import properties
from repovox.analysis.contracts import Knowledge, validate_envelope
from repovox.analysis.facts import CanonicalFact, identity, semantic_symbol, validate_source
from repovox.analysis.graph import infer
from repovox.analysis.grounding import verify
from repovox.analysis.parser import parse_file
from test_analysis import SHA, SNAPSHOT_ID, analyze, snapshot


def test_binding_analysis_time_budget(monkeypatch) -> None:
    from repovox.analysis import bindings

    ticks = iter([0.0, 3.0])
    monkeypatch.setattr(bindings, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(AnalysisError, match="parser_resource_limit"):
        parse_file("bounded.py", b"def task():\n    pass\n", "python")


def test_fact_limit_applies_before_binding_expansion(monkeypatch) -> None:
    from repovox.analysis import parser

    monkeypatch.setattr(parser, "DEFAULT_LIMITS", replace(parser.DEFAULT_LIMITS, facts=2))
    with pytest.raises(AnalysisError, match="analysis_fact_limit"):
        parse_file("bounded.js", b"function work() {}\nfunction run() { work(); }\n", "javascript")


def parsed(files: dict[str, bytes]) -> list[dict]:
    symbols = []
    for path, body in files.items():
        lang = (
            "python"
            if path.endswith(".py")
            else "typescript"
            if path.endswith(".ts")
            else "javascript"
        )
        found, errors = parse_file(path, body, lang)
        assert not errors
        for symbol in found:
            assert symbol["file_sha256"] == digest(body)
            start, end = symbol["start_byte"], symbol["end_byte"]
            assert body[:start].count(b"\n") + 1 == symbol["start_line"]
            assert body[: max(start, end - 1)].count(b"\n") + 1 == symbol["end_line"]
        symbols.extend(found)
    return symbols


def relationships(files: dict[str, bytes]) -> tuple[list[dict], list[dict]]:
    symbols = parsed(files)
    edges = infer({"symbols": symbols}, {"candidates": []})["edges"]
    return symbols, [e for e in edges if e["rule"] == "qualified-binding-v2"]


def test_import_identity_and_multiline_range() -> None:
    body = b"from .engine import (\n    Vessel as Boat,\n    sail,\n)\n"
    symbols = parsed({"harbor/__init__.py": body})
    imports = [semantic_symbol(s) for s in symbols if s["kind"] == "import"]
    boat = next(s for s in imports if s.local_binding == "Boat")
    assert (boat.category, boat.source_name, boat.qualified_name) == (
        "import_member",
        "Vessel",
        ".engine.Vessel",
    )
    assert (boat.import_module, boat.imported_member, boat.alias) == (".engine", "Vessel", "Boat")
    assert (boat.start_line, boat.end_line, boat.start_byte, boat.end_byte) == (
        1,
        4,
        0,
        len(body) - 1,
    )
    assert len({json.dumps(s.model_dump(), sort_keys=True) for s in imports}) == 2
    extracted = next(s for s in symbols if s.get("alias") == "Boat")
    alternate_display = deepcopy(extracted)
    alternate_display["name"] = ".engine.Vessel"
    alternate_display["rule"] = "another-parser-import-rule"
    # Explicit parsed module/member/binding fields, not the display label, define identity.
    assert semantic_symbol(alternate_display) == semantic_symbol(extracted)


def test_inheritance_and_imported_member_binding() -> None:
    symbols, edges = relationships(
        {
            "base.py": b"class Vehicle:\n    pass\n",
            "fleet.py": (
                b"from base import Vehicle as Carrier\nclass Ship(Carrier):\n   "
                b" pass\nclass Ferry(Ship):\n    pass\n"
            ),
        }
    )
    names = {s["id"]: s["name"] for s in symbols}
    assert {(names[e["source"]], names[e["target"]], e["relationship"]) for e in edges} == {
        ("base", "Vehicle", "imports_symbol"),
        ("Ship", "Vehicle", "inherits"),
        ("Ferry", "Ship", "inherits"),
    }
    bases = [s for s in symbols if s["kind"] == "base_reference"]
    assert {(s["name"], s["start_line"], s["end_line"]) for s in bases} == {
        ("Carrier", 2, 2),
        ("Ship", 4, 4),
    }
    assert all(
        e["classification"] == "resolved_static" and len(e["support_ids"]) >= 2 for e in edges
    )


@pytest.mark.parametrize(
    "lang,path,body",
    [
        ("python", "station.py", b"def polish():\n    pass\ndef dock():\n    polish()\n"),
        (
            "javascript",
            "station.js",
            (
                b"function polish() {}\nexport function dock() {\n  const launch"
                b" = () => polish();\n  launch();\n}\n"
            ),
        ),
        (
            "typescript",
            "station.ts",
            (
                b"function polish(): void {}\nexport function dock() {\n  const "
                b"launch = () => polish();\n  launch();\n}\n"
            ),
        ),
    ],
)
def test_lexical_calls(lang: str, path: str, body: bytes) -> None:
    symbols, edges = relationships({path: body})
    names = {s["id"]: s["name"] for s in symbols}
    pairs = {
        (names[e["source"]], names[e["target"]])
        for e in edges
        if e["relationship"] == "calls_lexically"
    }
    assert pairs == (
        {("dock", "polish")} if lang == "python" else {("launch", "polish"), ("dock", "launch")}
    )


@pytest.mark.parametrize(
    "body",
    [
        b"function task() {}\nfunction run(task) { task(); }\n",
        b"function task() {}\nfunction run() { task(); }\ntask = other;\n",
        b"function task() {}\nfunction run() { let task = other; task(); }\n",
        b"function task() {}\nfunction run() { obj.task(); }\n",
        b"if (enabled) { function task() {} }\nfunction run() { task(); }\n",
        b"import {task} from 'external';\nfunction run() { task(); }\n",
        b"function task() {}\nfunction run() { eval('unknown'); task(); }\n",
        b"function task() {}\nfunction run({task}) { task(); }\n",
        b"function task() {}\nfunction run() { {var task = other;} task(); }\n",
        (b"function task() {}\nfunction change() { task = other; }\nfunction run() { task(); }\n"),
    ],
)
def test_javascript_ambiguity_is_not_resolved(body: bytes) -> None:
    _, edges = relationships({"unknown.js": body})
    assert not edges


@pytest.mark.parametrize(
    "body",
    [
        b"def task():\n    pass\ndef run(task):\n    task()\n",
        b"def task():\n    pass\ndef run():\n    task()\ntask = other\n",
        b"if enabled:\n    def task():\n        pass\ndef run():\n    task()\n",
        b"from external import Vessel\nclass Boat(Vessel):\n    pass\n",
        b"class Boat(factory()):\n    pass\n",
        b"class Boat(Boat):\n    pass\n",
        b"class Boat(Ship):\n    pass\nclass Ship:\n    pass\n",
        b"def task():\n    pass\ndef run():\n    return (lambda task: task())(other)\n",
        b"@wrapper\ndef task():\n    pass\ndef run():\n    task()\n",
        (
            b"def task():\n    pass\ndef change():\n    global task\n    task "
            b"= other\ndef run():\n    task()\n"
        ),
    ],
)
def test_python_ambiguity_is_not_resolved(body: bytes) -> None:
    _, edges = relationships({"unknown.py": body})
    assert not edges


def test_typescript_constructor_binding_and_type_only_exclusion() -> None:
    sources = {
        "engine.ts": b"export class Motor {}\n",
        "use.ts": (
            b"import {Motor as Drive} from './engine';\nexport function bui"
            b"ld() {\n  return new Drive({});\n}\n"
        ),
    }
    symbols, edges = relationships(sources)
    assert {e["relationship"] for e in edges} == {"imports_symbol", "instantiates"}
    construct = next(s for s in symbols if s["kind"] == "call")
    assert (
        construct["syntax"]["constructor"] and construct["start_line"] == construct["end_line"] == 3
    )
    for replacement in [b"import type {Motor as Drive}", b"import {type Motor as Drive}"]:
        changed = sources | {
            "use.ts": sources["use.ts"].replace(b"import {Motor as Drive}", replacement)
        }
        assert not relationships(changed)[1]


@pytest.mark.parametrize(
    "files",
    [
        {
            "a.py": b"from b import Bee\nclass Aye:\n    pass\n",
            "b.py": b"from a import Aye\nclass Bee:\n    pass\n",
        },
        {
            "x.js": b"import {ship} from './boat';\nfunction sail() { ship(); }\n",
            "boat.js": b"export function ship() {}\n",
            "boat.ts": b"export function ship() {}\n",
        },
        {
            "x.js": b"import {ship} from './boat';\nfunction sail() { ship(); }\n",
            "boat.js": b"function ship() {}\n",
        },
    ],
)
def test_cycles_ambiguous_modules_and_private_exports(files: dict[str, bytes]) -> None:
    assert not relationships(files)[1]


def test_configuration_ranges_and_candidate_categories(tmp_path: Path) -> None:
    files = {
        "main.py": b"def start():\n    pass\n",
        "package.json": (
            b'{\n  "main": "missing.js",\n  "types": "missing.d.ts",\n  "expo'
            b'rts": {".": {\n    "import": "./main.js",\n    "types": "./mai'
            b'n.d.ts"\n  }},\n  "bin": {"tool": "./cli.js"}\n}\n'
        ),
        "pyproject.toml": (
            b'# leading comment\n[build-system]\nbuild-backend = "forge.buil'
            b'd" # backend\n[project.scripts]\nlaunch = "main:start"\n'
        ),
        "main.js": b"export default function start() {}\n",
    }
    request, result = analyze(tmp_path, files)
    config = request["inputs"]["4"]["configuration"]
    assert not config["config_errors"]
    entries = {tuple(e["property_path"]): e for e in config["config_entries"]}
    expected = {
        ("main",): (2, 2, "library_export"),
        ("types",): (3, 3, "type_declaration"),
        ("exports", ".", "import"): (5, 5, "library_export"),
        ("exports", ".", "types"): (6, 6, "type_declaration"),
        ("bin", "tool"): (8, 8, "candidate_command"),
        ("build-system", "build-backend"): (3, 3, "build_system"),
        ("project", "scripts", "launch"): (5, 5, "candidate_command"),
    }
    assert {
        key: (e["start_line"], e["end_line"], e["category"]) for key, e in entries.items()
    } == expected
    assert result["knowledge"]["entrypoints"]["selected"] is None
    assert all(e["validation_status"] == "valid" for e in result["evidence"]["items"])


@pytest.mark.parametrize(
    "body,json_format,key,expected",
    [
        (
            b'{\n "exports": {".": [\n "./one.js",\n "./two.js"\n ]}\n}',
            True,
            ("exports", ".", "1"),
            b'"./two.js"',
        ),
        (
            b'[project]\ndependencies = [\n "one>=1", # comment\n "two"\n]\n',
            False,
            ("project", "dependencies", "1"),
            b'dependencies = [\n "one>=1", # comment\n "two"\n]',
        ),
        (
            b'build-system.build-backend = "forge.build"\n',
            False,
            ("build-system", "build-backend"),
            b'build-system.build-backend = "forge.build"',
        ),
    ],
)
def test_multiline_and_nested_configuration(
    body: bytes, json_format: bool, key: tuple, expected: bytes
) -> None:
    _, ranges = properties(body, json_format)
    start, end = ranges[key]
    assert body[start:end] == expected


@pytest.mark.parametrize(
    "body,json_format", [(b'{"main":"a", "main":"b"}', True), (b'main="a"\nmain="b"', False)]
)
def test_duplicate_configuration_keys_rejected(body: bytes, json_format: bool) -> None:
    with pytest.raises(ValueError):
        properties(body, json_format)


def test_packaging_cli_and_plugin_candidates(tmp_path: Path) -> None:
    _, result = analyze(
        tmp_path,
        {
            "package.py": (
                b"import click as cli\nfrom setuptools import setup as configur"
                b"e\n@cli.command()\ndef launch():\n    pass\ndef _jupyter_labexte"
                b"nsion_paths():\n    return []\nconfigure()\n"
            ),
            "plugin.ts": (
                b"const extension = {id: 'fixture:extension', activate: () => "
                b"{}};\nexport default extension;\n"
            ),
            "plain.js": b"export function utility() {}\n",
        },
    )
    candidates = result["knowledge"]["entrypoints"]["candidates"]
    assert {(c["path"], c["category"]) for c in candidates} == {
        ("package.py", "candidate_command"),
        ("package.py", "packaging_hook"),
        ("plugin.ts", "plugin"),
    }
    assert result["knowledge"]["entrypoints"]["selected"] is None


def test_fake_cli_and_plugin_names_are_not_wiring(tmp_path: Path) -> None:
    _, result = analyze(
        tmp_path,
        {
            "fake.py": b"class click:\n    pass\n@click.command()\ndef run():\n    pass\n",
            "fake.ts": b"export default {id: 'only-a-label'};\n",
        },
    )
    assert [c["category"] for c in result["knowledge"]["entrypoints"]["candidates"]] == [
        "library_export"
    ]


def test_identity_provenance_equivalence_and_meaningful_differences(tmp_path: Path) -> None:
    _, result = analyze(tmp_path, {"port.py": b"from .parts import Wheel as Rim\n"})
    raw = next(
        f
        for f in result["knowledge"]["canonical_facts"]
        if f["category"] == "syntax" and f["subject"]["category"] == "import_member"
    )
    fact = CanonicalFact.model_validate(raw)
    validate_source(fact, tmp_path, "example/demo", SHA)
    alternate = deepcopy(raw)
    alternate["parser_rules"] = ["independent-syntax-extractor"]
    assert identity(fact) == identity(CanonicalFact.model_validate(alternate))
    for field, value in [
        ("repository", "other/project"),
        ("commit_sha", "b" * 40),
        ("classification", "unresolved"),
    ]:
        changed = deepcopy(raw)
        changed[field] = value
        assert identity(fact) != identity(CanonicalFact.model_validate(changed))
    for member, binding in [("Axle", "Rim"), ("Wheel", "Other")]:
        changed = deepcopy(raw)
        changed["subject"].update(
            imported_member=member,
            source_name=member,
            qualified_name=".parts." + member,
            local_binding=binding,
            alias=binding,
        )
        assert identity(fact) != identity(CanonicalFact.model_validate(changed))
    (tmp_path / "port.py").write_bytes(b"# different bytes\n")
    with pytest.raises(ValueError, match="source_invalid"):
        validate_source(fact, tmp_path, "example/demo", SHA)


def test_canonical_forgery_and_range_rejection(tmp_path: Path) -> None:
    request, result = analyze(tmp_path)
    original = deepcopy(result)
    duplicate = deepcopy(original["knowledge"])
    duplicate["canonical_facts"].append(duplicate["canonical_facts"][0])
    with pytest.raises(ValidationError, match="duplicate_canonical_fact"):
        Knowledge.model_validate(duplicate)
    result["knowledge"]["canonical_facts"][0]["classification"] = "resolved_static"
    with pytest.raises(AnalysisError, match="insufficient_evidence"):
        verify(
            tmp_path,
            snapshot(),
            SNAPSHOT_ID,
            request["inputs"]["3"],
            result["knowledge"],
            result["evidence"],
        )
    fact = CanonicalFact.model_validate(original["knowledge"]["canonical_facts"][0])
    with pytest.raises(ValueError, match="snapshot_mismatch"):
        validate_source(fact, tmp_path, "wrong/project", SHA)
    invalid = fact.model_dump()
    invalid["subject"]["end_byte"] = 99999
    with pytest.raises(ValueError, match="byte_range_invalid"):
        validate_source(CanonicalFact.model_validate(invalid), tmp_path, "example/demo", SHA)
    invalid["subject"]["end_line"] = 99999
    with pytest.raises(ValidationError, match="endpoint_missing_support"):
        CanonicalFact.model_validate(invalid)


def test_legacy_envelope_still_valid_and_not_silently_upgraded() -> None:
    old = {
        "schema_version": "2.2",
        "kind": "structure",
        "owner_id": SNAPSHOT_ID,
        "snapshot_id": SNAPSHOT_ID,
        "commit_sha": SHA,
        "pipeline_version": "phase2-static-v1",
        "input_digest": "a" * 64,
        "generation_metadata": None,
        "payload": {},
    }
    # A tiny fully typed legacy entrypoint packet is sufficient to test dispatch.
    old["kind"] = "entrypoints"
    old["payload"] = {
        "candidates": [
            {
                "symbol_id": "symbol-one",
                "path": "old.py",
                "rule": "python-main-v1",
                "support_ids": ["symbol-one"],
                "rank": 100,
            }
        ],
        "selected": "symbol-one",
        "frameworks": [],
        "scope": "synthetic",
        "uncertainty": [],
    }
    validate_envelope(old)
    old["schema_version"] = "2.3"
    with pytest.raises(ValidationError):
        validate_envelope(old)

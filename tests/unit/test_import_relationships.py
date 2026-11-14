"""Regression tests for relationship edges that canonical facts cannot tell apart.

Root cause covered here: one edge was emitted per supporting symbol, but a canonical
relationship fact is identified by endpoints plus line-level anchors. Two members of a single
`from models import Discriminator, Generator` therefore produced two byte-identical facts and
the accepted contract rejected the repository with duplicate_canonical_fact.
"""

import shutil
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from repovox.analysis import graph
from repovox.analysis.common import AnalysisError, stable
from repovox.analysis.contracts import PAYLOADS
from repovox.analysis.facts import CanonicalFact, identity, validate_collection
from repovox.analysis.github import Snapshot
from repovox.analysis.grounding import verify
from repovox.analysis.sandbox import execute

FIXTURE = Path(__file__).parents[1] / "fixtures" / "analysis" / "member_imports"
MODELS = (FIXTURE / "models.py").read_bytes()
SNAPSHOT_ID = "11111111-1111-4111-8111-111111111111"


def snapshot() -> dict[str, Any]:
    return Snapshot(
        "example/demo",
        "https://github.com/example/demo",
        1,
        "example",
        "demo",
        True,
        "main",
        "a" * 40,
        "2026-11-14T00:00:00Z",
    ).data()


def analyze(root: Path, files: dict[str, bytes] | None = None) -> tuple[dict[str, Any], dict]:
    """Run the real Stage 3-9 functions; returns the request (all stage outputs) and payload."""
    for name, body in (files or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    request: dict[str, Any] = {
        "snapshot": snapshot(),
        "snapshot_id": SNAPSHOT_ID,
        "archive_hash": "b" * 64,
        "inputs": {},
    }
    payload: dict[str, Any] = {}
    for stage, kind in [
        (3, "filter"),
        (4, "structure"),
        (5, "entrypoints"),
        (6, "infer"),
        (7, "knowledge"),
        (8, "evidence"),
        (9, "verify"),
    ]:
        payload = execute(stage, root, request)
        TypeAdapter(PAYLOADS[kind]).validate_python(payload)
        request["inputs"][str(stage)] = payload
    return request, payload


def copied(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    shutil.copytree(FIXTURE, root)
    return root


def symbols(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in payload["knowledge"]["symbols"]}


def edges(payload: dict[str, Any], relationship: str, path: str) -> list[dict[str, Any]]:
    index = symbols(payload)
    return [
        e
        for e in payload["knowledge"]["edges"]
        if e["relationship"] == relationship
        and e["classification"] == "resolved_static"
        and index[e["source"]]["path"] == path
    ]


def imports(payload: dict[str, Any], path: str) -> list[dict[str, Any]]:
    found = [
        s for s in payload["knowledge"]["symbols"] if s["kind"] == "import" and s["path"] == path
    ]
    return sorted(found, key=lambda s: s["syntax"]["imported_member"] or "")


def assert_evidence_complete(payload: dict[str, Any]) -> None:
    facts = [CanonicalFact.model_validate(f) for f in payload["knowledge"]["canonical_facts"]]
    validate_collection(facts)
    index = symbols(payload)
    syntax = [f for f in facts if f.category == "syntax"]
    assert len(syntax) == len(index)  # Every parsed symbol still has its own fact.
    assert len(
        {
            (
                f.subject.path,
                f.subject.start_byte,
                f.subject.end_byte,
                f.subject.category,
                f.subject.qualified_name,
            )
            for f in syntax
        }
    ) == len(syntax)
    verdicts = {v["claim_id"]: v for v in payload["verification"]["verdicts"]}
    valid = {e["id"] for e in payload["evidence"]["items"] if e["validation_status"] == "valid"}
    for claim in payload["knowledge"]["claims"]:
        assert verdicts[claim["id"]]["status"] in {"verified", "inferred"}
        assert claim["evidence_ids"] and set(claim["evidence_ids"]) <= valid
    assert payload["verification"]["counts"]["unsupported"] == 0


def unmerged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore the pre-correction behavior to prove what changed and what did not."""
    monkeypatch.setattr(graph, "merge_indistinguishable", lambda indexed, found: found)


def test_reported_failure_reproduces_without_the_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert b"from models import Discriminator, Generator\n" in (FIXTURE / "train.py").read_bytes()
    unmerged(monkeypatch)
    with pytest.raises(ValidationError, match="duplicate_canonical_fact"):
        analyze(copied(tmp_path))


def test_multiple_imported_members_keep_distinct_identities(tmp_path: Path) -> None:
    request, payload = analyze(copied(tmp_path))
    assert_evidence_complete(payload)
    members = imports(payload, "train.py")
    assert [m["syntax"]["imported_member"] for m in members] == ["Discriminator", "Generator"]
    qualified = {
        f["subject"]["qualified_name"]
        for f in payload["knowledge"]["canonical_facts"]
        if f["category"] == "syntax"
        and f["subject"]["category"] == "import_member"
        and f["subject"]["path"] == "train.py"
    }
    assert qualified == {"models.Discriminator", "models.Generator"}
    # The accepted parser anchors every member at its whole import statement; the members
    # are told apart by imported-member identity, and each keeps its own symbol and fact.
    source = (FIXTURE / "train.py").read_bytes()
    assert len({m["id"] for m in members}) == 2
    for member in members:
        assert source[member["start_byte"] : member["end_byte"]] == (
            b"from models import Discriminator, Generator"
        )
        assert (member["start_line"], member["end_line"]) == (1, 1)
    index = symbols(payload)
    # One module-to-module relationship, supported by both member symbols.
    module = edges(payload, "imports", "train.py")
    assert len(module) == 1 and index[module[0]["target"]]["path"] == "models.py"
    assert module[0]["support_ids"] == sorted(m["id"] for m in members)
    # Each member still resolves to its own class, with its own anchor.
    resolved = {
        index[e["source"]]["syntax"]["imported_member"]: index[e["target"]]
        for e in edges(payload, "imports_symbol", "train.py")
    }
    assert {k: (v["kind"], v["name"]) for k, v in resolved.items()} == {
        "Discriminator": ("class", "Discriminator"),
        "Generator": ("class", "Generator"),
    }
    claim = next(c for c in payload["knowledge"]["claims"] if c["subject_id"] == module[0]["id"])
    evidence = {
        e["symbol_id"] for e in payload["evidence"]["items"] if e["id"] in claim["evidence_ids"]
    }
    assert evidence == {m["id"] for m in members}


def test_merged_edge_loses_no_support(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request, payload = analyze(copied(tmp_path))
    merged = request["inputs"]["6"]["edges"]
    unmerged(monkeypatch)
    structural, entries = request["inputs"]["4"]["structure"], request["inputs"]["5"]
    before = graph.infer(structural, entries)["edges"]
    assert len(before) > len(merged)

    def shape(edge: dict[str, Any]) -> tuple[str, str, str, str]:
        return edge["source"], edge["target"], edge["relationship"], edge["classification"]

    support_before: dict[tuple[str, str, str, str], set[str]] = {}
    for edge in before:
        support_before.setdefault(shape(edge), set()).update(edge["support_ids"])
    support_after: dict[tuple[str, str, str, str], set[str]] = {}
    for edge in merged:
        support_after.setdefault(shape(edge), set()).update(edge["support_ids"])
    assert support_after == support_before
    untouched = {e["id"]: e for e in before} | {}
    assert all(e == untouched[e["id"]] for e in merged if e["id"] in untouched)
    changed = [e for e in merged if e["id"] not in untouched]
    assert {e["relationship"] for e in changed} == {"imports", "calls_lexically"}
    assert all(len(e["support_ids"]) >= 2 for e in changed)


def test_import_aliases_on_one_line(tmp_path: Path) -> None:
    files = {
        "models.py": MODELS,
        "use.py": (
            b"from models import Discriminator as Critic, Generator as Maker\n\n\n"
            b"def build():\n    return Maker(), Critic()\n"
        ),
    }
    _, payload = analyze(tmp_path, files)
    assert_evidence_complete(payload)
    members = imports(payload, "use.py")
    assert [(m["syntax"]["imported_member"], m["syntax"]["local_binding"]) for m in members] == [
        ("Discriminator", "Critic"),
        ("Generator", "Maker"),
    ]
    facts = [
        f
        for f in payload["knowledge"]["canonical_facts"]
        if f["category"] == "syntax" and f["subject"]["category"] == "import_member"
    ]
    assert {(f["subject"]["qualified_name"], f["subject"]["alias"]) for f in facts} == {
        ("models.Discriminator", "Critic"),
        ("models.Generator", "Maker"),
    }
    index = symbols(payload)
    assert len(edges(payload, "imports", "use.py")) == 1
    targets = {index[e["target"]]["name"] for e in edges(payload, "imports_symbol", "use.py")}
    assert targets == {"Generator", "Discriminator"}
    # Accepted, unchanged limit: calls through an alias are not resolved to the class.
    assert edges(payload, "instantiates", "use.py") == []


def test_relative_imports_of_several_members(tmp_path: Path) -> None:
    _, payload = analyze(copied(tmp_path))
    assert_evidence_complete(payload)
    members = imports(payload, "pkg/build.py")
    assert [m["syntax"]["imported_member"] for m in members] == ["Block", "Head"]
    assert {m["syntax"]["import_module"] for m in members} == {".layers"}
    index = symbols(payload)
    module = edges(payload, "imports", "pkg/build.py")
    assert len(module) == 1 and index[module[0]["target"]]["path"] == "pkg/layers.py"
    targets = {index[e["target"]]["name"] for e in edges(payload, "imports_symbol", "pkg/build.py")}
    assert targets == {"Block", "Head"}


def test_duplicate_lexical_bindings_and_repeated_calls(tmp_path: Path) -> None:
    files = {
        "models.py": MODELS,
        "twice.py": (
            b"from models import helper\nfrom models import helper\n\n\n"
            b"def run(value):\n    return helper(value) + helper(value)\n"
        ),
    }
    _, payload = analyze(tmp_path / "rebound", files)
    assert_evidence_complete(payload)
    members = imports(payload, "twice.py")
    assert len(members) == 2 and {m["start_line"] for m in members} == {1, 2}
    assert all(m["syntax"]["unsafe_binding"] for m in members)
    calls = [
        s
        for s in payload["knowledge"]["symbols"]
        if s["kind"] == "call" and s["path"] == "twice.py" and s["name"] == "helper"
    ]
    assert len(calls) == 2 and len({c["start_byte"] for c in calls}) == 2
    # A name bound twice is ambiguous: no resolved call or member binding is claimed.
    assert edges(payload, "calls_lexically", "twice.py") == []
    assert edges(payload, "imports_symbol", "twice.py") == []
    assert len(edges(payload, "imports", "twice.py")) == 2  # Two statements, two relationships.

    _, fixture_payload = analyze(copied(tmp_path / "fixture"))
    assert_evidence_complete(fixture_payload)
    repeated = edges(fixture_payload, "calls_lexically", "calls.py")
    assert len(repeated) == 1
    index = symbols(fixture_payload)
    sites = [i for i in repeated[0]["support_ids"] if index[i]["kind"] == "call"]
    assert len(sites) == 2  # Both call sites remain as support of the one relationship.
    assert len({index[i]["start_byte"] for i in sites}) == 2


def test_exactly_repeated_member_is_still_detected_not_suppressed(tmp_path: Path) -> None:
    """Known remaining limit, deliberately not masked.

    `from models import helper, helper` makes the accepted parser emit the same symbol twice
    (one statement-level anchor, one member identity). That is a genuine identity collision,
    so duplicate detection must keep rejecting it. Resolving it needs member-level anchors in
    the parser, which would change accepted symbol identities and is outside this correction.
    """
    files = {"models.py": MODELS, "same.py": b"from models import helper, helper\n"}
    with pytest.raises(ValidationError, match="duplicate_canonical_fact"):
        analyze(tmp_path, files)


def test_conflicting_imports_are_not_resolved(tmp_path: Path) -> None:
    files = {
        "models.py": MODELS,
        "other.py": b"class Generator:\n    pass\n",
        "clash.py": (
            b"from models import Generator\nfrom other import Generator\n\n\n"
            b"def build():\n    return Generator()\n"
        ),
    }
    _, payload = analyze(tmp_path, files)
    assert_evidence_complete(payload)
    index = symbols(payload)
    module_targets = sorted(
        index[e["target"]]["path"] for e in edges(payload, "imports", "clash.py")
    )
    assert module_targets == ["models.py", "other.py"]  # Two real, distinct relationships.
    assert edges(payload, "instantiates", "clash.py") == []  # Ambiguous name: no binding claimed.


def test_typescript_named_imports_on_one_line(tmp_path: Path) -> None:
    files = {
        "lib.ts": (
            b"export function left(x: string) { return x; }\n"
            b"export function right(x: string) { return x; }\n"
        ),
        "main.ts": (
            b'import { left, right } from "./lib";\n'
            b"export function run(x: string) { return left(x) + right(x); }\n"
        ),
    }
    _, payload = analyze(tmp_path, files)
    assert_evidence_complete(payload)
    assert len(edges(payload, "imports", "main.ts")) == 1
    index = symbols(payload)
    targets = {index[e["target"]]["name"] for e in edges(payload, "imports_symbol", "main.ts")}
    assert targets == {"left", "right"}


def test_real_identity_collisions_are_still_rejected(tmp_path: Path) -> None:
    _, payload = analyze(copied(tmp_path))
    facts = [CanonicalFact.model_validate(f) for f in payload["knowledge"]["canonical_facts"]]
    assert max(Counter(identity(f) for f in facts).values()) == 1
    with pytest.raises(ValueError, match="duplicate_canonical_fact"):
        validate_collection([*facts, facts[0]])
    relationship = next(f for f in facts if f.category == "relationship")
    with pytest.raises(ValueError, match="duplicate_canonical_fact"):
        validate_collection(
            [*facts, relationship.model_copy(update={"parser_rules": ["other-rule"]})]
        )
    duplicated = deepcopy(payload)
    duplicated["knowledge"]["canonical_facts"].append(duplicated["knowledge"]["canonical_facts"][0])
    with pytest.raises(ValidationError, match="duplicate_canonical_fact"):
        TypeAdapter(PAYLOADS["verify"]).validate_python(duplicated)


def test_verifier_rejects_a_forged_or_split_merged_edge(tmp_path: Path) -> None:
    root = copied(tmp_path)
    request, payload = analyze(root)
    index = symbols(payload)
    position = next(
        i
        for i, e in enumerate(payload["knowledge"]["edges"])
        if e["relationship"] == "imports"
        and e["classification"] == "resolved_static"
        and index[e["source"]]["path"] == "train.py"
    )
    for change in ("drop_support", "retarget"):
        forged = deepcopy(request["inputs"]["8"])
        edge = forged["knowledge"]["edges"][position]
        if change == "drop_support":
            edge["support_ids"] = edge["support_ids"][:1]
        else:
            edge["target"] = next(
                s["id"]
                for s in index.values()
                if s["path"] == "pkg/layers.py" and s["kind"] == "module"
            )
        with pytest.raises(AnalysisError, match="insufficient_evidence"):
            verify(
                root,
                request["snapshot"],
                SNAPSHOT_ID,
                request["inputs"]["4"]["manifest"],
                forged["knowledge"],
                forged["evidence"],
            )


@pytest.mark.parametrize(
    "files",
    [
        {
            "models.py": MODELS,
            "one.py": b"from models import Generator\n\n\ndef make():\n    return Generator()\n",
        },
        {
            "models.py": MODELS,
            "two.py": (
                b"from models import Generator\nfrom models import Discriminator\n\n\n"
                b"def make():\n    return Generator(), Discriminator()\n"
            ),
        },
        {
            "models.py": MODELS,
            "whole.py": b"import models\n\n\ndef make():\n    return models.Generator()\n",
        },
        {"main.py": b'def main(x):\n    return x\nif __name__ == "__main__":\n    main(1)\n'},
        {
            "app.py": (
                b'from fastapi import FastAPI\napp=FastAPI()\n@app.get("/hello")'
                b'\ndef hello():\n    return "hello"\n'
            ),
            "client.ts": b"export function client(x: string) { return x; }\n",
        },
    ],
)
def test_existing_accepted_facts_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, bytes]
) -> None:
    request, payload = analyze(tmp_path / "after", files)
    unmerged(monkeypatch)
    before_request, before = analyze(tmp_path / "before", files)
    assert request["inputs"]["6"]["edges"] == before_request["inputs"]["6"]["edges"]
    assert payload["knowledge"]["canonical_facts"] == before["knowledge"]["canonical_facts"]
    assert payload["knowledge"]["claims"] == before["knowledge"]["claims"]
    assert payload["verification"]["counts"] == before["verification"]["counts"]
    index = symbols(payload)
    for edge in payload["knowledge"]["edges"]:
        if edge["rule"] == "graph-syntax-v1":  # The accepted identifier formula still holds.
            assert len(edge["support_ids"]) == 1
            module = next(
                s["id"]
                for s in index.values()
                if s["kind"] == "module" and s["path"] == index[edge["support_ids"][0]]["path"]
            )
            assert edge["id"] == stable(
                "edge", module, edge["target"], edge["relationship"], edge["support_ids"][0]
            )

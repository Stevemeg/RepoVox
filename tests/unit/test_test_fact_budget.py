"""Deterministic test-file fact budget under the unchanged 10,000-fact cap (ADR-0030).

Every repository here is locally authored synthetic source, analysed by the real Stage 3-9
pipeline; nothing is executed. The heavy test files are JavaScript: one `total(1, 2);` line is
one call fact, so the real cap is crossed in seconds. Tiers 2 and 3 are exercised with a
smaller cap set on the modules that read it, with the same code path.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter
from repovox.analysis import grounding, sandbox
from repovox.analysis.budget import (
    PARSED,
    PREFIX,
    REASONS,
    FactBudget,
    tiers,
)
from repovox.analysis.common import DEFAULT_LIMITS, AnalysisError, Limits, canonical
from repovox.analysis.contracts import PAYLOADS
from repovox.analysis.documentation import context_symbols
from repovox.analysis.github import Snapshot
from repovox.analysis.parser import parse_file
from repovox.analysis.sandbox import execute
from repovox.media import story_extract
from repovox.media.architecture import discover
from repovox.media.sandbox import sources_from
from repovox.media.story import StoryError, UnresolvedQuestions
from repovox.media.story_board import build_story_board, check_story_board
from repovox.media.story_extract import (
    BUDGET_OPENING,
    TEMPLATES,
    extract_story,
    story_sources,
    verify_story,
)

CAP = DEFAULT_LIMITS.facts
KINDS = {3: "filter", 4: "structure", 5: "entrypoints", 6: "infer"}
KINDS |= {7: "knowledge", 8: "evidence", 9: "verify"}
PRODUCTION = {
    "README.md": b"# Tally\n\nTally adds numbers for a small shop.\n",
    "app/main.py": (
        b"class Base:\n    pass\n\n\n"
        b"def main(x):\n    return x\n\n\n"
        b'if __name__ == "__main__":\n    main(1)\n'
    ),
    "web/total.js": b"export function total(a, b) {\n  return a + b;\n}\n",
}
PYTHON_TEST = (
    b"from app.main import Base, main\n\n\n"
    b"class TestMain(Base):\n"
    b"    def test_main_returns_its_argument(self):\n"
    b"        assert main(1) == 1\n"
)


def heavy(calls: int) -> bytes:
    head = b'import { total } from "../web/total.js";\n\n'
    head += b'test("adds", () => {\n  expect(total(1, 2)).toBe(3);\n});\n'
    return head + b"total(1, 2);\n" * calls


def tree(root: Path, files: dict[str, bytes]) -> Path:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return root


def request() -> dict[str, Any]:
    return {
        "snapshot": Snapshot(
            "example/tally",
            "https://github.com/example/tally",
            1,
            "example",
            "tally",
            True,
            "main",
            "a" * 40,
            "2026-11-20T00:00:00Z",
        ).data(),
        "snapshot_id": "11111111-1111-4111-8111-111111111111",
        "archive_hash": "b" * 64,
        "inputs": {},
    }


def run(root: Path, until: int = 9, given: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stages 3..`until`; each payload is checked against the frozen 2.3 contract."""
    state = given or request()
    for ordinal in range(3, until + 1):
        if str(ordinal) in state["inputs"]:
            continue
        if ordinal == 4:  # Stage 4 updates the manifest in place; keep the Stage 3 original.
            state["stage3"] = deepcopy(state["inputs"]["3"])
        payload = execute(ordinal, root, state)
        TypeAdapter(PAYLOADS[KINDS[ordinal]]).validate_python(payload)
        state["inputs"][str(ordinal)] = payload
    return state


def again(stage3: dict[str, Any]) -> dict[str, Any]:
    """A fresh request that starts from a copy of an earlier Stage 3 manifest."""
    return {**request(), "inputs": {"3": deepcopy(stage3)}}


def unbudgeted(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """The facts Stage 4 emitted before ADR-0030: every parsed fact plus context, by id."""
    found: list[dict[str, Any]] = []
    for file in manifest["files"]:
        if file["status"] == "parsed":
            found += parse_file(file["path"], (root / file["path"]).read_bytes(), file["language"])[
                0
            ]
    return sorted(found + context_symbols(root, manifest), key=lambda s: s["id"])


def paths_of_tests(manifest: dict[str, Any]) -> set[str]:
    return {f["path"] for f in manifest["files"] if f["classification"] == "test"}


def fact(kind: str, ident: str, target: str | None = None) -> dict[str, Any]:
    return {"id": ident, "kind": kind, "syntax": {"lexical_target_id": target}}


# ------------------------------------------------------------------- the rule on its own


def test_tiers_order_calls_then_imports_and_their_dependents_then_the_rest() -> None:
    facts = [
        fact("module", "m"),
        fact("import", "i"),
        fact("call", "c", "i"),
        fact("base_reference", "b", "i"),
        fact("base_reference", "k", "f"),
        fact("function", "f"),
    ]
    assert tiers(facts) == [3, 2, 1, 2, 3, 3]


def test_the_budget_keeps_everything_at_or_under_the_cap() -> None:
    budget = FactBudget(6)
    production = [fact("function", f"p{i}") for i in range(3)]
    tests = [fact("call", "c"), fact("import", "i"), fact("module", "m")]
    budget.add("src/a.py", production, test=False)
    budget.add("tests/test_a.py", tests, test=True)
    assert budget.level() == 0 and budget.omitted() == {}
    assert budget.kept() == production + tests  # arrival order, nothing dropped


def test_each_tier_is_dropped_only_while_the_total_exceeds_the_cap() -> None:
    production = [fact("function", f"p{i}") for i in range(4)]
    tests = [fact("module", "m"), fact("import", "i"), fact("call", "c1"), fact("call", "c2")]
    expected = {
        8: (0, ["m", "i", "c1", "c2"]),
        7: (1, ["m", "i"]),
        6: (1, ["m", "i"]),
        5: (2, ["m"]),
        4: (3, []),
    }
    for limit, (level, kept) in expected.items():
        budget = FactBudget(limit)
        budget.add("src/a.py", production, test=False)
        budget.add("tests/a.test.js", tests, test=True)
        assert budget.level() == level
        assert [f["id"] for f in budget.kept()] == [f["id"] for f in production] + kept
        assert budget.omitted() == ({"tests/a.test.js": REASONS[level]} if level else {})
    with pytest.raises(AnalysisError, match="analysis_fact_limit"):
        budget = FactBudget(3)
        budget.add("src/a.py", production, test=False)


def test_a_dropped_tier_is_released_as_soon_as_it_is_certain() -> None:
    budget = FactBudget(100)
    budget.add("src/a.py", [fact("function", f"p{i}") for i in range(50)], test=False)
    for n in range(40):
        calls = [fact("call", f"t{n}-{i}") for i in range(50)]
        budget.add(f"tests/t{n}.test.js", [fact("module", f"m{n}"), *calls], test=True)
        assert len(budget.held) <= 100 + 51  # never more than the cap plus one file
    assert budget.level() == 1 and len(budget.kept()) == 90


# ------------------------------------------------------- at or under the cap: unchanged


def test_a_repository_at_or_under_the_cap_is_unchanged(tmp_path: Path) -> None:
    root = tree(
        tmp_path, PRODUCTION | {"tests/test_main.py": PYTHON_TEST, "tests/a.test.js": heavy(20)}
    )
    state = run(root)
    parsed = state["inputs"]["4"]
    assert parsed["structure"]["symbols"] == unbudgeted(root, parsed["manifest"])
    assert {f["reason"] for f in parsed["manifest"]["files"] if f["status"] == "parsed"} == {PARSED}
    knowledge = state["inputs"]["9"]["knowledge"]
    assert not [line for line in knowledge["limitations"] if line.startswith(PREFIX)]
    payload = state["inputs"]["9"]
    sources = story_sources(root, payload)
    story = extract_story(payload, sources, discover(payload, sources_from(root, payload)))
    assert not [c for c in story.unresolved_questions.claims if c.text.startswith(BUDGET_OPENING)]


def test_exactly_at_the_cap_nothing_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tree(tmp_path, PRODUCTION | {"tests/a.test.js": heavy(30)})
    base = run(root, until=4)
    total = len(unbudgeted(root, base["inputs"]["4"]["manifest"]))
    capped(monkeypatch, total)
    state = run(root, given=again(base["stage3"]))
    assert len(state["inputs"]["4"]["structure"]["symbols"]) == total
    assert {f["reason"] for f in state["inputs"]["4"]["manifest"]["files"]} >= {PARSED}
    assert not set(REASONS.values()) & {
        f["reason"] for f in state["inputs"]["4"]["manifest"]["files"]
    }


# -------------------------------------------------- over the cap: test calls go first


@pytest.fixture(scope="module")
def heavy_tests(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    files = PRODUCTION | {"tests/test_main.py": PYTHON_TEST}
    files |= {f"tests/t{n}.test.js": heavy(3_000) for n in range(4)}
    root = tree(tmp_path_factory.mktemp("heavy"), files)
    return root, run(root)


def test_test_file_calls_are_dropped_and_every_production_fact_is_kept(
    heavy_tests: tuple[Path, dict[str, Any]],
) -> None:
    root, state = heavy_tests
    parsed = state["inputs"]["4"]
    manifest, symbols = parsed["manifest"], parsed["structure"]["symbols"]
    every = unbudgeted(root, manifest)
    tests = paths_of_tests(manifest)
    assert len(every) > CAP >= len(symbols)
    production = [s for s in every if s["path"] not in tests]
    assert [s for s in symbols if s["path"] not in tests] == production  # 100% kept
    kept_tests = [s for s in symbols if s["path"] in tests]
    assert not [s for s in kept_tests if s["kind"] == "call"]
    assert [s for s in every if s["path"] in tests and s["kind"] != "call"] == kept_tests
    names = {(s["path"], s["kind"], s["name"]) for s in kept_tests}
    assert ("tests/test_main.py", "method", "test_main_returns_its_argument") in names
    assert ("tests/test_main.py", "class", "TestMain") in names
    assert ("tests/t0.test.js", "import", "../web/total.js") in names
    calling = {s["path"] for s in every if s["path"] in tests and s["kind"] == "call"}
    assert calling == tests  # four heavy JavaScript files and the Python test file
    reasons = {f["path"]: f["reason"] for f in manifest["files"] if f["status"] == "parsed"}
    assert reasons == {path: REASONS[1] if path in tests else PARSED for path in reasons}


def test_the_verifier_reproduces_and_discloses_the_budget(
    heavy_tests: tuple[Path, dict[str, Any]],
) -> None:
    _, state = heavy_tests
    verified = state["inputs"]["9"]
    assert verified["verification"]["counts"]["verified"] > 0
    assert [line for line in verified["knowledge"]["limitations"] if line.startswith(PREFIX)] == [
        f"{PREFIX} the repository exceeded the 10,000-fact analysis cap, so call facts from 5 "
        "test files were omitted; their test definitions and imports were kept. The budget "
        "omitted no source-file fact."
    ]


def test_the_budget_is_deterministic(heavy_tests: tuple[Path, dict[str, Any]]) -> None:
    root, state = heavy_tests
    first = execute(4, root, again(state["stage3"]))
    second = execute(4, root, again(state["stage3"]))
    assert canonical(first) == canonical(second) == canonical(state["inputs"]["4"])
    fresh = run(root)  # a fresh Stage 3 too: only its processing timestamp differs
    assert fresh["inputs"]["4"]["structure"] == state["inputs"]["4"]["structure"]
    assert (
        fresh["inputs"]["9"]["knowledge"]["symbols"] == state["inputs"]["9"]["knowledge"]["symbols"]
    )
    assert fresh["inputs"]["9"]["verification"] == state["inputs"]["9"]["verification"]


def test_the_verifier_rejects_a_hidden_or_invented_budget(
    heavy_tests: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    root, state = heavy_tests
    hidden = deepcopy(state)
    knowledge = hidden["inputs"]["8"]["knowledge"]
    knowledge["limitations"] = [
        line for line in knowledge["limitations"] if not line.startswith(PREFIX)
    ]
    with pytest.raises(AnalysisError, match="insufficient_evidence"):
        execute(9, root, hidden)
    relabelled = deepcopy(state)
    for manifest in (
        relabelled["inputs"]["4"]["manifest"],
        relabelled["inputs"]["8"]["knowledge"]["coverage"],
    ):
        manifest["files"][[f["path"] for f in manifest["files"]].index("tests/t0.test.js")][
            "reason"
        ] = PARSED
    with pytest.raises(AnalysisError, match="insufficient_evidence"):
        execute(9, root, relabelled)
    small = tree(tmp_path, PRODUCTION | {"tests/test_main.py": PYTHON_TEST})
    invented = run(small, until=8)
    for manifest in (
        invented["inputs"]["4"]["manifest"],
        invented["inputs"]["8"]["knowledge"]["coverage"],
    ):
        manifest["files"][[f["path"] for f in manifest["files"]].index("tests/test_main.py")][
            "reason"
        ] = REASONS[1]
    with pytest.raises(AnalysisError, match="insufficient_evidence"):
        execute(9, small, invented)


def test_the_story_and_video_plan_state_the_budget(
    heavy_tests: tuple[Path, dict[str, Any]],
) -> None:
    root, state = heavy_tests
    payload = state["inputs"]["9"]
    sources = story_sources(root, payload)
    report = discover(payload, sources_from(root, payload))
    story = extract_story(payload, sources, report)
    statement = TEMPLATES["fact_budget_1"].format(limit="10,000", files="5 test files")
    assert [c.text for c in story.unresolved_questions.claims][:1] == [statement]
    board = build_story_board(payload, story, report)
    check_story_board(board, payload, sources)
    limitations = next(s for s in board.scenes if s.type == "limitations")
    assert statement in [s.text for s in limitations.sentences]
    assert limitations.sentences[-1].text == TEMPLATES["runtime"]
    forged = story.model_copy(
        update={
            "unresolved_questions": UnresolvedQuestions(
                claims=tuple(c for c in story.unresolved_questions.claims if c.text != statement)
            )
        }
    )
    with pytest.raises(StoryError, match="story_budget_mismatch"):
        verify_story(forged, payload, sources, report)


# ------------------------------------------------ production alone over the cap: fails


def test_production_facts_over_the_cap_still_fail_closed(tmp_path: Path) -> None:
    files = PRODUCTION | {"tests/t0.test.js": heavy(10)}
    files |= {f"web/load{n}.js": heavy(3_000).replace(b"../web/", b"./") for n in range(4)}
    root = tree(tmp_path, files)
    with pytest.raises(AnalysisError, match="analysis_fact_limit"):
        run(root, until=4)


# ------------------------------------------- tiers 2 and 3, with a smaller cap


def capped(monkeypatch: pytest.MonkeyPatch, facts: int) -> None:
    limits = Limits(facts=facts)
    for module in (sandbox, grounding, story_extract):
        monkeypatch.setattr(module, "DEFAULT_LIMITS", limits)


@pytest.mark.parametrize("tier", [1, 2, 3])
def test_imports_then_all_test_facts_are_dropped_only_when_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tier: int
) -> None:
    root = tree(
        tmp_path, PRODUCTION | {"tests/test_main.py": PYTHON_TEST, "tests/a.test.js": heavy(5)}
    )
    base = run(root, until=4)
    every = unbudgeted(root, base["inputs"]["4"]["manifest"])
    tests = paths_of_tests(base["inputs"]["4"]["manifest"])
    counts = {1: 0, 2: 0, 3: 0}
    for path in sorted(tests):
        for level in tiers([s for s in every if s["path"] == path]):
            counts[level] += 1
    production = len(every) - sum(counts.values())
    capped(monkeypatch, production + sum(counts[t] for t in range(tier + 1, 4)))
    state = run(root, given=again(base["stage3"]))
    manifest = state["inputs"]["4"]["manifest"]
    symbols = state["inputs"]["4"]["structure"]["symbols"]
    assert [s for s in symbols if s["path"] not in tests] == [
        s for s in every if s["path"] not in tests
    ]
    ids = {s["id"] for s in symbols}
    # No kept fact names a dropped one: a base class's import goes with the import.
    assert all(s["syntax"].get("lexical_target_id") in ids | {None} for s in symbols)
    assert all(s["syntax"].get("enclosing_symbol_id") in ids | {None} for s in symbols)
    assert {f["reason"] for f in manifest["files"] if f["path"] in tests} == {REASONS[tier]}
    assert state["inputs"]["9"]["verification"]["counts"]["verified"] > 0
    payload = state["inputs"]["9"]
    sources = story_sources(root, payload)
    story = extract_story(payload, sources, discover(payload, sources_from(root, payload)))
    said = [c.text for c in story.unresolved_questions.claims]
    assert said[0] == TEMPLATES[f"fact_budget_{tier}"].format(
        limit=f"{production + sum(counts[t] for t in range(tier + 1, 4)):,}",
        files="2 test files",
    )
    assert (TEMPLATES["no_tests"] in said) is False  # test files exist even when tier 3 ran


def test_production_alone_over_a_smaller_cap_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tree(tmp_path, PRODUCTION | {"tests/test_main.py": PYTHON_TEST})
    base = run(root, until=4)
    every = unbudgeted(root, base["inputs"]["4"]["manifest"])
    tests = paths_of_tests(base["inputs"]["4"]["manifest"])
    capped(monkeypatch, len([s for s in every if s["path"] not in tests]) - 1)
    with pytest.raises(AnalysisError, match="analysis_fact_limit"):
        run(root, given=again(base["stage3"]), until=4)


def test_payloads_stay_canonical_json(heavy_tests: tuple[Path, dict[str, Any]]) -> None:
    _, state = heavy_tests
    body = canonical(state["inputs"]["4"])
    assert json.loads(body) == state["inputs"]["4"]

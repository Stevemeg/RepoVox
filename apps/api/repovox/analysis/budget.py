"""Deterministic test-file fact budget under the unchanged repository cap (ADR-0030).

At or under `Limits.facts` every fact is kept and nothing changes. Above it, test-file facts
are dropped in three fixed tiers, each only if the total still exceeds the cap:

1. call facts;
2. import facts, together with any fact whose lexical target is one of those imports;
3. every remaining fact.

Non-test facts (source and context) are never dropped. If they alone exceed the cap, the
repository fails closed with `analysis_fact_limit`, exactly as before. Stage 4 and the
Stage 9 verifier apply the same rule to the same bytes, so the result is reproducible.
"""

from typing import Any

from repovox.analysis.common import AnalysisError

PARSED = "parsed_without_errors"
# The manifest reason of a parsed test file that lost facts, by the repository's tier.
REASONS = {
    1: "parsed_test_calls_omitted",
    2: "parsed_test_calls_imports_omitted",
    3: "parsed_test_facts_omitted",
}
BUDGET_REASONS = frozenset(REASONS.values())
KEPT = 4  # The tier of a non-test fact: never dropped.
PREFIX = "Test-fact budget:"


def tiers(facts: list[dict[str, Any]]) -> list[int]:
    """The tier at which the budget drops each fact of one test file."""
    imports = {f["id"] for f in facts if f["kind"] == "import"}
    return [
        1
        if f["kind"] == "call"
        else 2
        if f["kind"] == "import" or f.get("syntax", {}).get("lexical_target_id") in imports
        else 3
        for f in facts
    ]


class FactBudget:
    """Facts in arrival order. Memory stays bounded: a tier the rule drops is released."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.non_test = 0
        self.counts = {1: 0, 2: 0, 3: 0}
        self.held: list[tuple[int, dict[str, Any]]] = []
        self.lowest: dict[str, int] = {}  # test file -> the lowest tier among its facts
        self.released = 0

    def add(self, path: str, facts: list[dict[str, Any]], test: bool) -> None:
        if test:
            levels = tiers(facts)
            for level in levels:
                self.counts[level] += 1
            arriving = list(zip(levels, facts, strict=True))
            if levels:
                self.lowest[path] = min(levels)
        else:
            self.non_test += len(facts)
            arriving = [(KEPT, f) for f in facts]
        # Counts only grow, so a tier dropped now is dropped whatever arrives later: it is
        # released from what is held and never held again.
        level = self.level()
        if level > self.released:
            self.held = [item for item in self.held if item[0] > level]
            self.released = level
        self.held.extend(item for item in arriving if item[0] > level)

    def level(self) -> int:
        """How many tiers the rule drops; fails closed when non-test facts alone exceed it."""
        total = self.non_test + sum(self.counts.values())
        level = 0
        while total > self.limit and level < 3:
            level += 1
            total -= self.counts[level]
        if total > self.limit:
            raise AnalysisError("analysis_fact_limit")
        return level

    def kept(self) -> list[dict[str, Any]]:
        level = self.level()
        return [fact for tier, fact in self.held if tier > level]

    def omitted(self) -> dict[str, str]:
        """The manifest reason of every test file that lost at least one fact."""
        level = self.level()
        if not level:
            return {}
        return {path: REASONS[level] for path, low in sorted(self.lowest.items()) if low <= level}


def record(manifest: dict[str, Any], omitted: dict[str, str]) -> None:
    for file in manifest["files"]:
        if file["path"] in omitted:
            file["reason"] = omitted[file["path"]]


def consistent(manifest: dict[str, Any], omitted: dict[str, str]) -> bool:
    """Whether the manifest records exactly the files the budget reproduces, and no other."""
    recorded = {f["path"]: f for f in manifest["files"] if f["reason"] in BUDGET_REASONS}
    return {path: f["reason"] for path, f in recorded.items()} == omitted and all(
        f["status"] == "parsed" for f in recorded.values()
    )


def disclosure(manifest: dict[str, Any], limit: int) -> list[str]:
    """The limitation line a budgeted analysis states; empty when nothing was omitted."""
    reasons = [f["reason"] for f in manifest["files"] if f["reason"] in BUDGET_REASONS]
    if not reasons:
        return []
    count = len(reasons)
    files = f"{count} test file" + ("" if count == 1 else "s")
    omitted = {
        REASONS[1]: f"call facts from {files} were omitted; their test definitions and imports "
        "were kept",
        REASONS[2]: f"call and import facts from {files} were omitted; their test definitions "
        "were kept",
        REASONS[3]: f"every fact from {files} was omitted; the files still count as parsed",
    }[max(reasons, key=lambda r: [*REASONS.values()].index(r))]
    return [
        f"{PREFIX} the repository exceeded the {limit:,}-fact analysis cap, so {omitted}. "
        "The budget omitted no source-file fact."
    ]

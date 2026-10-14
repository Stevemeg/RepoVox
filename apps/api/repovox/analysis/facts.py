"""Source-fact-2.0: source semantics separate from extractor provenance.

No v1 reference adapter or pilot-specific vocabulary translation is provided.
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from repovox.evaluation.gold import SHA, Citation, Record, source_valid


class Syntax(Record):
    category: str
    qualified_name: str
    import_module: str | None = None
    imported_member: str | None = None
    local_binding: str | None = None
    type_only: bool = False
    scope: list[str] = Field(default_factory=list)
    lexical_target_id: str | None = None
    enclosing_symbol_id: str | None = None
    unsafe_binding: bool = False
    default_export: bool = False
    exported: bool = False
    constructor: bool = False
    candidate_category: str | None = None
    candidate_support_ids: list[str] = Field(default_factory=list)


class SemanticSymbol(Citation):
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=0)
    category: str
    language: str
    source_name: str
    qualified_name: str
    import_module: str | None = None
    imported_member: str | None = None
    alias: str | None = None
    local_binding: str | None = None
    type_only: bool = False
    parameters: list[str] | None = None
    dispatch: str | None = None
    constructor: bool = False
    default_export: bool = False
    exported: bool = False
    binding: str | None = None

    @model_validator(mode="after")
    def valid_symbol(self) -> "SemanticSymbol":
        if self.end_byte < self.start_byte:
            raise ValueError("invalid_byte_range")
        if self.category in {"import_module", "import_member"}:
            if self.import_module is None or (
                self.category == "import_member" and not self.imported_member
            ):
                raise ValueError("import_identity_required")
            if self.category == "import_module" and self.imported_member is not None:
                raise ValueError("unexpected_import_member")
            expected = self.import_module
            if self.imported_member:
                expected += ("" if expected.endswith(".") else ".") + self.imported_member
            if self.qualified_name != expected or self.alias != self.local_binding:
                raise ValueError("inconsistent_import_identity")
        return self


class CanonicalFact(Record):
    schema_version: Literal["source-fact-2.0"] = "source-fact-2.0"
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    commit_sha: SHA
    category: Literal["syntax", "relationship", "entrypoint"]
    subject: SemanticSymbol
    target: SemanticSymbol | None = None
    relationship: str | None = None
    classification: Literal["declared", "resolved_static", "unresolved", "inferred"]
    support: list[Citation] = Field(min_length=1)
    entrypoint_category: str | None = None
    entrypoint_target: str | None = None
    parser_rules: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def qualified(self) -> "CanonicalFact":
        if self.category == "relationship" and (self.target is None or not self.relationship):
            raise ValueError("relationship_identity_required")
        if self.category != "relationship" and (self.target is not None or self.relationship):
            raise ValueError("unexpected_relationship")
        if self.category == "entrypoint" and not self.entrypoint_category:
            raise ValueError("entrypoint_category_required")
        if self.category != "entrypoint" and (
            self.entrypoint_category is not None or self.entrypoint_target is not None
        ):
            raise ValueError("unexpected_entrypoint")
        if len({json.dumps(c.model_dump(), sort_keys=True) for c in self.support}) != len(
            self.support
        ):
            raise ValueError("duplicate_canonical_support")
        anchors = {(c.path, c.file_sha256, c.start_line, c.end_line) for c in self.support}
        for endpoint in [self.subject, self.target]:
            if (
                endpoint
                and (endpoint.path, endpoint.file_sha256, endpoint.start_line, endpoint.end_line)
                not in anchors
            ):
                raise ValueError("canonical_endpoint_missing_support")
        return self


def identity(fact: CanonicalFact) -> str:
    """Only parser provenance is non-semantic; support order is a set, never erased."""
    value = fact.model_dump(exclude={"parser_rules"})
    value["support"] = sorted(value["support"], key=lambda c: json.dumps(c, sort_keys=True))
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def validate_source(fact: CanonicalFact, root: Path, repository: str, commit_sha: str) -> None:
    """Validate original anchors, not semantic truth or a reviewer approval."""
    if (fact.repository, fact.commit_sha) != (repository, commit_sha):
        raise ValueError("canonical_snapshot_mismatch")
    for anchor in fact.support:
        if not source_valid(anchor, root):
            raise ValueError("canonical_source_invalid")
    for endpoint in [fact.subject, fact.target]:
        if endpoint:
            body = (root / endpoint.path).read_bytes()
            start, end = endpoint.start_byte, endpoint.end_byte
            if not 0 <= start <= end <= len(body) or (
                body[:start].count(b"\n") + 1 != endpoint.start_line
                or body[: max(start, end - 1)].count(b"\n") + 1 != endpoint.end_line
            ):
                raise ValueError("canonical_byte_range_invalid")


def validate_collection(facts: list[CanonicalFact]) -> None:
    identities = [identity(fact) for fact in facts]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate_canonical_fact")


def semantic_symbol(symbol: dict[str, Any]) -> SemanticSymbol:
    syntax = Syntax.model_validate(symbol["syntax"])
    name = symbol["name"]
    qualified = syntax.qualified_name
    alias = None
    if syntax.category in {"import_module", "import_member"}:
        # Both spellings come from explicit module/member/binding syntax, never string guessing.
        name = syntax.imported_member or syntax.import_module
        qualified = syntax.import_module or ""
        if syntax.imported_member:
            qualified = qualified + ("" if qualified.endswith(".") else ".")
            qualified += syntax.imported_member
        alias = syntax.local_binding
    return SemanticSymbol(
        **{k: symbol[k] for k in Citation.model_fields},
        category=syntax.category,
        language=symbol["parser_language"],
        source_name=name,
        qualified_name=qualified,
        import_module=syntax.import_module,
        imported_member=syntax.imported_member,
        local_binding=syntax.local_binding,
        alias=alias,
        type_only=syntax.type_only,
        parameters=symbol.get("parameters"),
        dispatch=symbol.get("dispatch"),
        start_byte=symbol["start_byte"],
        end_byte=symbol["end_byte"],
        constructor=syntax.constructor,
        default_export=syntax.default_export,
        exported=syntax.exported,
        binding=symbol.get("binding"),
    )


def project(
    snapshot: dict[str, Any],
    symbols: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    indexed = {s["id"]: s for s in symbols}
    result: list[dict[str, Any]] = []
    base = {"repository": snapshot["repository"], "commit_sha": snapshot["commit_sha"]}

    def anchors(ids: list[str]) -> list[Citation]:
        values = [{k: indexed[i][k] for k in Citation.model_fields} for i in ids]
        return [
            Citation.model_validate(v)
            for v in {json.dumps(v, sort_keys=True): v for v in values}.values()
        ]

    for s in symbols:
        result.append(
            CanonicalFact(
                **base,
                category="syntax",
                subject=semantic_symbol(s),
                classification="declared",
                support=anchors([s["id"]]),
                parser_rules=[s["rule"]],
            ).model_dump()
        )
    for e in edges:
        result.append(
            CanonicalFact(
                **base,
                category="relationship",
                subject=semantic_symbol(indexed[e["source"]]),
                target=semantic_symbol(indexed[e["target"]]),
                relationship=e["relationship"],
                classification=e["classification"],
                support=anchors([e["source"], e["target"], *e["support_ids"]]),
                parser_rules=[e["rule"]],
            ).model_dump()
        )
    for e in entries:
        result.append(
            CanonicalFact(
                **base,
                category="entrypoint",
                subject=semantic_symbol(indexed[e["symbol_id"]]),
                classification="declared",
                support=anchors(e["support_ids"]),
                parser_rules=[e["rule"]],
                entrypoint_category=e["category"],
                entrypoint_target=e.get("target"),
            ).model_dump()
        )
    return result

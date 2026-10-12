"""Independent gold contract. No analyzer output is used to author expected facts/verdicts."""

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
ID = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")]
Status = Literal["verified", "inferred", "documentation_only", "unsupported"]
Classification = Literal["declared", "resolved_static", "unresolved", "inferred"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Citation(Record):
    path: str = Field(min_length=1, max_length=1024)
    file_sha256: Hash
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def safe_range(self) -> "Citation":
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or path.as_posix() != self.path
            or any(part in {".", ".."} for part in path.parts)
            or any(ord(c) < 32 for c in self.path)
            or "\\" in self.path
            or ":" in self.path
            or self.end_line < self.start_line
        ):
            raise ValueError("invalid_gold_source_range")
        return self


class Attributes(Record):
    parameters: list[str] | None = None
    alias: str | None = None
    imported_name: str | None = None
    binding: str | None = None
    dispatch: str | None = None


class SymbolIdentity(Citation):
    kind: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=1024)
    language: str = Field(min_length=1, max_length=80)
    rule: str = Field(min_length=1, max_length=80)
    attributes: Attributes


class GoldSymbol(SymbolIdentity):
    id: ID


class EdgeIdentity(Record):
    source: SymbolIdentity
    target: SymbolIdentity
    relationship: str = Field(min_length=1, max_length=80)
    classification: Classification
    support: list[SymbolIdentity] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_support(self) -> "EdgeIdentity":
        support = [json.dumps(s.model_dump(), sort_keys=True) for s in self.support]
        if len(set(support)) != len(support):
            raise ValueError("duplicate_fact_support")
        return self


class GoldEdge(EdgeIdentity):
    id: ID
    supported: bool
    citations: list[Citation] = Field(min_length=1)

    @model_validator(mode="after")
    def cited_support(self) -> "GoldEdge":
        if not {anchor(s) for s in self.support} <= {anchor(c) for c in self.citations}:
            raise ValueError("edge_missing_fact_evidence")
        return self


class GoldEntrypoint(Record):
    id: ID
    path: str
    rule: str = Field(min_length=1, max_length=80)
    target: str | None = None
    citations: list[Citation] = Field(min_length=1)

    @model_validator(mode="after")
    def grounded_path(self) -> "GoldEntrypoint":
        if not any(c.path == self.path for c in self.citations):
            raise ValueError("entrypoint_missing_source")
        return self


class SymbolFact(Record):
    type: Literal["symbol_syntax"]
    symbol: SymbolIdentity


class EdgeFact(Record):
    type: Literal["static_relationship"]
    edge: EdgeIdentity


Fact = Annotated[SymbolFact | EdgeFact, Field(discriminator="type")]


def anchor(citation: Citation) -> tuple[str, str, int, int]:
    return citation.path, citation.file_sha256, citation.start_line, citation.end_line


def identity(fact: Fact, repository: str, sha: str) -> str:
    """Canonical assertion identity, independent of gold/prediction IDs and verdicts."""
    payload = fact.model_dump()
    if isinstance(fact, EdgeFact):
        payload["edge"]["support"] = sorted(
            payload["edge"]["support"], key=lambda item: json.dumps(item, sort_keys=True)
        )
    return json.dumps(
        {
            "protocol": "source-fact-1.0",
            "repository": repository,
            "commit_sha": sha,
            "fact": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


class GoldClaim(Record):
    id: ID
    text: str = Field(min_length=1, max_length=4096)
    status: Status
    fact: Fact
    citations: list[Citation] = Field(min_length=1)

    @model_validator(mode="after")
    def cited_fact(self) -> "GoldClaim":
        support = (
            [self.fact.symbol] if isinstance(self.fact, SymbolFact) else self.fact.edge.support
        )
        if not {anchor(s) for s in support} <= {anchor(c) for c in self.citations}:
            raise ValueError("claim_missing_fact_evidence")
        return self


class GoldEvaluation(Record):
    gold_schema_version: Literal["gold-evaluation-1.0"]
    repository: str = Field(min_length=1)
    commit_sha: SHA
    annotation_scope: Literal["complete", "partial"]
    symbols: list[GoldSymbol]
    entrypoints: list[GoldEntrypoint]
    edges: list[GoldEdge]
    claims: list[GoldClaim]
    safety_observations: dict[str, str]

    @model_validator(mode="after")
    def unique_annotations(self) -> "GoldEvaluation":
        ids = (
            [s.id for s in self.symbols]
            + [e.id for e in self.entrypoints]
            + [e.id for e in self.edges]
            + [c.id for c in self.claims]
        )
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_gold_id")
        facts = [identity(c.fact, self.repository, self.commit_sha) for c in self.claims]
        if len(set(facts)) != len(facts):
            raise ValueError("duplicate_gold_fact")
        symbols = [json.dumps(s.model_dump(exclude={"id"}), sort_keys=True) for s in self.symbols]
        if len(set(symbols)) != len(symbols):
            raise ValueError("duplicate_gold_symbol")
        return self


def source_valid(citation: Citation, root: Path) -> bool:
    candidate = root / citation.path
    path = candidate.resolve()
    if candidate.is_symlink() or not path.is_relative_to(root.resolve()) or not path.is_file():
        return False
    body = path.read_bytes()
    return hashlib.sha256(
        body
    ).hexdigest() == citation.file_sha256 and 1 <= citation.start_line <= citation.end_line <= len(
        body.split(b"\n")
    )


def validate_gold_source(gold: GoldEvaluation, root: Path) -> None:
    citations: list[Citation] = list(gold.symbols)
    for entry in gold.entrypoints:
        citations.extend(entry.citations)
    for edge in gold.edges:
        citations.extend([edge.source, edge.target, *edge.support, *edge.citations])
    for claim in gold.claims:
        citations.extend(claim.citations)
        if isinstance(claim.fact, SymbolFact):
            citations.append(claim.fact.symbol)
        else:
            fact_edge = claim.fact.edge
            citations.extend([fact_edge.source, fact_edge.target, *fact_edge.support])
    if not all(source_valid(citation, root) for citation in citations):
        raise ValueError("gold_invalid_citation")
    # This checks provenance, not entailment or independent-human approval.

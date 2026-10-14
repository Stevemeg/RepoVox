"""Analysis 2.3; explicit legacy 2.2 reader, no reinterpretation of sealed artifacts."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from repovox.analysis.facts import CanonicalFact, Syntax, validate_collection

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
ID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*$")]
Status = Literal["verified", "inferred", "documentation_only", "unsupported"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SnapshotData(Strict):
    repository: str
    canonical_url: str
    github_id: int
    owner: str
    name: str
    public: Literal[True]
    default_branch: str
    commit_sha: SHA
    acquired_at: str
    acquisition_version: Literal["github-archive-v1"]


class SourceFile(Strict):
    path: str
    file_sha256: Hash
    bytes: int = Field(ge=0)
    language: str
    classification: str
    status: Literal["eligible", "parsed", "skipped", "failed", "context"]
    reason: str
    parsed_bytes: int = Field(ge=0)


class Manifest(Strict):
    repository: str
    commit_sha: SHA
    acquisition_version: str
    archive_sha256: Hash
    files: list[SourceFile] = Field(max_length=10000)
    eligible_bytes: int = Field(ge=0)
    parsed_bytes: int = Field(ge=0)
    excluded_bytes: int = Field(ge=0)
    eligible_files: int = Field(ge=0, le=5000)
    processing_timestamp: str
    parser_version: str
    pipeline_version: str
    coverage: float = Field(default=0, ge=0, le=1)
    parsed_non_test_files: int = Field(default=0, ge=0)
    language_coverage: dict[str, dict[str, int]] = Field(default_factory=dict)


class Symbol(Strict):
    syntax: Syntax
    id: ID
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=0)
    kind: str
    name: str = Field(max_length=1024)
    file_sha256: Hash
    parser_language: str
    parser_version: str
    rule: str
    qualification: str
    parameters: list[str] | None = None
    dispatch: str | None = None
    binding: str | None = None
    alias: str | None = None
    imported_name: str | None = None


class ParseError(Strict):
    path: str
    start_line: int
    end_line: int


class Structure(Strict):
    symbols: list[Symbol] = Field(max_length=10000)
    parse_errors: list[ParseError] = Field(max_length=10000)
    parser_version: str
    rule_version: str


class Candidate(Strict):
    category: Literal[
        "executable_application",
        "library_export",
        "type_declaration",
        "build_system",
        "plugin",
        "packaging_hook",
        "candidate_command",
    ]
    symbol_id: ID
    path: str
    rule: str
    support_ids: list[ID]
    rank: int
    target: str | None = None
    qualification: str | None = None


class Framework(Strict):
    name: str
    symbol_id: ID
    qualification: str


class Entrypoints(Strict):
    candidates: list[Candidate]
    selected: ID | None
    frameworks: list[Framework]
    scope: str
    uncertainty: list[str]


class PropertyRange(Strict):
    property_path: list[str]
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=0)


class Dependency(PropertyRange):
    name: str
    declared_constraint: str
    locked_version: Literal[None]
    path: str


class ConfigEntry(PropertyRange):
    category: str
    path: str
    target: str
    rule: str


class Configuration(Strict):
    dependencies: list[Dependency]
    config_entries: list[ConfigEntry]
    config_errors: list[str]


class NodeData(Strict):
    id: ID
    kind: str
    path: str
    name: str


class Edge(Strict):
    id: ID
    source: ID
    target: ID
    relationship: str
    classification: Literal["declared", "resolved_static", "unresolved", "inferred"]
    support_ids: list[ID]
    rule: str
    qualification: str
    claim_ids: list[ID] | None = None


class Graph(Strict):
    nodes: list[NodeData]
    edges: list[Edge]
    entrypoints: Entrypoints
    rule_version: str
    limitations: list[str]


class Claim(Strict):
    id: ID
    text: str
    status: Status
    evidence_ids: list[ID]
    reason: str
    rule: str
    subject_id: ID


class Versions(Strict):
    parser: str
    pipeline: str
    rules: str
    schema_name: str = Field(alias="schema")


class Flow(Strict):
    id: ID
    entrypoint_id: ID
    module_id: ID
    node_ids: list[ID]
    edge_ids: list[ID]
    qualification: str


class Knowledge(Strict):
    canonical_facts: list[CanonicalFact]
    repository: SnapshotData
    scope: str
    stack: list[str]
    frameworks: list[Framework]
    purpose_candidates: list[str]
    modules: list[str]
    symbols: list[Symbol]
    nodes: list[NodeData]
    edges: list[Edge]
    entrypoints: Entrypoints
    execution_flows: list[Flow]
    dependencies: list[Dependency]
    claims: list[Claim] = Field(max_length=20000)
    coverage: Manifest
    limitations: list[str]
    versions: Versions

    @model_validator(mode="after")
    def unique_facts(self) -> "Knowledge":
        validate_collection(self.canonical_facts)
        return self


class Redaction(Strict):
    start_line: int
    end_line: int
    reason: str


class EvidenceItem(Strict):
    id: ID
    snapshot_id: UUID
    commit_sha: SHA
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    file_sha256: Hash
    symbol_id: ID
    kind: Literal["source", "documentation", "manifest"]
    rule: str
    redacted: bool
    redactions: list[Redaction]
    excerpt: str = Field(max_length=4096)
    excerpt_end_line: int
    permalink: str
    validation_status: Literal["pending", "valid", "invalid"]
    last_checked_at: str


class Evidence(Strict):
    items: list[EvidenceItem] = Field(max_length=10000)


class Verdict(Strict):
    claim_id: ID
    status: Status
    evidence_ids: list[ID]
    rule: str
    reason: str
    conflict_ids: list[ID]


class Ledger(Strict):
    verifier_version: str
    verdicts: list[Verdict]
    counts: dict[Status, int]
    conflicts: list[str]
    scope: str


class Parsed(Strict):
    manifest: Manifest
    structure: Structure
    configuration: Configuration


class EvidenceBundle(Strict):
    knowledge: Knowledge
    evidence: Evidence


class Verified(Strict):
    knowledge: Knowledge
    evidence: Evidence
    verification: Ledger


PAYLOADS: dict[str, type[BaseModel]] = {
    "validate": SnapshotData,
    "filter": Manifest,
    "structure": Parsed,
    "entrypoints": Entrypoints,
    "infer": Graph,
    "knowledge": Knowledge,
    "evidence": EvidenceBundle,
    "verify": Verified,
}


class Envelope(Strict):
    schema_version: Literal["2.3"]
    kind: Literal[
        "validate", "filter", "structure", "entrypoints", "infer", "knowledge", "evidence", "verify"
    ]
    owner_id: UUID
    snapshot_id: UUID
    commit_sha: SHA
    pipeline_version: Literal["phase2-static-v1"]
    input_digest: Hash
    generation_metadata: Literal[None]
    payload: dict[str, Any]


def validate_envelope(value: dict[str, Any]) -> None:
    if value.get("schema_version") == "2.2":
        from repovox.analysis.contracts_v22 import validate_envelope as legacy

        legacy(value)
        return
    envelope = Envelope.model_validate(value)
    TypeAdapter(PAYLOADS[envelope.kind]).validate_python(envelope.payload)

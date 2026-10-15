"""Independent v2 reference contracts and original-source validation.

Only reviewed canonical schema/identity primitives are shared with analysis.
No extraction, rule-based verification or reference generation occurs here.
"""

import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

from repovox.analysis.facts import CanonicalFact, SemanticSymbol, identity
from repovox.evaluation.gold import ID, SHA, Citation, Hash, Record

Status = Literal["verified", "inferred", "documentation_only", "unsupported", "unreviewed"]
T = TypeVar("T", bound=BaseModel)
ENTRY_CATEGORIES = {
    "executable_application",
    "candidate_command",
    "library_export",
    "type_declaration",
    "build_system",
    "packaging_hook",
    "plugin",
}
RELATIONSHIPS = {
    "contains",
    "imports",
    "call_expression",
    "imports_symbol",
    "inherits",
    "calls_lexically",
    "instantiates",
}
SYMBOL_CATEGORIES = {
    "module",
    "class",
    "function",
    "method",
    "import_module",
    "import_member",
    "call",
    "base_reference",
    "export",
    "decorator",
    "entrypoint",
    "documentation",
    "declared_dependency",
    "config_entry",
    "plugin_registration",
}


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def serialize(value: Record | dict[str, Any]) -> bytes:
    data = value.model_dump(mode="json") if isinstance(value, Record) else value
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def decode(body: bytes, expected_hash: str, model: type[T]) -> T:
    if len(body) > 100_000_000:
        raise ValueError("v2_packet_size_limit")
    if digest(body) != expected_hash:
        raise ValueError("v2_commitment_mismatch")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("v2_duplicate_json_key")
            result[key] = value
        return result

    def invalid(value: str) -> Any:
        raise ValueError("v2_invalid_json_constant")

    value = json.loads(body, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict) or "schema_version" not in value:
        raise ValueError("v2_explicit_schema_version_required")

    def fact_versions(item: Any) -> None:
        if isinstance(item, dict):
            collection = item.get("canonical_facts", [])
            if not isinstance(collection, list):
                raise ValueError("v2_invalid_fact_collection")
            facts = ([item["fact"]] if "fact" in item else []) + collection
            for fact in facts:
                if not isinstance(fact, dict) or fact.get("schema_version") != "source-fact-2.0":
                    raise ValueError("v2_explicit_source-fact-2.0_required")
            for nested in item.values():
                fact_versions(nested)
        elif isinstance(item, list):
            for nested in item:
                fact_versions(nested)

    fact_versions(value)
    return model.model_validate(value)


def fact_key(fact: CanonicalFact) -> str:
    return digest(identity(fact).encode())


def profile(fact: CanonicalFact) -> None:
    # Evaluation profile restrictions do not change accepted canonical identity semantics.
    if fact.category == "relationship" and fact.relationship not in RELATIONSHIPS:
        raise ValueError("v2_unknown_relationship")
    if fact.category == "entrypoint" and fact.entrypoint_category not in ENTRY_CATEGORIES:
        raise ValueError("v2_invalid_entrypoint_category")
    for endpoint in [fact.subject, fact.target]:
        if endpoint and endpoint.start_byte == endpoint.end_byte:
            raise ValueError("v2_empty_byte_range")
        if endpoint and (
            endpoint.category not in SYMBOL_CATEGORIES
            or not endpoint.language
            or not endpoint.qualified_name
            or endpoint.dispatch not in {None, "named", "dynamic"}
        ):
            raise ValueError("v2_empty_symbol_identity")


class Policy(Record):
    track: Literal["AI_AUDITED_EXPLORATORY"] = "AI_AUDITED_EXPLORATORY"
    independently_human_reviewed: Literal[False] = False
    official_eval_entry_contribution: Literal[False] = False
    training_authorized: Literal[False] = False
    production_certification: Literal[False] = False


class Window(Citation):
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> "Window":
        if self.end_byte == self.start_byte:
            raise ValueError("v2_empty_byte_range")
        if self.end_byte < self.start_byte:
            raise ValueError("v2_invalid_byte_range")
        return self


class SourceFile(Record):
    path: str
    file_sha256: Hash
    language: str = Field(min_length=1)
    size: int = Field(ge=0, le=5_000_000)
    windows: list[Window] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def consistent(self) -> "SourceFile":
        last = -1
        for w in sorted(self.windows, key=lambda w: w.start_byte):
            if (w.path, w.file_sha256) != (self.path, self.file_sha256) or not (
                last < w.start_byte < w.end_byte <= self.size
            ):
                raise ValueError("v2_scope_window_overlap_or_mismatch")
            last = w.end_byte - 1
        return self


class Scope(Record):
    schema_version: Literal["evaluation-source-scope-2.0"] = "evaluation-source-scope-2.0"
    policy: Policy
    usage: Literal["SYNTHETIC_FIXTURE", "FUTURE_BLIND_PILOT"]
    tenant_id: ID
    analysis_owner_id: str = Field(pattern=r"^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$")
    family_id: ID
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    commit_sha: SHA
    rights_decision: Literal["PERMITTED_INTERNAL_EXPLORATORY"]
    rights_evidence_sha256: Hash
    snapshot_verification_sha256: Hash
    files: list[SourceFile] = Field(min_length=1, max_length=5000)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_files(self) -> "Scope":
        if len({f.path for f in self.files}) != len(self.files):
            raise ValueError("v2_duplicate_scope_file")
        if sum(f.size for f in self.files) > 50_000_000:
            raise ValueError("v2_source_budget")
        return self


class Judgment(Record):
    id: ID
    fact: CanonicalFact
    expected_status: Status
    evidence_entailment: Literal["supported", "unsupported", "unreviewed"]
    rationale: str = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def valid(self) -> "Judgment":
        profile(self.fact)
        if self.expected_status == "unreviewed" and self.evidence_entailment != "unreviewed":
            raise ValueError("v2_unreviewed_judgment_conflict")
        if self.expected_status == "verified" and self.evidence_entailment != "supported":
            raise ValueError("v2_verified_judgment_needs_support")
        return self


class Observation(Record):
    id: ID
    assertion: str = Field(min_length=1, max_length=4096)
    status: Status
    citations: list[Window] = Field(min_length=1)
    # Free semantic/runtime assertions are deliberately outside atomic matching.
    evaluation: Literal["SEMANTIC REVIEW REQUIRED"] = "SEMANTIC REVIEW REQUIRED"


class Provenance(Record):
    author_role: Literal["INDEPENDENT_AI_TECHNICAL_REVIEWER", "SYNTHETIC_TEST_AUTHOR"]
    source_only_attestation_sha256: Hash
    response_capture_sha256: Hash
    identity_basis: Literal["owner_attested", "synthetic_fixture"]
    provider_authenticated: Literal[False] = False

    @model_validator(mode="after")
    def consistent_origin(self) -> "Provenance":
        if (self.author_role == "SYNTHETIC_TEST_AUTHOR") != (
            self.identity_basis == "synthetic_fixture"
        ):
            raise ValueError("v2_provenance_role_mismatch")
        return self


class Reference(Record):
    schema_version: Literal["gold-evaluation-2.0"] = "gold-evaluation-2.0"
    policy: Policy
    tenant_id: ID
    family_id: ID
    repository: str
    commit_sha: SHA
    scope_sha256: Hash
    blind_source_sha256: Hash
    prediction_commitment_sha256: Hash
    annotation_scope: Literal["complete", "partial"]
    scope_description: str = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    provenance: Provenance
    assertions: list[Judgment] = Field(max_length=20000)
    observations: list[Observation] = Field(max_length=1000)
    revision: int = Field(ge=1, le=100)
    revision_context: Literal[
        "initial_blind", "source_only_correction", "post_reveal_correction"
    ] = "initial_blind"
    supersedes_sha256: Hash | None
    correction_reason: str | None
    correction_citations: list[Window]
    correction_approval_sha256: Hash | None = None

    @model_validator(mode="after")
    def valid(self) -> "Reference":
        ids = [a.id for a in self.assertions] + [o.id for o in self.observations]
        if len(set(ids)) != len(ids):
            raise ValueError("v2_duplicate_reference_id")
        keys = [fact_key(a.fact) for a in self.assertions]
        if len(set(keys)) != len(keys):
            raise ValueError("v2_duplicate_reference_fact")
        for a in self.assertions:
            if (a.fact.repository, a.fact.commit_sha) != (self.repository, self.commit_sha):
                raise ValueError("v2_reference_snapshot_mismatch")
        if self.revision == 1:
            if (
                self.supersedes_sha256
                or self.correction_reason
                or self.correction_citations
                or self.correction_approval_sha256
                or self.revision_context != "initial_blind"
            ):
                raise ValueError("v2_unexpected_correction")
        elif not (
            self.supersedes_sha256
            and self.correction_reason
            and self.correction_citations
            and self.correction_approval_sha256
            and self.revision_context != "initial_blind"
        ):
            raise ValueError("v2_correction_lineage_required")
        return self


class PredictedFact(Record):
    id: ID
    fact: CanonicalFact
    status: Status
    verdict_origin: Literal["bound_analysis_ledger", "no_verdict_available", "synthetic_fixture"]
    claim_id: str | None
    evidence: list[Citation] = Field(min_length=1)

    @model_validator(mode="after")
    def bound(self) -> "PredictedFact":
        profile(self.fact)
        if self.verdict_origin == "no_verdict_available" and (
            self.status != "unreviewed" or self.claim_id is not None
        ):
            raise ValueError("v2_unbound_verdict")
        if self.verdict_origin == "bound_analysis_ledger" and not self.claim_id:
            raise ValueError("v2_missing_claim_binding")
        if sorted(serialize(c) for c in self.evidence) != sorted(
            serialize(c) for c in self.fact.support
        ):
            raise ValueError("v2_evidence_support_mismatch")
        return self


class Unprojected(Record):
    id: ID
    status: Status
    reason: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class Prediction(Record):
    schema_version: Literal["evaluation-prediction-2.0"] = "evaluation-prediction-2.0"
    policy: Policy
    tenant_id: ID
    family_id: ID
    repository: str
    commit_sha: SHA
    scope_sha256: Hash
    analysis_sha256: Hash
    engineering_commit: SHA
    projection_version: Literal["analysis-2.3-verdict-projection-1.0", "synthetic-fixture-2.0"]
    facts: list[PredictedFact] = Field(max_length=30000)
    unprojected_claims: list[Unprojected] = Field(max_length=20000)
    selected_entrypoint: Hash | None
    selection_interpretation: Literal[
        "not_selected", "unique_static_candidate", "ambiguous_static_candidates"
    ] = "not_selected"

    @model_validator(mode="after")
    def valid(self) -> "Prediction":
        keys = [fact_key(a.fact) for a in self.facts]
        ids = [a.id for a in self.facts]
        claims = [a.claim_id for a in self.facts if a.claim_id is not None]
        claims += [a.id for a in self.unprojected_claims]
        if (
            len(set(keys)) != len(keys)
            or len(set(ids)) != len(ids)
            or len(set(claims)) != len(claims)
        ):
            raise ValueError("v2_duplicate_prediction")
        for a in self.facts:
            if (a.fact.repository, a.fact.commit_sha) != (self.repository, self.commit_sha):
                raise ValueError("v2_prediction_snapshot_mismatch")
            if (
                self.projection_version != "synthetic-fixture-2.0"
                and a.verdict_origin == "synthetic_fixture"
            ):
                raise ValueError("v2_synthetic_verdict_in_real_projection")
        if self.selected_entrypoint is not None and self.selected_entrypoint not in {
            fact_key(a.fact) for a in self.facts if a.fact.category == "entrypoint"
        }:
            raise ValueError("v2_selected_entrypoint_missing")
        if (self.selection_interpretation == "unique_static_candidate") != (
            self.selected_entrypoint is not None
        ):
            raise ValueError("v2_selection_interpretation_mismatch")
        return self


def source_bytes(root: Path, scope: Scope, proofs: dict[str, bytes]) -> dict[str, bytes]:
    from repovox.analysis.privacy import screen_bytes

    for key in [scope.rights_evidence_sha256, scope.snapshot_verification_sha256]:
        if key not in proofs or not proofs[key] or digest(proofs[key]) != key:
            raise ValueError("v2_rights_or_snapshot_evidence_missing")
    result = {}
    for f in scope.files:
        path = root / f.path
        if any(
            p.is_symlink() for p in [root, path, *path.parents]
        ) or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("v2_source_containment")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != f.size:
            raise ValueError("v2_source_hash_mismatch")
        with path.open("rb") as stream:
            body = stream.read(f.size + 1)
        if len(body) != f.size or digest(body) != f.file_sha256:
            raise ValueError("v2_source_hash_mismatch")
        body.decode("utf-8")
        screen_bytes(body)
        for w in f.windows:
            check_range(w, body)
        result[f.path] = body
    return result


def check_range(c: Citation, body: bytes) -> None:
    if not 1 <= c.start_line <= c.end_line <= len(body.split(b"\n")):
        raise ValueError("v2_line_range_invalid")
    if isinstance(c, (Window, SemanticSymbol)):
        start, end = c.start_byte, c.end_byte
        if start == end:
            raise ValueError("v2_empty_byte_range")
        if not 0 <= start <= end <= len(body) or (
            body[:start].count(b"\n") + 1 != c.start_line
            or body[: max(start, end - 1)].count(b"\n") + 1 != c.end_line
        ):
            raise ValueError("v2_byte_range_invalid")
        # Original UTF-8 boundaries, never offsets inside a multibyte code point.
        body[:start].decode("utf-8")
        body[:end].decode("utf-8")


def validate_citation(c: Citation, scope: Scope, bodies: dict[str, bytes]) -> None:
    f = next((f for f in scope.files if f.path == c.path), None)
    if f is None or c.file_sha256 != f.file_sha256:
        raise ValueError("v2_citation_outside_scope_or_hash")
    check_range(c, bodies[c.path])
    # Line-only support cannot claim lines partly excluded by a byte scope.
    body = bodies[c.path]
    start = sum(len(line) + 1 for line in body.split(b"\n")[: c.start_line - 1])
    end = min(len(body), sum(len(line) + 1 for line in body.split(b"\n")[: c.end_line]))
    if isinstance(c, (Window, SemanticSymbol)):
        start, end = c.start_byte, c.end_byte
    if start == end:
        raise ValueError("v2_empty_byte_range")
    if not any(w.start_byte <= start <= end <= w.end_byte for w in f.windows):
        raise ValueError("v2_citation_excluded_range")


def validate_fact(fact: CanonicalFact, scope: Scope, bodies: dict[str, bytes]) -> None:
    if (fact.repository, fact.commit_sha) != (scope.repository, scope.commit_sha):
        raise ValueError("v2_fact_snapshot_mismatch")
    profile(fact)
    for c in [fact.subject, *fact.support, *([fact.target] if fact.target else [])]:
        validate_citation(c, scope, bodies)
    languages = {f.path: f.language for f in scope.files}
    for endpoint in [fact.subject, fact.target]:
        if endpoint and endpoint.language != languages[endpoint.path]:
            raise ValueError("v2_source_language_mismatch")


def validate_reference(
    body: bytes,
    expected_hash: str,
    scope: Scope,
    scope_hash: str,
    source: Path,
    proofs: dict[str, bytes],
    predecessors: dict[str, bytes] | None = None,
) -> Reference:
    ref = decode(body, expected_hash, Reference)
    if (ref.tenant_id, ref.family_id, ref.repository, ref.commit_sha, ref.scope_sha256) != (
        scope.tenant_id,
        scope.family_id,
        scope.repository,
        scope.commit_sha,
        scope_hash,
    ):
        raise ValueError("v2_reference_scope_binding")
    bodies = source_bytes(source, scope, proofs)
    from repovox.evaluation.custody_v2 import SourcePacket, source_packet

    if ref.blind_source_sha256 not in proofs:
        raise ValueError("v2_blind_source_missing")
    packet = decode(proofs[ref.blind_source_sha256], ref.blind_source_sha256, SourcePacket)
    if packet != source_packet(
        serialize(scope), digest(serialize(scope)), source, proofs
    ).model_copy(update={"scope_sha256": scope_hash}):
        raise ValueError("v2_blind_source_content_mismatch")
    for key in [
        ref.provenance.response_capture_sha256,
        ref.provenance.source_only_attestation_sha256,
    ]:
        if key not in proofs or not proofs[key] or digest(proofs[key]) != key:
            raise ValueError("v2_capture_or_attestation_missing")
    for a in ref.assertions:
        validate_fact(a.fact, scope, bodies)
    for c in [*ref.correction_citations, *(c for o in ref.observations for c in o.citations)]:
        validate_citation(c, scope, bodies)
    if ref.revision > 1:
        approval = ref.correction_approval_sha256
        if approval not in proofs or not proofs[approval] or digest(proofs[approval]) != approval:
            raise ValueError("v2_correction_approval_missing")
        predecessor_key = ref.supersedes_sha256
        if not predecessors or predecessor_key not in predecessors:
            raise ValueError("v2_predecessor_missing")
        assert predecessor_key is not None
        prior = validate_reference(
            predecessors[predecessor_key],
            predecessor_key,
            scope,
            scope_hash,
            source,
            proofs,
            predecessors,
        )
        if ref.revision != prior.revision + 1:
            raise ValueError("v2_revision_gap")
        if (
            prior.revision_context == "post_reveal_correction"
            and ref.revision_context != "post_reveal_correction"
        ):
            raise ValueError("v2_correction_context_regression")
        if (ref.blind_source_sha256, ref.prediction_commitment_sha256) != (
            prior.blind_source_sha256,
            prior.prediction_commitment_sha256,
        ):
            raise ValueError("v2_revision_packet_binding")
    return ref

"""Problem-to-solution intelligence schema, version problem-to-solution-1.0. Data only.

An engineering story says what a repository's authors state it solves, what the pinned commit
actually implements, what its tests and examples show, and what stays unresolved. Every
statement is a `Claim` with an evidence type and a status. Status is assigned by fixed rules
in `story_extract` from the kind of evidence behind a claim, never from repository text, and
`story_extract.verify_story` re-checks every citation against the pinned source bytes.

Statuses:
  VERIFIED            exact cited source backed by a Stage 9 claim the verifier marked verified
  INFERRED            a deterministic rule over cited evidence; the binding is not proven
  DOCUMENTATION_ONLY  stated in documentation and not backed by code
  UNVERIFIED          an assertion or question that no repository evidence supports
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Literal["problem-to-solution-1.0"] = "problem-to-solution-1.0"
EXTRACTOR_VERSION: Literal["problem-to-solution-extractor-1.0"] = (
    "problem-to-solution-extractor-1.0"
)
EvidenceType = Literal[
    "author_stated_problem",
    "inferred_problem_context",
    "intended_solution",
    "implemented_solution",
    "demonstrated_outcome",
    "unverified_outcome",
    "limitation",
    "unresolved",
]
ClaimStatus = Literal["VERIFIED", "INFERRED", "DOCUMENTATION_ONLY", "UNVERIFIED"]
SourceRole = Literal["readme", "documentation", "manifest", "source", "test", "example"]
ProofKind = Literal["unit_test", "integration_test", "benchmark", "example"]
Explanation = Literal["supported", "unsupported", "unavailable"]
MismatchKind = Literal[
    "readme_only_feature",
    "mention_only_technology",
    "declared_only_technology",
    "unstated_implementation",
    "incomplete_implementation",
    "unbenchmarked_performance_claim",
    "unsupported_architecture_claim",
]
ID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
OUTCOME_SCOPE: Literal[
    "Test and example assertions are read from source; RepoVox does not run them. They show "
    "behaviour the authors check, not production use or measured performance."
] = (
    "Test and example assertions are read from source; RepoVox does not run them. They show "
    "behaviour the authors check, not production use or measured performance."
)

# Which statuses each evidence type may carry. Documentation can never be VERIFIED, and an
# outcome nothing supports can never be anything but UNVERIFIED.
STATUS_RULES: dict[str, frozenset[str]] = {
    "author_stated_problem": frozenset({"DOCUMENTATION_ONLY"}),
    "inferred_problem_context": frozenset({"DOCUMENTATION_ONLY"}),
    "intended_solution": frozenset({"DOCUMENTATION_ONLY", "INFERRED"}),
    "implemented_solution": frozenset({"VERIFIED", "INFERRED"}),
    "demonstrated_outcome": frozenset({"VERIFIED", "INFERRED"}),
    "unverified_outcome": frozenset({"UNVERIFIED"}),
    "limitation": frozenset({"DOCUMENTATION_ONLY", "INFERRED"}),
    "unresolved": frozenset({"UNVERIFIED"}),
}
# Which evidence types each artifact may hold.
ARTIFACT_TYPES: dict[str, frozenset[str]] = {
    "problem_statement": frozenset({"author_stated_problem", "unresolved"}),
    "problem_context": frozenset({"inferred_problem_context"}),
    "intended_solution": frozenset({"intended_solution"}),
    "implementation_approach": frozenset({"implemented_solution", "intended_solution"}),
    "architecture": frozenset({"implemented_solution", "unresolved"}),
    "implementation_evidence": frozenset({"implemented_solution"}),
    "demonstrated_outcomes": frozenset({"demonstrated_outcome", "unverified_outcome"}),
    "limitations": frozenset({"limitation"}),
    "unresolved_questions": frozenset({"unresolved"}),
}
ARTIFACTS = tuple(ARTIFACT_TYPES)


class StoryError(Exception):
    """Fixed code only; never repository text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceRef(Closed):
    """One exact citation: a line range of a hash-pinned file and its quoted text."""

    id: ID
    path: str = Field(min_length=1, max_length=400)
    file_sha256: Hash
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=1200)
    permalink: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def ordered(self) -> "EvidenceRef":
        if not 0 <= self.end_line - self.start_line <= 7:
            raise ValueError("evidence range must be 1-8 lines")
        return self


class Claim(Closed):
    """The shared atomic unit of every artifact."""

    id: ID
    text: str = Field(min_length=1, max_length=300)
    evidence_type: EvidenceType
    status: ClaimStatus
    evidence_refs: tuple[EvidenceRef, ...] = Field(max_length=8)
    source_location: str | None
    # Stage 9 claims behind a VERIFIED or INFERRED implementation, outcome or limitation.
    analysis_claim_ids: tuple[ID, ...] = Field(default=(), max_length=16)
    # Implemented-solution claims that corroborate an intended solution.
    supports: tuple[ID, ...] = Field(default=(), max_length=8)
    proof: ProofKind | None = None
    # Architecture IR elements the claim describes, for highlighting and animation.
    component_ids: tuple[str, ...] = Field(default=(), max_length=16)
    connection_ids: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def consistent(self) -> "Claim":
        if self.status not in STATUS_RULES[self.evidence_type]:
            raise ValueError("status not allowed for evidence type")
        if self.evidence_type != "unresolved" and not self.evidence_refs:
            raise ValueError("claim without evidence")
        first = self.evidence_refs[0] if self.evidence_refs else None
        if self.source_location != (f"{first.path}:{first.start_line}" if first else None):
            raise ValueError("source location must name the first citation")
        if (self.proof is not None) != (self.evidence_type == "demonstrated_outcome"):
            raise ValueError("proof kind belongs to demonstrated outcomes only")
        if self.supports and self.evidence_type != "intended_solution":
            raise ValueError("only intended solutions are corroborated")
        if self.evidence_type == "intended_solution" and (
            (self.status == "INFERRED") != bool(self.supports)
        ):
            raise ValueError("an intended solution is INFERRED exactly when code corroborates it")
        if self.status == "VERIFIED" and not self.analysis_claim_ids:
            raise ValueError("VERIFIED requires Stage 9 claims")
        return self


class ProblemStatement(Closed):
    sufficiency: Literal["documented", "insufficient"]
    claims: tuple[Claim, ...] = Field(max_length=12)


class ProblemContext(Closed):
    claims: tuple[Claim, ...] = Field(max_length=12)


class IntendedSolution(Closed):
    claims: tuple[Claim, ...] = Field(max_length=16)


class ImplementationApproach(Closed):
    claims: tuple[Claim, ...] = Field(max_length=16)
    decisions: tuple[Claim, ...] = Field(max_length=8)


class ArchitectureDescription(Closed):
    """Linked to one validated Universal Architecture IR report by digest and element ids."""

    ir_version: Literal["architecture-ir-1.0"] | None
    report_sha256: Hash | None
    explanation: Explanation
    unavailable_reason: str | None = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    architecture_ids: tuple[str, ...] = Field(max_length=3)
    primary: str | None
    view: str | None
    claims: tuple[Claim, ...] = Field(max_length=12)
    workflow: tuple[Claim, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def linked(self) -> "ArchitectureDescription":
        available = self.explanation != "unavailable"
        if available != (self.report_sha256 is not None and self.ir_version is not None):
            raise ValueError("an available architecture names its report")
        if available == (self.unavailable_reason is not None):
            raise ValueError("only an unavailable architecture has a reason")
        if (self.explanation == "supported") != (self.primary is not None):
            raise ValueError("a supported architecture has a primary element")
        if self.primary is not None and self.primary not in self.architecture_ids:
            raise ValueError("primary architecture must be listed")
        if self.workflow and self.primary is None:
            raise ValueError("a workflow needs an architecture")
        return self


class ImplementationEvidence(Closed):
    claims: tuple[Claim, ...] = Field(max_length=16)


class DemonstratedOutcomes(Closed):
    scope: Literal[
        "Test and example assertions are read from source; RepoVox does not run them. They "
        "show behaviour the authors check, not production use or measured performance."
    ] = OUTCOME_SCOPE
    claims: tuple[Claim, ...] = Field(max_length=16)


class Limitations(Closed):
    claims: tuple[Claim, ...] = Field(max_length=16)


class UnresolvedQuestions(Closed):
    claims: tuple[Claim, ...] = Field(max_length=24)


class Mismatch(Closed):
    """A stated intention or claim that the implementation, tests or architecture contradict."""

    id: ID
    kind: MismatchKind
    detail: str = Field(min_length=1, max_length=300)
    stated_claim_ids: tuple[ID, ...] = Field(max_length=8)
    evidence_claim_ids: tuple[ID, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def anchored(self) -> "Mismatch":
        if not self.stated_claim_ids and not self.evidence_claim_ids:
            raise ValueError("a mismatch names the claims it is about")
        return self


class StorySource(Closed):
    path: str = Field(min_length=1, max_length=400)
    file_sha256: Hash
    role: SourceRole


class EngineeringStory(Closed):
    schema_version: Literal["problem-to-solution-1.0"]
    extractor_version: Literal["problem-to-solution-extractor-1.0"]
    repository: str = Field(min_length=1, max_length=200)
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    analysis_sha256: Hash
    sources: tuple[StorySource, ...] = Field(max_length=6000)
    problem_statement: ProblemStatement
    problem_context: ProblemContext
    intended_solution: IntendedSolution
    implementation_approach: ImplementationApproach
    architecture: ArchitectureDescription
    implementation_evidence: ImplementationEvidence
    demonstrated_outcomes: DemonstratedOutcomes
    limitations: Limitations
    unresolved_questions: UnresolvedQuestions
    mismatches: tuple[Mismatch, ...] = Field(max_length=32)
    # Repository lines that read like instructions to a model; never used as claims.
    instruction_like_lines: int = Field(ge=0)

    def grouped(self) -> tuple[tuple[str, tuple[Claim, ...]], ...]:
        """Every claim with the artifact that holds it, in a fixed order."""
        return (
            ("problem_statement", self.problem_statement.claims),
            ("problem_context", self.problem_context.claims),
            ("intended_solution", self.intended_solution.claims),
            (
                "implementation_approach",
                self.implementation_approach.claims + self.implementation_approach.decisions,
            ),
            ("architecture", self.architecture.claims + self.architecture.workflow),
            ("implementation_evidence", self.implementation_evidence.claims),
            ("demonstrated_outcomes", self.demonstrated_outcomes.claims),
            ("limitations", self.limitations.claims),
            ("unresolved_questions", self.unresolved_questions.claims),
        )

    def claims(self) -> dict[str, Claim]:
        return {claim.id: claim for _, group in self.grouped() for claim in group}

    @model_validator(mode="after")
    def coherent(self) -> "EngineeringStory":
        seen: dict[str, Claim] = {}
        refs: set[str] = set()
        for artifact, group in self.grouped():
            for claim in group:
                if claim.evidence_type not in ARTIFACT_TYPES[artifact] or claim.id in seen:
                    raise ValueError("claim misplaced or duplicated")
                seen[claim.id] = claim
                for ref in claim.evidence_refs:
                    if ref.id in refs:
                        raise ValueError("evidence id reused")
                    refs.add(ref.id)
        stated = any(c.evidence_type == "author_stated_problem" for c in seen.values())
        if (self.problem_statement.sufficiency == "documented") != stated:
            raise ValueError("problem sufficiency must follow its evidence")
        if self.problem_statement.sufficiency == "insufficient" and not any(
            c.evidence_type == "unresolved" for c in self.problem_statement.claims
        ):
            raise ValueError("an insufficient problem statement says so explicitly")
        for claim in seen.values():
            for other in claim.supports:
                found = seen.get(other)
                if found is None or found.evidence_type != "implemented_solution":
                    raise ValueError("corroboration must name implemented solutions")
        for mismatch in self.mismatches:
            if not set(mismatch.stated_claim_ids + mismatch.evidence_claim_ids) <= set(seen):
                raise ValueError("mismatch names an unknown claim")
        if len({m.id for m in self.mismatches}) != len(self.mismatches):
            raise ValueError("mismatch id reused")
        if len({s.path for s in self.sources}) != len(self.sources):
            raise ValueError("source listed twice")
        return self


__all__ = [
    "ARTIFACTS",
    "ARTIFACT_TYPES",
    "EXTRACTOR_VERSION",
    "OUTCOME_SCOPE",
    "SCHEMA_VERSION",
    "STATUS_RULES",
    "ArchitectureDescription",
    "Claim",
    "DemonstratedOutcomes",
    "EngineeringStory",
    "EvidenceRef",
    "ImplementationApproach",
    "ImplementationEvidence",
    "IntendedSolution",
    "Limitations",
    "Mismatch",
    "ProblemContext",
    "ProblemStatement",
    "StoryError",
    "StorySource",
    "UnresolvedQuestions",
]

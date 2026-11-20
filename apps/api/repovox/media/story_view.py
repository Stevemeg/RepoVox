"""The public, bounded view of a verified story and its narration, for the video API. Data only.

`StoryView` reuses the verified story's own artifact, claim, citation and mismatch models
(`repovox.media.story`), so the API serves exactly the statuses and evidence types the
verifier assigned. To keep the record bounded, it replaces the per-file source list with
counts per role. It also keeps at most `REFS_PER_CLAIM` citations per claim and clips each
quote to `QUOTE_LIMIT` characters, and `evidence_trimmed` says when either happened. Every
path is repository-relative and every permalink is a public repository URL. No host path,
credential or model text is included.

`NarrationView` describes how the walkthrough was worded and voiced. It covers the template
or the grounded model refiner (ADR-0026), plus the local voice that spoke (ADR-0027).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from repovox.analysis.common import canonical
from repovox.media.story import (
    ArchitectureDescription,
    Claim,
    ClaimStatus,
    DemonstratedOutcomes,
    EngineeringStory,
    ImplementationApproach,
    ImplementationEvidence,
    IntendedSolution,
    Limitations,
    Mismatch,
    ProblemContext,
    ProblemStatement,
    SourceRole,
    UnresolvedQuestions,
)

VIEW_VERSION: Literal["engineering-story-view-1.0"] = "engineering-story-view-1.0"
QUOTE_LIMIT = 240
REFS_PER_CLAIM = 3
VIEW_LIMIT = 512 * 1024  # Serialized bytes; a larger view is not published.
# The wording a client must show for each status. Documentation is never shown as verified.
STATUSES: tuple[ClaimStatus, ...] = ("VERIFIED", "INFERRED", "DOCUMENTATION_ONLY", "UNVERIFIED")
STATUS_LABELS: dict[ClaimStatus, str] = {
    "VERIFIED": "VERIFIED",
    "INFERRED": "INFERRED",
    "DOCUMENTATION_ONLY": "AUTHOR-STATED / NOT VERIFIED BY CODE",
    "UNVERIFIED": "UNVERIFIED",
}
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StoryView(Closed):
    view_version: Literal["engineering-story-view-1.0"]
    schema_version: Literal["problem-to-solution-1.0"]
    extractor_version: Literal["problem-to-solution-extractor-1.0"]
    repository: str = Field(min_length=1, max_length=200)
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    analysis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_counts: dict[SourceRole, int]
    status_counts: dict[ClaimStatus, int]
    status_labels: dict[ClaimStatus, str]
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
    instruction_like_lines: int = Field(ge=0)
    evidence_trimmed: bool

    @model_validator(mode="after")
    def labelled(self) -> "StoryView":
        if self.status_labels != STATUS_LABELS:
            raise ValueError("status labels are fixed")
        return self


class NarrationView(Closed):
    """How the walkthrough was worded and which local voice spoke it. Fixed names only."""

    refiner: Literal["deterministic-template-1.0", "grounded-llm-refiner-1.0"]
    provider: Literal["deterministic", "ollama", "openai_compatible", "anthropic"]
    model: str | None = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")
    blueprint_sha256: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    scenes_total: int = Field(ge=1, le=24)
    scenes_refined: int = Field(ge=0, le=24)
    scenes_fallback: int = Field(ge=0, le=24)
    refined_scene_ids: tuple[str, ...] = Field(max_length=24)
    fallback_reason: Code | None
    rejection_reasons: dict[str, tuple[Code, ...]]
    tts_provider: Literal["deterministic", "kokoro_onnx", "local"] | None
    tts_engine: Name | None
    tts_voice: Name | None

    @model_validator(mode="after")
    def consistent(self) -> "NarrationView":
        grounded = self.refiner == "grounded-llm-refiner-1.0"
        if grounded == (self.provider == "deterministic") or grounded == (self.model is None):
            raise ValueError("a grounded narrator names its provider and model")
        if self.scenes_refined + self.scenes_fallback > self.scenes_total:
            raise ValueError("scene counts are inconsistent")
        return self


def trimmed_claim(claim: Claim) -> tuple[Claim, bool]:
    refs = []
    cut = len(claim.evidence_refs) > REFS_PER_CLAIM
    for ref in claim.evidence_refs[:REFS_PER_CLAIM]:
        if len(ref.quote) > QUOTE_LIMIT:
            ref = ref.model_copy(update={"quote": ref.quote[: QUOTE_LIMIT - 3] + "..."})
            cut = True
        refs.append(ref)
    return claim.model_copy(update={"evidence_refs": tuple(refs)}), cut


def story_view(story: EngineeringStory) -> StoryView | None:
    """The bounded public view, or None if even the bounded view would exceed VIEW_LIMIT."""
    cut = False

    def claims(group: tuple[Claim, ...]) -> tuple[Claim, ...]:
        nonlocal cut
        found = []
        for claim in group:
            trimmed, shortened = trimmed_claim(claim)
            cut = cut or shortened
            found.append(trimmed)
        return tuple(found)

    every = story.claims().values()
    roles = [source.role for source in story.sources]
    approach, architecture = story.implementation_approach, story.architecture
    view = StoryView(
        view_version=VIEW_VERSION,
        schema_version=story.schema_version,
        extractor_version=story.extractor_version,
        repository=story.repository,
        commit_sha=story.commit_sha,
        analysis_sha256=story.analysis_sha256,
        source_counts={role: roles.count(role) for role in sorted(set(roles))},
        status_counts={status: sum(c.status == status for c in every) for status in STATUSES},
        status_labels=STATUS_LABELS,
        problem_statement=story.problem_statement.model_copy(
            update={"claims": claims(story.problem_statement.claims)}
        ),
        problem_context=ProblemContext(claims=claims(story.problem_context.claims)),
        intended_solution=IntendedSolution(claims=claims(story.intended_solution.claims)),
        implementation_approach=ImplementationApproach(
            claims=claims(approach.claims), decisions=claims(approach.decisions)
        ),
        architecture=architecture.model_copy(
            update={
                "claims": claims(architecture.claims),
                "workflow": claims(architecture.workflow),
            }
        ),
        implementation_evidence=ImplementationEvidence(
            claims=claims(story.implementation_evidence.claims)
        ),
        demonstrated_outcomes=story.demonstrated_outcomes.model_copy(
            update={"claims": claims(story.demonstrated_outcomes.claims)}
        ),
        limitations=Limitations(claims=claims(story.limitations.claims)),
        unresolved_questions=UnresolvedQuestions(claims=claims(story.unresolved_questions.claims)),
        mismatches=story.mismatches,
        instruction_like_lines=story.instruction_like_lines,
        evidence_trimmed=False,
    )
    view = view.model_copy(update={"evidence_trimmed": cut})
    if len(canonical(view.model_dump(mode="json"))) > VIEW_LIMIT:
        return None
    return view


__all__ = [
    "QUOTE_LIMIT",
    "REFS_PER_CLAIM",
    "STATUS_LABELS",
    "VIEW_LIMIT",
    "VIEW_VERSION",
    "NarrationView",
    "StoryView",
    "story_view",
]

"""Adaptive problem-to-solution storyboard from a verified engineering story. No inference.

Up to eleven scenes in a fixed order: introduction, problem, context, proposed solution,
development approach, architecture, implementation workflow, technical decisions,
demonstrated results, limitations and conclusion. A scene without evidence is left out
instead of being filled. The introduction, problem, architecture, limitations and conclusion
are always present, and when the problem is not documented the problem scene says exactly
that. Every sentence that states something about the repository cites story claims, and its
uncertainty label is the weakest status among them, so author-stated and unverified material
is always labelled as such.
"""

from typing import Any, cast

from repovox.analysis.common import canonical, digest
from repovox.media.architecture import Report
from repovox.media.refiner import (
    DETERMINISTIC,
    DIAGRAM_TEXT_LIMIT,
    GROUNDED_NARRATOR,
    TEXT_LIMIT,
    NarrativeRefiner,
    PlannedSentence,
    RecordedNarration,
    ScenePlan,
    blueprint_digest,
    refine_all,
    verify_refined_scene,
)
from repovox.media.story import Claim, EngineeringStory, StoryError
from repovox.media.story_extract import TEMPLATES, clip, plural, verify_story
from repovox.media.storyboard import (
    STORY_VERSION,
    GroundingError,
    Row,
    Scene,
    SceneType,
    Sentence,
    StoryAttachment,
    Storyboard,
    Uncertainty,
    display,
    short,
    speakable,
)

SCENES = (
    "introduction",
    "problem",
    "context",
    "solution",
    "approach",
    "architecture",
    "workflow",
    "decisions",
    "results",
    "limitations",
    "conclusion",
)
REQUIRED = {"introduction", "problem", "architecture", "limitations", "conclusion"}
DIAGRAM_SCENES = {"architecture", "workflow"}
RANK = {"UNVERIFIED": 0, "DOCUMENTATION_ONLY": 1, "INFERRED": 2, "VERIFIED": 3}
LABEL: dict[str, Uncertainty] = {
    "UNVERIFIED": "unverified",
    "DOCUMENTATION_ONLY": "documentation",
    "INFERRED": "inferred",
    "VERIFIED": "verified",
}
STATUS_WORD = {
    "UNVERIFIED": "UNVERIFIED",
    "DOCUMENTATION_ONLY": "AUTHOR-STATED",
    "INFERRED": "INFERRED",
    "VERIFIED": "VERIFIED",
}
PROOF = {
    "unit_test": "Unit test, not run",
    "integration_test": "Integration test, not run",
    "benchmark": "Benchmark file, not run",
    "example": "Example program, not run",
}
SCOPE = (
    "RepoVox did not run any test or example. They show behaviour the authors check, not "
    "production use or measured performance."
)
ARCHITECTURE_TITLE = {
    "supported": "Architecture overview",
    "unsupported": "Architecture: not established",
    "unavailable": "Architecture: not described",
}


def uncertainty(claims: list[Claim]) -> Uncertainty:
    if not claims:
        return "none"
    return LABEL[min((c.status for c in claims), key=RANK.__getitem__)]


def where(story: EngineeringStory, claim: Claim) -> str:
    path = claim.evidence_refs[0].path
    role = next((s.role for s in story.sources if s.path == path), "documentation")
    return "The README" if role == "readme" else f"The documentation in {short(path)}"


def rows_of(claims: list[Claim]) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, str]] = []
    for claim in claims:
        if claim.source_location and len(found) < 8:
            found.append((claim.source_location, STATUS_WORD[claim.status]))
    return tuple(dict.fromkeys(found))


def say(text: str, *claims: Claim) -> PlannedSentence:
    return PlannedSentence(text=text, claim_ids=tuple(dict.fromkeys(c.id for c in claims)))


def plan(story: EngineeringStory) -> list[ScenePlan]:
    """What each scene says and which claims it rests on, before any rewording."""
    claims = story.claims()
    roles = {s.role for s in story.sources}
    count = {role: sum(s.role == role for s in story.sources) for role in roles}
    scenes: list[ScenePlan] = []

    def add(
        kind: str,
        title: str,
        sentences: list[PlannedSentence],
        rows: tuple[tuple[str, str], ...] = (),
        diagram: bool = False,
    ) -> None:
        if sentences:
            scenes.append(ScenePlan(kind, kind, title, rows, diagram, tuple(sentences[:6])))

    documents = count.get("readme", 0) + count.get("documentation", 0)
    problem = story.problem_statement
    description = story.architecture
    add(
        "introduction",
        "Engineering story",
        [
            say(
                f"This is the engineering story of {story.repository} at pinned commit "
                f"{story.commit_sha[:12]}."
            ),
            say(
                f"It was built from {plural(documents, 'documentation file')}, "
                f"{plural(count.get('source', 0), 'source file')} and "
                f"{plural(count.get('test', 0), 'test file')}, read as data and never run."
            ),
        ],
        (
            ("Repository", story.repository),
            ("Pinned commit", story.commit_sha[:12]),
            ("Documentation files", str(documents)),
            ("Source files", str(count.get("source", 0) + count.get("example", 0))),
            ("Test files", str(count.get("test", 0))),
            (
                "Problem statement",
                "documented" if problem.sufficiency == "documented" else "not documented",
            ),
            ("Architecture", description.explanation),
        ),
    )
    stated = [c for c in problem.claims if c.evidence_type == "author_stated_problem"]
    if stated:
        lines = [say(f"{where(story, c)} states the problem: {c.text}", c) for c in stated[:4]]
        if len(stated) > 4:
            lines.append(say(f"{plural(len(stated) - 4, 'more problem statement')} documented."))
        add("problem", "The problem", lines, rows_of(stated))
    else:
        add("problem", "The problem", [say(c.text, c) for c in problem.claims[:1]])
    context = list(story.problem_context.claims)
    add(
        "context",
        "Context and motivation",
        [say(f"Background from {where(story, c).lower()}: {c.text}", c) for c in context[:4]],
        rows_of(context),
    )
    intended = list(story.intended_solution.claims)
    solution: list[PlannedSentence] = []
    for claim in intended[:4]:
        backing = [claims[i] for i in claim.supports if i in claims][:1]
        if backing:
            solution.append(
                say(
                    f"The authors state: {claim.text} Matching code: {backing[0].text}",
                    claim,
                    *backing,
                )
            )
        else:
            solution.append(
                say(f"The authors state: {claim.text} No matching code was found.", claim)
            )
    add("solution", "The proposed solution", solution, rows_of(intended))
    approach = list(story.implementation_approach.claims)
    add("approach", "How it was built", [say(c.text, c) for c in approach[:5]], rows_of(approach))
    overview = list(description.claims)
    if description.explanation == "supported":
        add(
            "architecture",
            ARCHITECTURE_TITLE["supported"],
            [
                PlannedSentence(c.text, (c.id,), c.component_ids, c.connection_ids)
                for c in overview[:6]
            ],
            diagram=True,
        )
    else:
        add(
            "architecture",
            ARCHITECTURE_TITLE[description.explanation],
            [say(c.text, c) for c in overview[:2]],
            rows_of(overview),
        )
    workflow = list(description.workflow)
    if workflow:
        add(
            "workflow",
            "Implementation workflow",
            [say("Now the main workflow, one static relationship at a time.")]
            + [
                PlannedSentence(c.text, (c.id,), c.component_ids, c.connection_ids)
                for c in workflow[:5]
            ],
            diagram=True,
        )
    decisions = list(story.implementation_approach.decisions)
    add(
        "decisions",
        "Technical decisions",
        [
            say(
                f"{where(story, c)} records a decision: {c.text}"
                if c.evidence_type == "intended_solution"
                else c.text,
                c,
            )
            for c in decisions[:4]
        ],
        rows_of(decisions),
    )
    outcomes = list(story.demonstrated_outcomes.claims)
    shown = [c for c in outcomes if c.evidence_type == "demonstrated_outcome"][:3]
    claimed = [c for c in outcomes if c.evidence_type == "unverified_outcome"][:2]
    results = [say(f"{PROOF[c.proof or 'unit_test']}: {c.text}", c) for c in shown]
    if shown:
        results.append(say(SCOPE))
    results += [
        say(f"The documentation claims: {c.text} This is not verified.", c) for c in claimed
    ]
    add("results", "Demonstrated results", results, rows_of(shown + claimed))
    limits = list(story.limitations.claims)
    questions = [c for c in story.unresolved_questions.claims if c.text != TEMPLATES["runtime"]]
    runtime = [c for c in story.unresolved_questions.claims if c.text == TEMPLATES["runtime"]]
    closing: list[PlannedSentence] = []
    for claim in limits[:2]:
        prefix = "Documented limitation: " if claim.status == "DOCUMENTATION_ONLY" else ""
        closing.append(say(prefix + claim.text, claim))
    for mismatch in story.mismatches[:2]:
        named = [claims[i] for i in mismatch.stated_claim_ids + mismatch.evidence_claim_ids]
        closing.append(say(f"Mismatch: {mismatch.detail}", *named))
    for claim in questions[: 5 - len(closing)]:
        closing.append(say(f"Open question: {claim.text}", claim))
    closing += [say(c.text, c) for c in runtime[:1]]
    add("limitations", "Limitations and open questions", closing, rows_of(limits + questions))
    tally = {status: sum(c.status == status for c in claims.values()) for status in RANK}
    add(
        "conclusion",
        "Conclusion",
        [
            say(
                f"In total {plural(tally['VERIFIED'], 'claim')} rest on verified code, "
                f"{tally['INFERRED']} are inferred, {tally['DOCUMENTATION_ONLY']} rest on "
                f"documentation alone and {tally['UNVERIFIED']} are unverified."
            ),
            say(
                "The authors document the problem; "
                f"{plural(len(story.mismatches), 'mismatch', 'mismatches')} between their "
                "documentation and the code were recorded."
                if problem.sufficiency == "documented"
                else "The problem this repository solves is not documented, so this story "
                "describes what was built, not why."
            ),
            say("Everything in this video comes from cited source lines at one pinned commit."),
        ],
        (
            ("Verified", str(tally["VERIFIED"])),
            ("Inferred", str(tally["INFERRED"])),
            ("Author-stated only", str(tally["DOCUMENTATION_ONLY"])),
            ("Unverified", str(tally["UNVERIFIED"])),
            ("Mismatches recorded", str(len(story.mismatches))),
        ),
    )
    return scenes


def build_story_board(
    payload: dict[str, Any],
    story: EngineeringStory,
    report: Report | None,
    refiner: NarrativeRefiner = DETERMINISTIC,
) -> Storyboard:
    """Storyboard for a story the caller has already verified with `verify_story`."""
    claims = story.claims()
    knowledge = payload["knowledge"]
    scenes: list[Scene] = []
    plans = plan(story)
    refinement = refine_all(refiner, plans, story)
    for scene in plans:
        texts = refinement.texts.get(scene.id, ())
        if len(texts) != len(scene.sentences):
            raise GroundingError("narration_plan_mismatch")
        limit = DIAGRAM_TEXT_LIMIT if scene.diagram else TEXT_LIMIT
        sentences: list[Sentence] = []
        for n, (planned, raw) in enumerate(zip(scene.sentences, texts, strict=True), 1):
            text = clip(display(raw, 4000), limit)
            cited = [claims[i] for i in planned.claim_ids]
            sentences.append(
                Sentence(
                    id=f"{scene.id}-s{n}",
                    text=text,
                    spoken=speakable(text),
                    technical=bool(cited),
                    uncertainty=uncertainty(cited),
                    claim_ids=planned.claim_ids,
                    evidence_ids=tuple(dict.fromkeys(r.id for c in cited for r in c.evidence_refs)),
                    component_ids=planned.component_ids,
                    connection_ids=planned.connection_ids,
                )
            )
        scenes.append(
            Scene(
                id=scene.id,
                type=cast(SceneType, scene.type),
                title=display(scene.title, 44),
                claim_ids=tuple(dict.fromkeys(c for s in sentences for c in s.claim_ids))[:256],
                evidence_ids=tuple(dict.fromkeys(e for s in sentences for e in s.evidence_ids))[
                    :256
                ],
                rows=tuple(
                    Row(label=display(label, 40), value=display(value, 70))
                    for label, value in scene.rows
                ),
                sentences=tuple(sentences),
                diagram=scene.diagram,
            )
        )
    return Storyboard(
        version=STORY_VERSION,
        repository=display(knowledge["repository"]["repository"], 120),
        commit_sha=knowledge["repository"]["commit_sha"],
        pipeline_version=knowledge["versions"]["pipeline"],
        analysis_sha256=digest(canonical(payload)),
        scenes=tuple(scenes),
        story=StoryAttachment(
            story=story,
            architecture=report,
            narrator=refiner.name,
            narration=refinement.provenance,
        ),
    )


def check_story_board(
    board: Storyboard, payload: dict[str, Any], sources: dict[str, bytes]
) -> None:
    """Independent of the builder: re-verify the story, the scenes and exact reproducibility."""
    attachment = board.story
    if board.version != STORY_VERSION or attachment is None:
        raise GroundingError("invalid_storyboard")
    story, report = attachment.story, attachment.architecture
    try:
        verify_story(story, payload, sources, report)
    except StoryError as error:
        raise GroundingError(error.code) from None
    if board.analysis_sha256 != digest(canonical(payload)):
        raise GroundingError("analysis_mismatch")
    # Only two narrators exist: the template wording, and grounded model wording that carries
    # its provenance and is re-checked claim by claim below.
    if attachment.narrator == DETERMINISTIC.name:
        if attachment.narration is not None:
            raise GroundingError("narration_provenance_invalid")
    elif attachment.narrator == GROUNDED_NARRATOR:
        if attachment.narration is None:
            raise GroundingError("narration_provenance_invalid")
    else:
        raise GroundingError("narrator_unsupported")
    claims = story.claims()
    order = [s.type for s in board.scenes]
    if (
        len(set(order)) != len(order)
        or order != [s for s in SCENES if s in order]
        or not REQUIRED <= set(order)
    ):
        raise GroundingError("story_scene_order")
    primary = None
    if report is not None and story.architecture.primary is not None:
        primary = next(a for a in report.architectures if a.id == story.architecture.primary)
    members: set[str] = set()
    links: set[str] = set()
    if primary is not None:
        view = next((v for v in primary.views if v.id == story.architecture.view), None)
        members = set(view.component_ids) if view else {c.id for c in primary.components}
        links = set(view.connection_ids) if view else {c.id for c in primary.connections}
    for scene in board.scenes:
        if scene.id != scene.type or scene.excerpt is not None or scene.links:
            raise GroundingError("story_scene_invalid")
        if scene.diagram != (scene.type in DIAGRAM_SCENES and primary is not None):
            raise GroundingError("story_scene_invalid")
        for sentence in scene.sentences:
            cited = [claims.get(i) for i in sentence.claim_ids]
            if any(c is None for c in cited):
                raise GroundingError("unverified_claim")
            found = [c for c in cited if c is not None]
            refs = tuple(dict.fromkeys(r.id for c in found for r in c.evidence_refs))
            if sentence.evidence_ids != refs or sentence.technical != bool(found):
                raise GroundingError("invalid_evidence")
            if sentence.uncertainty != uncertainty(found):
                raise GroundingError("uncited_technical_sentence")
            if sentence.spoken != speakable(sentence.text):
                raise GroundingError("speech_text_mismatch")
            if (
                not set(sentence.component_ids) <= members
                or not set(sentence.connection_ids) <= links
            ):
                raise GroundingError("story_scene_invalid")
    if attachment.narration is None:
        if build_story_board(payload, story, report) != board:
            raise GroundingError("storyboard_not_reproducible")
        return
    check_refined_wording(board, payload, story, report)


def check_refined_wording(
    board: Storyboard, payload: dict[str, Any], story: EngineeringStory, report: Report | None
) -> None:
    """A model-worded storyboard: everything but the wording of its refined scenes must be
    exactly the deterministic storyboard, and each refined scene must pass the same grounding
    check the worker applied. No model is called."""
    attachment = board.story
    provenance = attachment.narration if attachment is not None else None
    if provenance is None:
        raise GroundingError("narration_provenance_invalid")
    plans = plan(story)
    ids = {scene.id for scene in plans}
    if (
        provenance.blueprint_sha256 != blueprint_digest(plans, story)
        or provenance.scenes_total != len(plans)
        or not set(provenance.refined_scene_ids) | set(provenance.rejection_reasons) <= ids
    ):
        raise GroundingError("narration_provenance_invalid")
    texts = {scene.id: tuple(s.text for s in scene.sentences) for scene in board.scenes}
    for scene in plans:
        if scene.id not in provenance.refined_scene_ids:
            continue
        if scene.id not in texts or verify_refined_scene(scene, texts[scene.id], story):
            raise GroundingError("narration_not_grounded")
    replay = RecordedNarration(texts, provenance)
    if build_story_board(payload, story, report, replay) != board:
        raise GroundingError("storyboard_not_reproducible")


__all__ = [
    "DIAGRAM_TEXT_LIMIT",
    "SCENES",
    "TEXT_LIMIT",
    "build_story_board",
    "check_refined_wording",
    "check_story_board",
    "plan",
]

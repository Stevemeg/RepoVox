"""Narrative refinement seam between the verified story plan and the storyboard.

The storyboard builder turns a verified `EngineeringStory` into scene plans: each planned
sentence already names the claims it rests on, and its uncertainty label is derived from
those claims' statuses. A refiner may only change how a planned sentence is worded. It cannot
add, drop or reorder sentences, change which claims a sentence cites, or choose a status.

`DeterministicNarrativeRefiner` keeps the planned wording, so a storyboard is exactly
reproducible from its inputs and Stage 11 can rebuild and compare it. A grounded language
model refiner (Milestone 2) plugs in here. Until it has its own claim-level grounding check,
`story_board.check_story_board` refuses any storyboard written by a refiner other than the
deterministic one, so no unchecked wording reaches speech.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PlannedSentence:
    text: str
    claim_ids: tuple[str, ...]
    component_ids: tuple[str, ...] = ()
    connection_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenePlan:
    id: str
    type: str
    title: str
    rows: tuple[tuple[str, str], ...]
    diagram: bool
    sentences: tuple[PlannedSentence, ...]


class NarrativeRefiner(Protocol):
    """Rewords planned sentences. Repository text inside them is untrusted data."""

    name: str

    def refine(self, scene: ScenePlan) -> tuple[str, ...]:
        """Exactly one replacement text per planned sentence, in the same order."""
        ...


class DeterministicNarrativeRefiner:
    """The default: planned template wording, unchanged."""

    name = "deterministic-template-1.0"

    def refine(self, scene: ScenePlan) -> tuple[str, ...]:
        return tuple(sentence.text for sentence in scene.sentences)


DETERMINISTIC = DeterministicNarrativeRefiner()

__all__ = [
    "DETERMINISTIC",
    "DeterministicNarrativeRefiner",
    "NarrativeRefiner",
    "PlannedSentence",
    "ScenePlan",
]

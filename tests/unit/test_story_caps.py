"""The story keeps the schema's artifact caps and cites only claims it publishes.

The extractor once kept 24 implementation-evidence claims where `problem-to-solution-1.0`
allows 16, and let an intended solution cite a corroborating claim that a cap later cut; both
failed with `story_invalid`. Every repository here is locally authored synthetic source.
"""

from pathlib import Path

from repovox.media.story_board import build_story_board, check_story_board
from test_engineering_story import shape

# Eight documented features, each matching two declared functions, plus three source areas:
# more corroborating evidence than the story schema's 16 implementation-evidence claims.
FEATURES = [
    ("Record apple harvest weights.", "record_apple_harvest", "apple_harvest_weights"),
    ("Forecast pear orchard yields.", "forecast_pear_orchard", "pear_orchard_yields"),
    ("Schedule cherry picking crews.", "schedule_cherry_picking", "cherry_picking_crews"),
    ("Track plum irrigation valves.", "track_plum_irrigation", "plum_irrigation_valves"),
    ("Grade peach crate quality.", "grade_peach_crate", "peach_crate_quality"),
    ("Price quince market baskets.", "price_quince_market", "quince_market_baskets"),
    ("Log apricot frost alerts.", "log_apricot_frost", "apricot_frost_alerts"),
    ("Count walnut storage bins.", "count_walnut_storage", "walnut_storage_bins"),
]


def orchard() -> dict[str, str]:
    readme = "# Orchard\n\nOrchard keeps harvest records for small farms.\n\n## Features\n\n"
    readme += "".join(f"- {line}\n" for line, _, _ in FEATURES)
    files = {"README.md": readme}
    for index, (_, first, second) in enumerate(FEATURES):
        area = ("harvest", "planning", "storage")[index % 3]
        body = "".join(
            f"def {name}(rows):\n    return list(rows)\n\n\n" for name in (first, second)
        )
        files[f"{area}/{first}.py"] = body
    return files


def test_story_keeps_the_schema_caps_and_only_cites_published_claims(tmp_path: Path) -> None:
    found = shape(tmp_path, orchard(), "example/orchard")  # extracts and verifies the story
    story = found.story
    assert len(story.implementation_evidence.claims) == 16
    claims = story.claims()
    supports = [s for c in claims.values() for s in c.supports]
    assert supports and all(claims[s].evidence_type == "implemented_solution" for s in supports)
    statuses = [c.status for c in story.intended_solution.claims]
    # Early features are corroborated; a feature whose evidence would fall past the cap is
    # left author-stated instead of citing a claim the story does not publish.
    assert "INFERRED" in statuses and "DOCUMENTATION_ONLY" in statuses
    board = build_story_board(found.payload, story, found.report)
    check_story_board(board, found.payload, found.sources)

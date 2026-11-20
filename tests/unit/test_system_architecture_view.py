"""Whole-repository system architecture view: tiers, cited cross-tier edges, ranking, frames.

Fixtures are locally authored synthetic source (`system_fixtures.py`), parsed as data and never
executed. No model, network or paid service is used.
"""

import json
from pathlib import Path

import pytest
from repovox.media import archgraph, explainer, stages
from repovox.media.architecture import (
    Architecture,
    Citation,
    Component,
    Connection,
    Context,
    validate,
)
from repovox.media.diagram import (
    AREA_BOTTOM,
    AREA_TOP,
    TIER_ORDER,
    Diagram,
    card_label,
    classify,
    fit,
    fit_path,
    tiered,
)
from repovox.media.narration import FPS
from repovox.media.story_board import check_story_board
from repovox.media.system_view import IDENTITY, TYPE, matches, normalised
from system_fixtures import FULL_STACK, LIBRARY
from test_architecture import every_citation
from test_engineering_story import Shape, shape

UI_HELPERS = {"date", "human", "Section", "State", "Empty", "Facts", "Typography"}


@pytest.fixture(scope="module")
def full(tmp_path_factory: pytest.TempPathFactory) -> Shape:
    return shape(tmp_path_factory.mktemp("full"), FULL_STACK, "example/forge")


@pytest.fixture(scope="module")
def library(tmp_path_factory: pytest.TempPathFactory) -> Shape:
    return shape(tmp_path_factory.mktemp("library"), LIBRARY, "example/textkit")


def system_of(shaped: Shape) -> Architecture:
    assert shaped.report is not None
    first = shaped.report.architectures[0]
    assert (first.id, first.type) == (IDENTITY, TYPE)
    return first


def tier(component: Component) -> str:
    return classify(component)[0]


def quoted(citations: tuple[Citation, ...]) -> set[tuple[str, int]]:
    return {(c.path, c.line) for c in citations}


def line_of(shaped: Shape, path: str, needle: str) -> int:
    lines = (shaped.root / path).read_text(encoding="utf-8").split("\n")
    return next(i for i, text in enumerate(lines, 1) if needle in text)


def changed(a: bytes, b: bytes) -> bool:
    return a != b and a.startswith(b"\x89PNG\r\n\x1a\n") and b.startswith(b"\x89PNG\r\n\x1a\n")


# ------------------------------------------------------------- 1. subsystems, tiers, edges


def test_full_stack_map_spans_every_tier_with_cited_cross_tier_edges(full: Shape) -> None:
    assert full.report is not None
    validate(full.report, full.payload, full.sources)  # Evidence and exact reproducibility.
    system = system_of(full)
    tiers = {tier(c) for c in system.components}
    assert tiers == {"client", "api", "service", "platform"}
    roles = {c.label: c.role for c in system.components if c.kind.endswith("_subsystem")}
    assert roles["routes"] == "api" and roles["ml"] == "ml" and roles["db"] == "data"
    # Subsystems are directories, never single UI helpers.
    assert not {c.label for c in system.components} & UI_HELPERS
    assert all(c.kind.endswith("_subsystem") or c.group == "external" for c in system.components)
    verified = {
        v["claim_id"] for v in full.payload["verification"]["verdicts"] if v["status"] == "verified"
    }
    for citation in every_citation(system):
        text = full.sources[citation.path].decode().split("\n")[citation.line - 1]
        assert text.strip() == citation.quote and set(citation.claim_ids) <= verified
    parts = {c.id: c for c in system.components}

    def edge(kind: str, source: str, target: str) -> Connection:
        return next(
            c
            for c in system.connections
            if c.kind == kind and (tier(parts[c.source]), tier(parts[c.target])) == (source, target)
        )

    # Client -> API: a request path matched to a declared route, cited on both sides.
    request = edge("http_request", "client", "api")
    assert (request.basis, request.status) == ("literal_match", "INFERRED")
    page = "frontend/src/features/runs/RunPage.tsx"
    routes = "backend/app/api/routes/runs.py"
    assert {
        (page, line_of(full, page, "api.post(`/api/v1/runs/")),
        (routes, line_of(full, routes, '@router.post("/runs/{run_id}/start")')),
        (routes, line_of(full, routes, 'APIRouter(prefix="/api/v1"')),
    } <= quoted(request.citations)
    # API -> core services -> ML and data: resolved imports, verified, on the import lines.
    down = edge("imports", "api", "service")
    service = "backend/app/services/runs/service.py"
    assert down.status == "VERIFIED" and quoted(down.citations) == {
        (routes, line_of(full, routes, "import RunService"))
    }
    model = next(
        c for c in system.connections if c.kind == "imports" and parts[c.target].role == "ml"
    )
    assert model.status == "VERIFIED" and quoted(model.citations) == {
        (service, line_of(full, service, "import train_model"))
    }
    assert "imports train_model" in model.label
    database = edge("uses", "platform", "platform")
    assert parts[database.target].kind == "database"
    # The narrated path crosses every tier in order, each step cited.
    flow = system.flows[0]
    assert flow.name == "cross tier flow"
    ranks = [TIER_ORDER.index(tier(parts[s.component_ids[0]])) for s in flow.steps]
    ranks.append(TIER_ORDER.index(tier(parts[flow.steps[-1].component_ids[1]])))
    assert ranks == sorted(ranks) and len(set(ranks)) == 4
    assert all(s.citations for s in flow.steps)


def test_fastapi_router_routes_carry_their_literal_prefix(full: Shape) -> None:
    assert full.report is not None
    repo = archgraph.Repo(Context(full.payload, full.sources))
    declared = archgraph.routes(repo)
    path = "backend/app/api/routes/runs.py"
    found = {(r.method, r.path, r.label) for r in declared[path]}
    assert found == {
        ("POST", "/api/v1/runs/{run_id}/start", "POST /runs/{run_id}/start"),
        ("GET", "/api/v1/runs/{run_id}", "GET /runs/{run_id}"),
    }
    # A multi-line decorator is cited on the decorator, the path line and the prefix line.
    read = next(r for r in declared[path] if r.method == "GET")
    assert [n for _, n in read.cited] == [13, 14, 5]
    assert read.anchors == ("/runs/{run_id}", "/api/v1")


def test_a_router_name_bound_twice_or_not_from_fastapi_is_not_a_router(tmp_path: Path) -> None:
    files = dict(FULL_STACK)
    files["backend/app/api/routes/runs.py"] = files["backend/app/api/routes/runs.py"].replace(
        'router = APIRouter(prefix="/api/v1", tags=["Runs"])\n',
        'router = APIRouter(prefix="/api/v1", tags=["Runs"])\nrouter = make_router()\n',
    )
    shaped = shape(tmp_path, files, "example/forge")
    repo = archgraph.Repo(Context(shaped.payload, shaped.sources))
    assert "backend/app/api/routes/runs.py" not in archgraph.routes(repo)


def test_request_paths_match_route_tails_with_parameters() -> None:
    route = normalised("/api/v1/runs/{run_id}/start")
    assert matches(normalised("/api/v1/runs/${runId}/start"), route)
    assert matches(normalised("https-base/api/v1/runs/7/start?x=1"), route)
    assert not matches(normalised("/runs/${id}/start"), route)  # Shorter than the route.
    assert not matches(normalised("/api/v1/${kind}/7/start"), route)  # Parameter vs literal.
    assert not matches(normalised("/api/v1/users"), normalised("/{}"))  # Only parameters.


# ------------------------------------------------------------------------- 2. ranking


def test_backend_workflow_ranks_ahead_of_ui_formatting_pages(full: Shape) -> None:
    assert full.report is not None
    kinds = [a.type for a in full.report.architectures]
    assert kinds[0] == TYPE and kinds[1] == "service"
    page = next(a for a in full.report.architectures if a.type == "component_graph")
    service = full.report.architectures[1]
    assert page.title.startswith("Dashboard()")
    assert {"date", "human"} <= {c.label for c in page.components}
    assert archgraph.workflow_score(page) < archgraph.workflow_score(service)
    position = full.report.architectures.index
    assert position(service) < position(page)
    # The second video reaches past the route into core services and model code.
    tiers = {tier(c) for c in service.components}
    assert {"api", "service", "platform"} <= tiers
    labels = {c.label for c in service.components}
    assert {"start_run", "RunService", "train_model"} <= labels


def test_titles_keep_the_end_of_their_path() -> None:
    long = "frontend/src/features/evaluation/EvaluationDetail.tsx"
    title = archgraph.titled("EvaluationDetail() in ", long)
    assert title == "EvaluationDetail() in EvaluationDetail.tsx"  # Whole segments only.
    assert archgraph.titled("RunPage() in ", long.replace("EvaluationDetail", "Run")) == (
        "RunPage() in src/features/evaluation/Run.tsx"
    )
    assert archgraph.titled("HTTP service in ", "a/" * 40 + "x.py").endswith("/x.py")


# -------------------------------------------------------------- 3. frames and narration


def test_system_frames_show_tiers_unclipped_and_packets_move(full: Shape) -> None:
    assert full.report is not None
    system = system_of(full)
    view = system.views[0]
    diagram = Diagram(system, full.report.repository, full.report.commit_sha, view)
    assert [t for t, _ in diagram.bands] == ["client", "api", "service", "platform"]
    assert fit(diagram.title, 1200, 3) == diagram.title  # The main title is never cut.
    shown = [fit_path(label, area[2] - 20) for label, area in diagram.lanes]
    assert not any(text.endswith("...") for text in shown)
    assert len(set(shown)) == len({label for label, _ in diagram.lanes})
    for component in diagram.components:
        x, y, w, h = diagram.boxes[component.id]
        assert card_label(component, w - 18) == component.label  # No clipped card names.
        assert AREA_TOP <= y and y + h <= AREA_BOTTOM
    step = system.flows[0].steps[0]
    images = stages.diagram_frames(
        diagram,
        step.component_ids,
        step.connection_ids,
        step.status,
        step.text,
        step.citations[0],
        0,
        5,
        FPS * 4,
        mode="flow",
        step=(1, len(system.flows[0].steps)),
    )
    assert len(images) == stages.animation_count(FPS * 4)
    assert sum(changed(a, b) for a, b in zip(images, images[1:], strict=False)) >= len(images) - 2
    reveal = stages.diagram_frames(
        diagram, tuple(view.component_ids), (), "VERIFIED", "x", None, 0, 5, FPS * 6, mode="reveal"
    )
    assert len(reveal) == (len(diagram.bands) - 1) * stages.REVEAL_STEPS + 1


def test_a_dense_tier_wraps_its_containers_onto_two_rows() -> None:
    citation = Citation(
        path="frontend/src/features/a/x.tsx",
        file_sha256="a" * 64,
        line=1,
        quote="x",
        claim_ids=("claim-1",),
        permalink="https://github.com/example/demo/blob/" + "a" * 40 + "/x#L1-L1",
    )
    cards = [
        Component(
            id=f"c{n}",
            role="client",
            kind="client_subsystem",
            label=f"feature{n}",
            status="VERIFIED",
            anchors=("x",),
            citations=(citation,),
            group=f"frontend/src/features/area{n}",
        )
        for n in range(6)
    ]
    found = tiered(cards, [])
    assert found is not None
    _, lanes, bands = found
    rows = {area[1] for _, area in lanes}
    assert len(bands) == 1 and len(rows) == 2  # Six containers: two rows, never crushed.
    names = [fit_path(label, area[2] - 20) for label, area in lanes]
    assert len(set(names)) == 6 and not any(n.startswith("frontend...") for n in names)


def test_system_narration_discloses_binding_once_and_names_each_tier(full: Shape) -> None:
    system = system_of(full)
    lines = explainer.narrate(system)
    explainer.check_narration(lines, system)
    texts = [line.text for line in lines]
    assert texts.count(explainer.DISCLOSURE) == 1
    assert not any("binding is inferred, not confirmed" in t for t in texts)
    for word in ("client", "API", "core services", "ML and data"):
        assert any(t.startswith(f"The {word} tier holds") for t in texts)
    flow = [line for line in lines if line.section == "flow" and line.connection_ids]
    assert len(flow) == len(system.flows[0].steps) and all(line.citations for line in flow)
    # Component graphs also say the binding status once, not once per card.
    assert full.report is not None
    page = next(a for a in full.report.architectures if a.type == "component_graph")
    page_lines = [line.text for line in explainer.narrate(page)]
    assert page_lines.count(explainer.DISCLOSURE) <= 1
    assert not any("binding is inferred, not confirmed" in t for t in page_lines)


# ------------------------------------------------------------- 4. one-tier repositories


def test_a_pure_python_library_keeps_its_one_tier(library: Shape) -> None:
    assert library.report is not None
    validate(library.report, library.payload, library.sources)
    system = system_of(library)
    assert {tier(c) for c in system.components} == {"service"}
    assert system.title == "System architecture across 1 tier"
    assert {c.label for c in system.components} == {"core", "io", "text", "report"}
    assert system.flows[0].name == "dependency flow"
    diagram = Diagram(system, "example/textkit", "a" * 40, system.views[0])
    assert [t for t, _ in diagram.bands] == ["service"]  # No empty tier is drawn.
    lines = explainer.narrate(system)
    explainer.check_narration(lines, system)
    assert "in 1 tier," in lines[0].text


def test_a_small_repository_keeps_the_file_level_overview(tmp_path: Path) -> None:
    files = {
        k: v
        for k, v in FULL_STACK.items()
        if k.startswith("backend/app/") and "/ml/" not in k and not k.endswith("__init__.py")
    }
    assert len(files) <= archgraph.OVERVIEW_FILES
    shaped = shape(tmp_path, files, "example/forge")
    assert shaped.report is not None
    assert all(a.type != TYPE for a in shaped.report.architectures)


# -------------------------------------------------------------- 5. Stage 10 and Stage 11


def test_walkthrough_story_uses_the_system_map_and_passes_every_check(full: Shape) -> None:
    assert full.story is not None and full.report is not None
    assert (full.story.architecture.primary, full.story.architecture.view) == (IDENTITY, "overview")
    storyboard = stages.storyboard_stage(full.payload, full.story, full.report)  # Stage 10
    script = stages.narration_stage(full.payload, storyboard, full.sources)  # Stage 11
    board = stages.load_board(storyboard)
    check_story_board(board, full.payload, full.sources)
    scenes = {scene.type: scene for scene in board.scenes}
    architecture, workflow = scenes["architecture"], scenes["workflow"]
    assert architecture.diagram and workflow.diagram
    tier_lines = [s.text for s in architecture.sentences if " tier holds " in s.text]
    assert len(tier_lines) == 4  # One sentence per tier, each spotlighting its subsystems.
    assert all(s.claim_ids for s in architecture.sentences)
    system = system_of(full)
    steps = {s.connection_ids for s in system.flows[0].steps}
    assert any(s.connection_ids in steps for s in workflow.sentences)
    assert len(json.loads(script)) == sum(len(s.sentences) for s in board.scenes)
    diagram = stages.story_diagram(board)
    assert diagram is not None and diagram.architecture.type == TYPE

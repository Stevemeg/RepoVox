"""Architecture-agnostic extraction, validation, layout, narration and video tests.

Every family below goes through the same generic graph extractor, the same renderer and the
same narrator. None of them has a dedicated detector or layout. Fixtures are locally authored
synthetic source, parsed as data and never executed.
"""

import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from repovox.media import archgraph, explainer, jsflow
from repovox.media.architecture import (
    Architecture,
    ArchitectureError,
    Component,
    Connection,
    Context,
    Report,
    check,
    discover,
    validate,
)
from repovox.media.diagram import Diagram
from repovox.media.local import analyze_with_sources
from repovox.media.narration import FPS
from repovox.media.pyflow import SourceFile
from repovox.media.raster import HEIGHT, WIDTH
from repovox.media.speech import natural
from test_architecture import (
    FIXTURES,
    analyzed,
    every_citation,
    git,
    gray_frame,
    media_tools,
    repository_from,
)

Loaded = tuple[dict[str, Any], dict[str, bytes], Report]
FAMILIES = [
    "cnn_model",
    "custom_unnamed",
    "data_pipeline",
    "express_service",
    "fullstack_typescript",
    "fullstack_web",
    "microservices",
    "multi_agent",
    "rag_pipeline",
    "react_frontend",
    "transformer_model",
    "typescript_pipeline",
]
NAMED = re.compile(r"(?i)\b(gan|rag|transformer|attention|agent|cnn|microservice|pipeline)\b")


def load(root: Path) -> Loaded:
    payload, sources = analyzed(root)
    return payload, sources, discover(payload, sources)


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Loaded]:
    result: dict[str, Loaded] = {}
    for name in [*FAMILIES, "tech_mention_only"]:
        root = tmp_path_factory.mktemp(name) / "source"
        shutil.copytree(FIXTURES / name, root)
        result[name] = load(root)
    return result


def written(root: Path, files: dict[str, str]) -> Path:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
    return root


def by_type(report: Report, kind: str) -> list[Architecture]:
    return [a for a in report.architectures if a.type == kind]


def labels(architecture: Architecture) -> dict[str, Component]:
    return {c.label: c for c in architecture.components if c.parent is None}


def edges(architecture: Architecture) -> set[tuple[str, str, str]]:
    names = {c.id: c.label for c in architecture.components}
    return {(names[c.source], c.kind, names[c.target]) for c in architecture.connections}


@pytest.mark.parametrize("family", FAMILIES)
def test_every_family_uses_the_same_engine(loaded: dict[str, Loaded], family: str) -> None:
    payload, sources, report = loaded[family]
    validate(report, payload, sources)
    assert report.explanation == "supported" and report.rejected == ()
    verified = {
        v["claim_id"] for v in payload["verification"]["verdicts"] if v["status"] == "verified"
    }
    for architecture in report.architectures:
        assert architecture.type in {"component_graph", "service", "system_overview"}
        assert architecture.views and architecture.views[0].id == "overview"
        for citation in every_citation(architecture):
            lines = sources[citation.path].decode().split("\n")
            assert lines[citation.line - 1].strip() == citation.quote
            assert citation.claim_ids and set(citation.claim_ids) <= verified
        lines_ = explainer.narrate(architecture)
        explainer.check_narration(lines_, architecture)
        assert [x for x in lines_ if x.connection_ids], "narration must animate relationships"
        assert all(x.citations for x in lines_ if x.status in {"VERIFIED", "INFERRED"})
        for view in architecture.views:
            diagram = Diagram(architecture, "example/demo", "a" * 40, view)
            assert set(diagram.boxes) == set(view.component_ids)
            assert set(diagram.routes) == set(view.connection_ids)
            placed = list(diagram.boxes.values())
            for i, (ax, ay, aw, ah) in enumerate(placed):
                assert 0 <= ax and ax + aw <= WIDTH and 120 <= ay and ay + ah <= 548
                for bx, by, bw, bh in placed[i + 1 :]:
                    assert ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay
            for line in (x for x in lines_ if x.view == view.id):
                diagram.base(
                    line.component_ids,
                    line.connection_ids,
                    line.status,
                    line.text,
                    line.citations[0] if line.citations else None,
                    0,
                    1,
                )
        # No connection is stronger than the components it joins.
        status = {c.id: c.status for c in architecture.components}
        for connection in architecture.connections:
            if "INFERRED" in (status[connection.source], status[connection.target]):
                assert connection.status == "INFERRED"
            if connection.basis in {"declared_route", "literal_match"}:
                assert connection.status == "INFERRED"


def test_engine_has_no_named_architecture_logic(loaded: dict[str, Loaded]) -> None:
    source = inspect.getsource(archgraph)
    code = "\n".join(line.split("#")[0] for line in source.split("\n") if '"""' not in line)
    assert not re.search(r"(?i)\b(gan|rag|transformer|attention|agent|cnn)\b", code)
    custom = by_type(loaded["custom_unnamed"][2], "component_graph")[0]
    spoken = " ".join(line.text for line in explainer.narrate(custom))
    assert not NAMED.search(spoken)
    assert "What the code is for is not inferred" in spoken


def test_custom_unnamed_architecture_is_reconstructed(loaded: dict[str, Loaded]) -> None:
    payload, sources, report = loaded["custom_unnamed"]
    (graph,) = report.architectures
    assert (graph.type, graph.status, graph.title) == (
        "component_graph",
        "VERIFIED",
        "cycle() in cycle.py",
    )
    assert graph.scope == ("cycle.py", "gauge.py", "works.py")
    parts = labels(graph)
    assert set(parts) == {"Sluice", "Basin", "Gauge", "ration", "surge", "quota", "result"}
    assert (parts["Sluice"].kind, parts["Sluice"].group) == ("class", "works.py")
    assert (parts["ration"].kind, parts["ration"].group) == ("function", "gauge.py")
    assert edges(graph) == {
        ("surge", "data", "Sluice"),
        ("Sluice", "data", "Basin"),
        ("Basin", "data", "Gauge"),
        ("Gauge", "data", "ration"),
        ("quota", "data", "ration"),
        ("ration", "data", "result"),
    }
    assert all(c.basis == "static_data_flow" for c in graph.connections)
    assert [step.text for step in graph.flows[0].steps][1] == (
        "The value from Sluice, held in flow, is passed to Basin."
    )
    assert "runtime behavior" in {u.topic for u in graph.unresolved}
    lanes = [label for label, _ in Diagram(graph, "r/r", "a" * 40, graph.views[0]).lanes]
    assert lanes == ["works.py", "gauge.py", "cycle.py"]  # Boundaries drawn as lanes.


def test_structurally_different_families(loaded: dict[str, Loaded]) -> None:
    rag = by_type(loaded["rag_pipeline"][2], "component_graph")[0]
    assert rag.status == "INFERRED"
    assert {
        ("embed", "data", "VectorStore"),
        ("VectorStore", "data", "build_prompt"),
        ("build_prompt", "data", "LocalModel"),
        ("VectorStore", "wires", "index"),
        ("LocalModel", "data", "result"),
    } <= edges(rag)
    assert [v.id for v in rag.views] == ["overview", "inside-index"]
    assert "binding strength" in {u.topic for u in rag.unresolved}

    encoder = by_type(loaded["transformer_model"][2], "component_graph")[0]
    assert (encoder.title, encoder.status) == ("Encoder.forward() in attention.py", "VERIFIED")
    assert {
        ("tokens", "data", "embed"),
        ("embed", "data", "block1"),
        ("block1", "data", "block2"),
        ("block2", "data", "head"),
    } <= edges(encoder)
    zoom = encoder.views[1]
    children = {c.label: c for c in encoder.components if c.parent == zoom.parent}
    assert zoom.title == "Inside Block.forward"
    assert {"attention", "norm1", "feed", "norm2"} <= set(children)
    assert children["attention"].lines == ("SelfAttention",)
    assert len(loaded["transformer_model"][2].architectures) == 1  # Inner blocks are zooms.

    team = by_type(loaded["multi_agent"][2], "component_graph")[0]
    assert {
        ("Memory", "wires", "Researcher"),
        ("Researcher", "data", "Memory"),
        ("Planner", "data", "Researcher"),
        ("Researcher", "data", "Writer"),
        ("Writer", "data", "Critic"),
    } <= edges(team)

    etl = by_type(loaded["data_pipeline"][2], "component_graph")[0]
    assert {
        ("extract", "data", "clean"),
        ("clean", "data", "aggregate"),
        ("aggregate", "data", "load"),
        ("load", "uses", "sqlite3"),
    } <= edges(etl)
    assert (labels(etl)["sqlite3"].kind, labels(etl)["sqlite3"].group) == ("database", "external")

    vision = by_type(loaded["cnn_model"][2], "component_graph")[0]
    assert {
        ("images", "data", "conv1"),
        ("conv1", "data", "pool"),
        ("pool", "data", "conv2"),
        ("conv2", "data", "flatten"),
        ("flatten", "data", "head"),
    } <= edges(vision)
    assert labels(vision)["conv1"].lines == ("nn.Conv2d",)


def test_multi_subsystem_repositories_get_an_overview_and_details(
    loaded: dict[str, Loaded],
) -> None:
    web = loaded["fullstack_web"][2]
    assert [a.type for a in web.architectures] == ["system_overview", "service"]
    overview, service = web.architectures
    assert {
        ("page.ts", "imports", "api.ts"),
        ("app.py", "imports", "repository.py"),
        ("api.ts", "http_request", "app.py"),
        ("repository.py", "uses", "sqlite3"),
    } <= edges(overview)
    request = next(c for c in overview.connections if c.kind == "http_request")
    assert (request.basis, request.status) == ("literal_match", "INFERRED")
    assert {c.path for c in request.citations} == {"frontend/api.ts", "backend/app.py"}
    assert "Whether a request reaches it at runtime is not established" in " ".join(
        step.text for step in overview.flows[0].steps
    )
    assert {"backend", "frontend", "external"} == {c.group for c in overview.components}
    assert {
        ("GET /items", "routes", "read_items"),
        ("POST /items", "routes", "create_item"),
        ("read_items", "calls", "list_items"),
        ("create_item", "calls", "add_item"),
        ("list_items", "uses", "sqlite3"),
    } <= edges(service)
    assert all(
        (c.basis, c.status) == ("declared_route", "INFERRED")
        for c in service.connections
        if c.kind == "routes"
    )

    micro = loaded["microservices"][2]
    assert [a.type for a in micro.architectures] == ["system_overview", "service", "service"]
    assert {
        ("client.py", "http_request", "service.py"),
        ("stock.py", "uses", "redis"),
        ("client.py", "uses", "requests"),
    } <= edges(micro.architectures[0])
    kinds = {c.label: c.kind for c in micro.architectures[0].components}
    assert (kinds["redis"], kinds["requests"]) == ("cache", "http_client")
    assert {a.title for a in micro.architectures[1:]} == {
        "HTTP service in inventory/service.py",
        "HTTP service in orders/service.py",
    }


def test_previously_unseen_structure_needs_no_new_code(tmp_path: Path) -> None:
    root = written(
        tmp_path / "source",
        {
            "malt.py": "def mash(grain, water):\n    return grain + water\n",
            "vat.py": (
                "class Vat:\n    def ferment(self, wort, yeast):\n        return wort\n\n\n"
                "def chill(batch):\n    return batch\n"
            ),
            "brew.py": (
                "from malt import mash\nfrom vat import Vat, chill\n\n\n"
                "def brew(grain, water, yeast):\n"
                "    wort = mash(grain, water)\n"
                "    vat = Vat()\n"
                "    young = vat.ferment(wort, yeast)\n"
                "    return chill(young)\n"
            ),
        },
    )
    payload, sources, report = load(root)
    validate(report, payload, sources)
    (graph,) = report.architectures
    assert graph.status == "VERIFIED" and graph.title == "brew() in brew.py"
    assert edges(graph) == {
        ("grain", "data", "mash"),
        ("water", "data", "mash"),
        ("mash", "data", "Vat"),
        ("yeast", "data", "Vat"),
        ("Vat", "data", "chill"),
        ("chill", "data", "result"),
    }
    lines = explainer.narrate(graph)
    explainer.check_narration(lines, graph)
    assert "The value from mash, held in wort, is passed to Vat." in [x.text for x in lines]


def test_partial_architecture_shows_only_what_is_supported(tmp_path: Path) -> None:
    body = (
        "def gather(source):\n    return source\n\n\n"
        "def shape(rows):\n    return rows\n\n\n"
        "def store(rows):\n    return rows\n\n\n"
        "def run(source, publish):\n"
        "    rows = gather(source)\n"
        "    shaped = shape(rows)\n"
        "    kept = store(shaped)\n"
        "    notify(kept)\n"
        "    return publish(kept)\n"
    )
    payload, sources, report = load(written(tmp_path / "partial", {"job.py": body}))
    (graph,) = report.architectures
    assert {"gather", "shape", "store"} <= set(labels(graph))
    assert not {"notify", "publish"} & set(labels(graph))  # Unbound callees are never drawn.
    # The function returns the result of an unbound call on that value: derived, not direct.
    returned = next(c for c in graph.connections if c.id.endswith("-data-result"))
    assert returned.status == "INFERRED"
    assert "through an intermediate expression" in graph.flows[0].steps[-1].text
    unbound = next(u for u in graph.unresolved if u.topic == "unbound calls")
    assert "notify" in unbound.reason
    thin = "def one(x):\n    return x\n\n\ndef run(x):\n    return one(x)\n"
    _, _, small = load(written(tmp_path / "thin", {"job.py": thin}))
    assert small.explanation == "unsupported" and small.architectures == ()
    assert [(r.candidate, r.reason) for r in small.rejected] == [
        ("architecture", "insufficient_structure")
    ]


def test_technology_mentions_alone_produce_no_architecture(
    loaded: dict[str, Loaded], tmp_path: Path
) -> None:
    payload, sources, report = loaded["tech_mention_only"]
    validate(report, payload, sources)
    assert report.explanation == "unsupported" and report.architectures == ()
    (rejected,) = report.rejected
    assert (rejected.candidate, rejected.reason) == (
        "architecture",
        "mention_without_implementation",
    )
    assert {"README.md", "notes.py"} <= {m.path for m in rejected.mentions}
    manifest = explainer.explain(report, payload, sources, tmp_path / "architecture")
    assert manifest["architectures"] == []
    assert not list((tmp_path / "architecture").rglob("*.mp4"))


def rebuilt(report: Report, architecture: Architecture) -> Report:
    others = tuple(a for a in report.architectures if a.id != architecture.id)
    return report.model_copy(update={"architectures": (architecture, *others)})


def test_forged_graph_elements_and_runtime_claims_are_rejected(
    loaded: dict[str, Loaded],
) -> None:
    payload, sources, report = loaded["custom_unnamed"]
    (graph,) = report.architectures
    ids = {c.label: c.id for c in graph.components}
    link = graph.connections[0]
    part = graph.components[0]

    def with_link(**changes: Any) -> Architecture:
        return graph.model_copy(
            update={"connections": (link.model_copy(update=changes), *graph.connections[1:])}
        )

    def with_part(**changes: Any) -> Architecture:
        return graph.model_copy(
            update={"components": (part.model_copy(update=changes), *graph.components[1:])}
        )

    false_link = Connection(
        id="gauge-data-sluice",
        source=ids["Gauge"],
        target=ids["Sluice"],
        kind="data",
        label="value passed",
        phase="structure",
        basis="static_data_flow",
        status="VERIFIED",
        anchors=("sluice.admit", "reading"),
        citations=link.citations,
    )
    forged = Component(
        id="reservoir",
        role="class",
        kind="class",
        label="Reservoir",
        status="VERIFIED",
        anchors=("class Reservoir",),
        citations=part.citations,
        group="works.py",
    )
    quote = part.citations[0]
    cases = {
        "unsupported_element": [
            graph.model_copy(update={"connections": (*graph.connections, false_link)}),
            graph.model_copy(update={"components": (*graph.components, forged)}),
        ],
        "false_citation": [
            with_part(citations=(quote.model_copy(update={"quote": "class Sluice(Dam):"}),)),
            with_part(citations=(quote.model_copy(update={"file_sha256": "f" * 64}),)),
        ],
        "unverified_claim": [
            with_part(citations=(quote.model_copy(update={"claim_ids": ("claim-none",)}),)),
        ],
        "unsupported_connection": [with_link(target="missing"), with_link(target=link.source)],
        "unsupported_hierarchy": [with_part(parent="nowhere")],
        "unsupported_view": [
            graph.model_copy(
                update={
                    "views": (
                        graph.views[0].model_copy(
                            update={"component_ids": (*graph.views[0].component_ids, "ghost")}
                        ),
                    )
                }
            ),
            graph.model_copy(update={"views": (graph.views[0].model_copy(update={"id": "x"}),)}),
        ],
    }
    for code, candidates in cases.items():
        for candidate in candidates:
            with pytest.raises(ArchitectureError) as raised:
                check(rebuilt(report, candidate), payload, sources)
            assert raised.value.code == code, code
    # The IR has no way to say something was observed at runtime.
    with pytest.raises(ValidationError):
        link.model_copy(update={"basis": "observed_runtime"}).model_validate(
            {**link.model_dump(), "basis": "observed_runtime"}
        )
    web_payload, web_sources, web = loaded["fullstack_web"]
    for architecture in web.architectures:
        for connection in architecture.connections:
            if connection.basis in {"declared_route", "literal_match"}:
                promoted = architecture.model_copy(
                    update={
                        "connections": tuple(
                            c.model_copy(update={"status": "VERIFIED"})
                            if c.id == connection.id
                            else c
                            for c in architecture.connections
                        )
                    }
                )
                with pytest.raises(ArchitectureError) as raised:
                    check(rebuilt(web, promoted), web_payload, web_sources)
                assert raised.value.code == "unsupported_runtime_claim"
    lines = explainer.narrate(graph)
    moving = next(i for i, line in enumerate(lines) if line.connection_ids)
    claim = "At runtime Sluice sends every surge to Basin."
    altered = (
        *lines[:moving],
        lines[moving].model_copy(update={"text": claim, "spoken": natural(claim, {})}),
        *lines[moving + 1 :],
    )
    with pytest.raises(ArchitectureError) as raised:
        explainer.check_narration(altered, graph)
    assert raised.value.code == "narration_not_reproducible"
    outside = (lines[0].model_copy(update={"view": "inside-nothing"}), *lines[1:])
    with pytest.raises(ArchitectureError) as raised:
        explainer.check_narration(outside, graph)
    assert raised.value.code == "narration_unsupported_element"


def test_graph_follows_the_pinned_commit(tmp_path: Path) -> None:
    repository = repository_from("custom_unnamed", tmp_path / "repository")
    url = "https://github.com/example/tide-fixture"
    first = git(repository, "rev-parse", "HEAD")
    works = repository / "works.py"
    works.write_bytes(
        works.read_bytes() + b"\n\nclass Weir:\n    def skim(self, flow):\n        return flow\n"
    )
    cycle = repository / "cycle.py"
    body = cycle.read_bytes().replace(
        b"from works import Basin, Sluice", b"from works import Basin, Sluice, Weir"
    )
    body = body.replace(
        b"    level = basin.settle(flow)\n",
        b"    weir = Weir()\n    skimmed = weir.skim(flow)\n    level = basin.settle(skimmed)\n",
    )
    cycle.write_bytes(body)
    git(repository, "commit", "-q", "-am", "add a stage")
    second = git(repository, "rev-parse", "HEAD")
    old_payload, old_sources = analyze_with_sources(repository, url, first)
    new_payload, new_sources = analyze_with_sources(repository, url, second)
    old, new = discover(old_payload, old_sources), discover(new_payload, new_sources)
    assert ("Sluice", "data", "Basin") in edges(old.architectures[0])
    assert ("Sluice", "data", "Basin") not in edges(new.architectures[0])
    assert {("Sluice", "data", "Weir"), ("Weir", "data", "Basin")} <= edges(new.architectures[0])
    assert all(f"/blob/{second}/" in c.permalink for c in every_citation(new.architectures[0]))
    with pytest.raises(ArchitectureError) as raised:
        check(old, new_payload, new_sources)
    assert raised.value.code == "analysis_mismatch"
    relabelled = old.model_copy(
        update={"commit_sha": second, "analysis_sha256": new.analysis_sha256}
    )
    with pytest.raises(ArchitectureError) as raised:
        check(relabelled, new_payload, new_sources)
    assert raised.value.code == "false_citation"


def test_unseen_architecture_is_animated_and_narrated(
    loaded: dict[str, Loaded], tmp_path: Path
) -> None:
    """Milestone path: reconstruct, validate, animate and narrate with no dedicated code."""
    engine = media_tools()
    payload, sources, report = loaded["custom_unnamed"]
    manifest = explainer.explain(report, payload, sources, tmp_path / "architecture", engine=engine)
    (item,) = manifest["architectures"]
    bundle = tmp_path / "architecture" / "published" / item["id"]
    assert item["type"] == "component_graph" and item["status"] == "VERIFIED"
    narration = json.loads((bundle / "narration.json").read_text(encoding="utf-8"))
    frames = sum(n["frames"] for n in narration)
    assert item["media"]["video_frames"] == frames and item["media"]["full_decode"] == "passed"
    citations = json.loads((bundle / "citations.json").read_text(encoding="utf-8"))
    for citation in citations:
        source = sources[citation["path"]].decode().split("\n")
        assert source[citation["line"] - 1].strip() == citation["quote"]
    stored = Architecture.model_validate_json((bundle / "architecture.json").read_bytes())
    assert {c["element"] for c in citations} >= {c.id for c in stored.connections}
    video = bundle / "video.mp4"
    probed = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(video)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    streams = {s["codec_type"]: s for s in probed["streams"]}
    assert streams["video"]["codec_name"] == "h264" and streams["audio"]["codec_name"] == "aac"
    assert int(streams["video"]["nb_read_frames"]) == frames
    assert (streams["video"]["width"], streams["video"]["height"]) == (WIDTH, HEIGHT)
    loud = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(video), "-af", "volumedetect", "-f", "null", "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stderr
    assert float(loud.split("max_volume:")[1].split("dB")[0]) > -30
    moving = next(n for n in narration if n["connection_ids"] and n["frames"] >= 60)
    start = moving["start_frame"] / FPS
    assert gray_frame(video, start + 0.4) != gray_frame(video, start + 1.0)


# Shapes first met in a real repository: a signature spread over several lines, a handler
# with many call sites, and test functions that call the production code they test.


def drawn(architecture: Architecture) -> None:
    """Every view lays out inside the canvas and its narration is reproducible."""
    lines_ = explainer.narrate(architecture)
    explainer.check_narration(lines_, architecture)
    for view in architecture.views:
        diagram = Diagram(architecture, "example/demo", "a" * 40, view)  # No diagram_overflow.
        assert set(diagram.boxes) == set(view.component_ids)
        placed = list(diagram.boxes.values())
        for i, (ax, ay, aw, ah) in enumerate(placed):
            assert 0 <= ax and ax + aw <= WIDTH and 120 <= ay and ay + ah <= 548
            for bx, by, bw, bh in placed[i + 1 :]:
                assert ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay


def test_parameters_are_cited_where_a_multiline_signature_declares_them(tmp_path: Path) -> None:
    steps = "".join(
        f"def {name}({args}):\n    return {args.split(',')[0]}\n\n\n"
        for name, args in [
            ("soak", "grain"),
            ("grind", "grain, mesh"),
            ("press", "meal, weight"),
            ("sift", "harvest"),
            ("bake", "flour"),
        ]
    )
    mill = (
        "from steps import bake, grind, press, sift, soak\n\n\n"
        "def mill(\n"
        "    grain: list,\n"
        "    mesh=2,\n"
        "    *,\n"
        "    weight: float = 1.0,\n"
        "):\n"
        "    wet = soak(grain)\n"
        "    meal = grind(wet, mesh)\n"
        "    return press(meal, weight)\n\n\n"
        "def run(\n"
        "    harvest,\n"
        "    sieve,\n"
        "    stone,\n"
        "):\n"
        "    clean = sift(harvest)\n"
        "    flour = mill(clean, sieve, weight=stone)\n"
        "    return bake(flour)\n"
    )
    root = written(tmp_path / "source", {"steps.py": steps, "mill.py": mill})
    payload, sources, report = load(root)  # discover() runs check() on its own report.
    validate(report, payload, sources)
    (graph,) = report.architectures
    assert graph.title == "run() in mill.py"
    assert [v.id for v in graph.views] == ["overview", "inside-mill"]
    zoom = graph.views[1]
    inputs = {
        (c.label, c.parent is None): (c.citations[0].line, c.citations[0].quote)
        for c in graph.components
        if c.kind == "input"
    }
    # Top level (run) and inside the zoom (mill): each on its own line, never the `def` line.
    assert inputs == {
        ("harvest", True): (16, "harvest,"),
        ("sieve", True): (17, "sieve,"),
        ("stone", True): (18, "stone,"),
        ("grain", False): (5, "grain: list,"),
        ("mesh", False): (6, "mesh=2,"),
        ("weight", False): (8, "weight: float = 1.0,"),
    }
    inner = {c.id for c in graph.components if c.parent == zoom.parent}
    assert {c.label for c in graph.components if c.id in inner and c.kind == "input"} == {
        "grain",
        "mesh",
        "weight",
    }
    assert set(zoom.component_ids) == inner
    drawn(graph)
    # The defect: citing a parameter on the `def` line, which does not show it, is rejected.
    weight = next(c for c in graph.components if c.label == "weight")
    at_def = Context(payload, sources).cite("mill.py", 4)
    assert at_def is not None and at_def.quote == "def mill("
    forged = graph.model_copy(
        update={
            "components": tuple(
                c.model_copy(update={"citations": (at_def,)}) if c.id == weight.id else c
                for c in graph.components
            )
        }
    )
    with pytest.raises(ArchitectureError) as raised:
        check(rebuilt(report, forged), payload, sources)
    assert raised.value.code == "unsupported_element"


def test_a_handler_with_many_call_sites_stays_within_the_diagram(tmp_path: Path) -> None:
    names = [f"stage{n:02d}" for n in range(1, 21)]
    steps = "import sqlite3\n\n\n" + "".join(
        f"def {name}(order):\n"
        + ("    sqlite3.connect(order)\n" if name == "stage01" else "")
        + "    return order\n\n\n"
        for name in names
    )
    calls = "".join(f"    {name}(order)\n" for name in names)
    app = (
        f"from fastapi import FastAPI\nfrom steps import {', '.join(names)}\n\n"
        'app = FastAPI()\n\n\n@app.post("/orders")\n'
        f"def place(order):\n{calls}    return order\n\n\n"
        '@app.get("/orders")\ndef listing(order):\n    return stage02(order)\n'
    )
    root = written(tmp_path / "source", {"steps.py": steps, "app.py": app})
    payload, sources, report = load(root)
    validate(report, payload, sources)
    (service,) = by_type(report, "service")
    assert service.title == "HTTP service in app.py"
    # Bounded before anything is added: no component is left without a connection.
    linked = {end for c in service.connections for end in (c.source, c.target)}
    assert {c.id for c in service.components} == linked
    assert len(service.components) <= archgraph.MAX_NODES + 2
    called = {c.target for c in service.connections if c.kind == "calls"}
    assert 0 < len(called) < len(names)  # Many call sites, a bounded drawing.
    assert {"POST /orders", "GET /orders", "place", "listing"} <= set(labels(service))
    assert ("listing", "calls", "stage02") in edges(service)
    assert "not drawn" in {u.topic for u in service.unresolved}
    drawn(service)


def test_test_functions_are_not_chosen_as_the_architecture(tmp_path: Path) -> None:
    parts = "".join(
        f"def {name}({args}):\n    return {args.split(',')[0]}\n\n\n"
        for name, args in [
            ("load", "path"),
            ("clean", "rows"),
            ("score", "rows, weights"),
            ("report", "scores"),
        ]
    )
    pipeline = (
        "from app.parts import clean, load, report, score\n\n\n"
        "def run(path, weights):\n"
        "    rows = load(path)\n"
        "    tidy = clean(rows)\n"
        "    scores = score(tidy, weights)\n"
        "    return report(scores)\n"
    )
    # Larger than the production function, and it calls it: before the fix this test was
    # the only root scope, so it alone was drawn as the repository's architecture.
    test = (
        "from app.parts import clean, load, report, score\n"
        "from app.pipeline import run\n\n\n"
        "def test_report_matches_the_pipeline(tmp_path, weights):\n"
        "    rows = load(tmp_path)\n"
        "    tidy = clean(rows)\n"
        "    scores = score(tidy, weights)\n"
        "    summary = report(scores)\n"
        "    expected = run(tmp_path, weights)\n"
        "    assert expected == summary\n"
    )
    root = written(
        tmp_path / "source",
        {
            "app/__init__.py": "",
            "app/parts.py": parts,
            "app/pipeline.py": pipeline,
            "tests/test_pipeline.py": test,
        },
    )
    payload, sources, report = load(root)
    validate(report, payload, sources)
    classes = {f["path"]: f["classification"] for f in payload["knowledge"]["coverage"]["files"]}
    assert classes["tests/test_pipeline.py"] == "test"
    assert classes["app/pipeline.py"] == "source"
    (graph,) = by_type(report, "component_graph")
    assert graph.title == "run() in app/pipeline.py"
    assert {"load", "clean", "score", "report"} <= set(labels(graph))
    for architecture in report.architectures:
        assert not any(path.startswith("tests/") for path in architecture.scope)
        assert "test_report_matches_the_pipeline" not in architecture.title
    drawn(graph)


def test_test_files_are_left_out_of_the_system_overview(
    loaded: dict[str, Loaded], tmp_path: Path
) -> None:
    root = tmp_path / "source"
    shutil.copytree(FIXTURES / "fullstack_web", root)
    production = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    # Each test file imports, requests and uses more than any production file, so before the
    # fix both ranked among the overview's highest-degree files.
    written(
        root,
        {
            "tests/test_app.py": (
                "import sqlite3\n\n"
                "import requests\n"
                "from backend.app import create_item, read_items\n"
                "from backend.repository import add_item, list_items\n\n\n"
                "def test_items_round_trip(tmp_path):\n"
                '    connection = sqlite3.connect(":memory:")\n'
                '    response = requests.get("http://localhost/api/items")\n'
                '    add_item(tmp_path, "x")\n'
                "    assert list_items(tmp_path) == read_items()\n"
                '    assert create_item("x") == response.json()\n'
                "    connection.close()\n"
            ),
            "frontend/api.test.ts": (
                'import { loadItems } from "./api";\n'
                'import { renderPage } from "./page";\n\n'
                "export async function checkItems(): Promise<void> {\n"
                '  const response = await fetch("/api/items");\n'
                '  await renderPage({ textContent: "" });\n'
                "  await loadItems();\n"
                "  await response.json();\n"
                "}\n"
            ),
        },
    )
    payload, sources, report = load(root)
    validate(report, payload, sources)
    classes = {f["path"]: f["classification"] for f in payload["knowledge"]["coverage"]["files"]}
    assert classes["tests/test_app.py"] == classes["frontend/api.test.ts"] == "test"
    assert all(classes[path] == "source" for path in production)

    (overview,) = by_type(report, "system_overview")
    cited_paths = {
        citation.path
        for item in (*overview.components, *overview.connections)
        for citation in item.citations
    }
    assert cited_paths <= production
    assert not {"test_app.py", "api.test.ts"} & {c.label for c in overview.components}
    # The production view is exactly the one the fixture draws without any test files.
    (reference,) = by_type(loaded["fullstack_web"][2], "system_overview")
    assert edges(overview) == edges(reference)
    drawn(overview)


# JavaScript, TypeScript and TSX go through the same extractor, validator, layout and narrator.
# Nothing below is filtered out by language; every element is checked against exact source.


def cited(component: Component) -> tuple[str, int, str]:
    citation = component.citations[0]
    return citation.path, citation.line, citation.quote


def test_express_routes_handlers_and_client_library(loaded: dict[str, Loaded]) -> None:
    payload, sources, report = loaded["express_service"]
    assert {f["language"] for f in payload["knowledge"]["coverage"]["files"]} == {"javascript"}
    (service,) = report.architectures
    assert (service.type, service.title) == ("service", "HTTP service in server.js")
    assert edges(service) == {
        ("GET /items", "routes", "GET /items handler"),
        ("GET /items handler", "calls", "listItems"),
        ("POST /items", "routes", "createItem"),
        ("createItem", "calls", "addItem"),
        ("listItems", "uses", "pg"),
        ("addItem", "uses", "pg"),
    }
    parts = labels(service)
    # A handler written in place is cited where it starts; a named one where it is declared.
    assert cited(parts["GET /items handler"]) == (
        "server.js",
        7,
        'app.get("/items", async (req, res) => {',
    )
    assert cited(parts["createItem"]) == ("server.js", 14, "async function createItem(req, res) {")
    assert cited(parts["POST /items"]) == ("server.js", 12, 'app.post("/items", createItem);')
    assert parts["GET /items handler"].lines == ("takes req, res",)
    # `new Pool()` from "pg" at module level is a client handle the functions use.
    assert (parts["pg"].kind, parts["pg"].group, parts["pg"].lines) == (
        "database",
        "external",
        ("client library",),
    )
    assert "pool.query(" in parts["pg"].citations[0].quote and parts["pg"].anchors == ("pool",)
    # Members destructured from `require` of a module whose `module.exports` names them, with
    # a destructuring binding the analyzer confirms, are as strong as a confirmed import.
    assert (parts["listItems"].status, parts["createItem"].status) == ("VERIFIED", "VERIFIED")
    assert "binding strength" not in {u.topic for u in service.unresolved}
    assert all(
        (c.basis, c.status) == ("declared_route", "INFERRED")
        for c in service.connections
        if c.kind == "routes"
    )
    spoken = [line.text for line in explainer.narrate(service)]
    assert "The route GET /items is declared on GET /items handler. Which handler serves a " in (
        " ".join(spoken)
    )
    assert "listItems calls the pg client library, a database interaction." in " ".join(spoken)
    drawn(service)


def test_typescript_values_parameters_and_constructed_parts(loaded: dict[str, Loaded]) -> None:
    payload, sources, report = loaded["typescript_pipeline"]
    (graph,) = report.architectures
    assert (graph.type, graph.status, graph.title) == (
        "component_graph",
        "VERIFIED",
        "runPipeline() in src/pipeline.ts",
    )
    top = {c for c in edges(graph) if c[0] not in {"scores", "key", "encoder"}}
    assert top == {
        ("source", "data", "readRecords"),
        ("readRecords", "data", "normalise"),
        ("normalise", "data", "score"),
        ("weight", "data", "score"),
        ("url", "data", "ScoreStore"),
        ("score", "data", "ScoreStore"),
        ("ScoreStore", "data", "result"),
        ("ScoreStore", "uses", "redis"),
    }
    parts = labels(graph)
    # A namespace import (`transform.score`) and an arrow-function constant both bind.
    assert (parts["normalise"].group, parts["normalise"].anchors) == (
        "src/transform.ts",
        ("normalise =",),
    )
    assert parts["ScoreStore"].lines == ("methods save",)  # The constructor is not listed.
    # Each parameter of a multi-line typed signature is cited on the line that declares it.
    assert {name: cited(parts[name])[1:] for name in ("source", "weight", "url")} == {
        "source": (6, "source: string,"),
        "weight": (7, "weight: number,"),
        "url": (8, "url: string,"),
    }
    assert "The value from readRecords, held in rows, is passed to normalise." in [
        step.text for step in graph.flows[0].steps
    ]
    # `redis` is reached through `createClient`, which is what the cited line shows.
    assert (parts["redis"].kind, parts["redis"].anchors) == ("cache", ("createClient",))
    # `this.part = ...` in the constructor, used by a method: a zoom view, as for Python.
    zoom = graph.views[1]
    assert (zoom.id, zoom.title) == ("inside-scorestore", "Inside ScoreStore.save")
    inner = {c.label: c for c in graph.components if c.parent == zoom.parent}
    assert set(inner) == {"scores", "key", "encoder", "client"}
    assert (inner["encoder"].lines, inner["encoder"].anchors) == (("Encoder",), ("this.encoder",))
    assert {(a, k, b) for a, k, b in edges(graph) if a in inner} == {
        ("scores", "data", "encoder"),
        ("key", "data", "client"),
        ("encoder", "data", "client"),
    }
    drawn(graph)
    # Citing a parameter on the signature's first line, which does not show it, is rejected.
    weight = parts["weight"]
    at_signature = Context(payload, sources).cite("src/pipeline.ts", 5)
    assert at_signature is not None and at_signature.quote == "export async function runPipeline("
    forged = graph.model_copy(
        update={
            "components": tuple(
                c.model_copy(update={"citations": (at_signature,)}) if c.id == weight.id else c
                for c in graph.components
            )
        }
    )
    with pytest.raises(ArchitectureError) as raised:
        check(rebuilt(report, forged), payload, sources)
    assert raised.value.code == "unsupported_element"
    moved = graph.model_copy(
        update={
            "components": tuple(
                c.model_copy(
                    update={
                        "citations": (
                            c.citations[0].model_copy(
                                update={"quote": "export function readRecords(input: string) {"}
                            ),
                        )
                    }
                )
                if c.label == "readRecords"
                else c
                for c in graph.components
            )
        }
    )
    with pytest.raises(ArchitectureError) as raised:
        check(rebuilt(report, moved), payload, sources)
    assert raised.value.code == "false_citation"


def test_tsx_components_receive_values_through_jsx(loaded: dict[str, Loaded]) -> None:
    payload, sources, report = loaded["react_frontend"]
    assert {f["language"] for f in payload["knowledge"]["coverage"]["files"]} == {
        "typescript",
        "tsx",
    }
    (graph,) = report.architectures
    assert (graph.type, graph.title) == ("component_graph", "Page() in web/Page.tsx")
    assert edges(graph) == {
        ("props", "data", "loadItems"),
        ("loadItems", "data", "rank"),
        ("rank", "data", "ItemList"),
        ("rank", "data", "Summary"),
        ("props", "data", "Summary"),
        ("loadItems", "uses", "fetch"),
    }
    status = {(c.source, c.target): c.status for c in graph.connections}
    ids = {c.label: c.id for c in graph.components}
    # `items={ranked}` passes the value itself; `total={ranked.length}` passes part of it.
    assert status[ids["rank"], ids["ItemList"]] == "VERIFIED"
    assert status[ids["rank"], ids["Summary"]] == "INFERRED"
    assert status[ids["props"], ids["loadItems"]] == "INFERRED"
    element = next(
        c for c in graph.connections if (c.source, c.target) == (ids["rank"], ids["ItemList"])
    )
    assert [x.quote for x in element.citations] == ["<ItemList items={ranked} />"]
    # The platform's fetch, not rebound in the file, is drawn as a built-in client.
    fetch = labels(graph)["fetch"]
    assert (fetch.kind, fetch.group, fetch.lines) == (
        "http_client",
        "external",
        ("built-in function",),
    )
    spoken = " ".join(line.text for line in explainer.narrate(graph))
    assert "loadItems calls the built-in fetch function, a http client interaction." in spoken
    assert "fetch is a built-in function for a http client." in spoken
    # Returned JSX describes markup; it is not a value from any component.
    assert "output" not in {c.kind for c in graph.components}
    drawn(graph)


def test_typescript_frontend_and_express_backend_share_one_overview(
    loaded: dict[str, Loaded],
) -> None:
    payload, sources, report = loaded["fullstack_typescript"]
    assert [a.type for a in report.architectures] == ["system_overview", "service"]
    overview, service = report.architectures
    assert edges(overview) == {
        ("view.ts", "imports", "api.ts"),
        ("api.ts", "http_request", "app.js"),
        ("api.ts", "uses", "fetch"),
        ("app.js", "imports", "orders.js"),
        ("orders.js", "uses", "mongodb"),
    }
    files = {c.label: c.lines[0] for c in overview.components if c.kind == "source_file"}
    assert files == {
        "api.ts": "typescript, 1 definition",
        "view.ts": "typescript, 1 definition",
        "app.js": "javascript",
        "orders.js": "javascript, 2 definitions",
    }
    request = next(c for c in overview.connections if c.kind == "http_request")
    assert (request.basis, request.status) == ("literal_match", "INFERRED")
    assert {c.path for c in request.citations} == {"client/api.ts", "server/app.js"}
    assert edges(service) == {
        ("GET /api/orders", "routes", "GET /api/orders handler"),
        ("GET /api/orders handler", "calls", "findOrders"),
        ("POST /api/orders", "routes", "POST /api/orders handler"),
        ("POST /api/orders handler", "calls", "placeOrder"),
        ("findOrders", "uses", "mongodb"),
        ("placeOrder", "uses", "mongodb"),
    }
    assert service.status == "INFERRED" and {c.status for c in service.components} >= {"VERIFIED"}
    # Neither a declared route nor a matching literal can be promoted to a verified interaction.
    for architecture in report.architectures:
        for connection in architecture.connections:
            if connection.basis not in {"declared_route", "literal_match"}:
                continue
            promoted = architecture.model_copy(
                update={
                    "connections": tuple(
                        c.model_copy(update={"status": "VERIFIED"}) if c.id == connection.id else c
                        for c in architecture.connections
                    )
                }
            )
            with pytest.raises(ArchitectureError) as raised:
                check(rebuilt(report, promoted), payload, sources)
            assert raised.value.code == "unsupported_runtime_claim"
    for architecture in report.architectures:
        drawn(architecture)


def test_script_scopes_bind_conservatively(tmp_path: Path) -> None:
    steps = (
        "export function fetchRows(source) {\n  return source;\n}\n\n"
        "export function clean(rows) {\n  return rows;\n}\n\n"
        "export function save(row) {\n  return row;\n}\n\n"
        "export function audit(entry) {\n  return entry;\n}\n"
    )
    job = (
        'import { audit, clean, fetchRows, save } from "./steps.js";\n'
        'import { load } from "./client.js";\n\n'
        "export function run(source, entry) {\n"
        "  const rows = fetchRows(source);\n"
        "  const tidy = clean(rows);\n"
        "  tidy.forEach((rows) => save(rows));\n"
        "  load(entry);\n"
        "  return audit(entry);\n"
        "}\n"
    )
    # `fetch` is rebound in this file, so it is not the platform's request function.
    client = (
        'import { getJSON } from "./http.js";\n\n'
        "const fetch = getJSON;\n\n"
        "export function load(url) {\n  return fetch(url);\n}\n"
    )
    http = "export function getJSON(url) {\n  return url;\n}\n"
    # An Express application in a test file is not the repository's service.
    test = (
        'import express from "express";\n'
        'import { run } from "../lib/job.js";\n\n'
        "const app = express();\n\n"
        'app.get("/health", (req, res) => {\n'
        "  const seen = run(req.query, req.body);\n"
        "  res.json(seen);\n"
        "});\n"
    )
    root = written(
        tmp_path / "source",
        {
            "lib/steps.js": steps,
            "lib/job.js": job,
            "lib/client.js": client,
            "lib/http.js": http,
            "tests/server.test.js": test,
        },
    )
    payload, sources, report = load(root)
    validate(report, payload, sources)
    routes = {
        c["path"]
        for c in payload["knowledge"]["entrypoints"]["candidates"]
        if c["rule"] == "framework-route-v1"
    }
    assert routes == {"tests/server.test.js"}  # Found by the analyzer, then not drawn.
    assert by_type(report, "service") == []
    (graph,) = report.architectures
    assert graph.title == "run() in lib/job.js"
    found = edges(graph)
    assert {
        ("source", "data", "fetchRows"),
        ("fetchRows", "data", "clean"),
        ("entry", "data", "audit"),
        ("entry", "data", "load"),
        ("audit", "data", "result"),
    } <= found
    # A call inside a callback is a call site of run, but the callback's own parameter `rows`
    # hides the outer `rows`: no value from fetchRows or clean is claimed to reach save.
    assert "save" in labels(graph)
    assert not {(a, k, b) for a, k, b in found if b == "save"}
    assert "fetch" not in {c.label for c in graph.components}
    assert not any(path.startswith("tests/") for path in graph.scope)
    drawn(graph)


def quoted(component: Component) -> list[tuple[str, int, str]]:
    return [(c.path, c.line, c.quote) for c in component.citations]


USERS_DB = (
    'const { Pool } = require("pg");\n\n'
    "const pool = new Pool();\n\n"
    "function listUsers(team) {\n"
    '  return pool.query("SELECT name FROM users WHERE team = $1", [team]);\n'
    "}\n\n"
    "function findUser(id) {\n"
    '  return pool.query("SELECT name FROM users WHERE id = $1", [id]);\n'
    "}\n\n"
    "module.exports = { listUsers, findUser };\n"
)
USERS_ROUTER = (
    'const express = require("express");\n'
    'const { listUsers, findUser } = require("../db");\n\n'
    "const router = express.Router();\n\n"
    'router.get("/", async (req, res) => {\n'
    "  const rows = await listUsers(req.query.team);\n"
    "  res.json(rows);\n"
    "});\n\n"
    'router.get("/:id", showUser);\n\n'
    "async function showUser(req, res) {\n"
    "  const user = await findUser(req.params.id);\n"
    "  res.json(user);\n"
    "}\n\n"
    "module.exports = router;\n"
)
USERS_APP = (
    'const express = require("express");\n'
    'const users = require("./routes/users");\n\n'
    "const app = express();\n"
    "app.use(express.json());\n"
    'app.use("/api/users", users);\n\n'
    "app.listen(3000);\n"
)
USERS_CLIENT = (
    "export async function loadUsers() {\n"
    '  const response = await fetch("/api/users");\n'
    "  return response.json();\n"
    "}\n"
)


def test_express_router_routes_take_the_prefix_they_are_mounted_at(tmp_path: Path) -> None:
    files = {
        "server/db.js": USERS_DB,
        "server/routes/users.js": USERS_ROUTER,
        "server/app.js": USERS_APP,
        "web/client.js": USERS_CLIENT,
    }
    payload, sources, report = load(written(tmp_path / "source", files))
    validate(report, payload, sources)
    # The analyzer records routes only on the object bound to `express()`: none here.
    assert not {
        c["path"]
        for c in payload["knowledge"]["entrypoints"]["candidates"]
        if c["rule"] == "framework-route-v1"
    }
    (service,) = by_type(report, "service")
    assert service.title == "HTTP service in server/routes/users.js"
    assert edges(service) == {
        ("GET /api/users", "routes", "GET /api/users handler"),
        ("GET /api/users handler", "calls", "listUsers"),
        ("GET /api/users/:id", "routes", "showUser"),
        ("showUser", "calls", "findUser"),
        ("listUsers", "uses", "pg"),
        ("findUser", "uses", "pg"),
    }
    parts = labels(service)
    # A mounted route is cited where it is declared and where the router is mounted, and
    # anchored on the path part each of those lines shows.
    endpoint = parts["GET /api/users/:id"]
    assert quoted(endpoint) == [
        ("server/routes/users.js", 11, 'router.get("/:id", showUser);'),
        ("server/app.js", 6, 'app.use("/api/users", users);'),
    ]
    assert (endpoint.anchors, endpoint.lines, endpoint.status) == (
        ("/:id", "/api/users"),
        ("mounted route",),
        "INFERRED",
    )
    assert cited(parts["GET /api/users handler"]) == (
        "server/routes/users.js",
        6,
        'router.get("/", async (req, res) => {',
    )
    # Destructured from a `require` whose module.exports names them: confirmed bindings.
    assert (parts["listUsers"].status, parts["findUser"].status) == ("VERIFIED", "VERIFIED")
    assert all(
        (c.basis, c.status) == ("declared_route", "INFERRED")
        for c in service.connections
        if c.kind == "routes"
    )
    spoken = " ".join(line.text for line in explainer.narrate(service))
    assert "The route GET /api/users/:id is declared on showUser." in spoken
    # The client's path literal matches the combined path, not the router's own `/`.
    (overview,) = by_type(report, "system_overview")
    assert ("client.js", "http_request", "users.js") in edges(overview)
    request = next(c for c in overview.connections if c.kind == "http_request")
    assert {c.path for c in request.citations} == {
        "web/client.js",
        "server/routes/users.js",
        "server/app.js",
    }
    for architecture in report.architectures:
        drawn(architecture)
    # Without the mount line, the cited source no longer shows the prefix: rejected.
    forged = service.model_copy(
        update={
            "components": tuple(
                c.model_copy(update={"citations": c.citations[:1]}) if c.id == endpoint.id else c
                for c in service.components
            )
        }
    )
    with pytest.raises(ArchitectureError) as raised:
        check(rebuilt(report, forged), payload, sources)
    assert raised.value.code == "unsupported_element"


def test_nested_typescript_routers_and_unmounted_or_foreign_routers(tmp_path: Path) -> None:
    files = {
        "src/store.ts": (
            'import Redis from "ioredis";\n\n'
            "const cache = new Redis();\n\n"
            "export async function readReport(id: string) {\n  return cache.get(id);\n}\n\n"
            "export async function purge(id: string) {\n  return cache.del(id);\n}\n"
        ),
        "src/admin.ts": (
            'import { Router } from "express";\n'
            'import { purge } from "./store";\n\n'
            "export const admin = Router();\n\n"
            'admin.delete("/cache/:id", async (req, res) => {\n'
            "  await purge(req.params.id);\n"
            "  res.sendStatus(204);\n"
            "});\n"
        ),
        "src/reports.ts": (
            'import express from "express";\n'
            'import { admin } from "./admin";\n'
            'import { readReport } from "./store";\n\n'
            "const reports = express.Router();\n\n"
            'reports.use("/admin", admin);\n'
            'reports.get("/:id", async (req, res) => {\n'
            "  res.json(await readReport(req.params.id));\n"
            "});\n\n"
            "export default reports;\n"
        ),
        "src/server.ts": (
            'import express from "express";\n'
            'import reports from "./reports";\n\n'
            "const app = express();\n"
            'app.use("/r", reports);\n'
            "app.listen(8080);\n"
        ),
        # Declared but never mounted: shown with its own path, and the mount is unresolved.
        "src/orphan.ts": (
            'import { Router } from "express";\n'
            'import { readReport } from "./store";\n\n'
            "const orphan = Router();\n\n"
            'orphan.get("/orphan", async (req, res) => {\n'
            '  res.json(await readReport("x"));\n'
            "});\n"
        ),
        # A `Router` that is not the one from the express package is not a router.
        "src/fake.js": (
            'const { Router } = require("./router");\n'
            'const { purge } = require("./store");\n\n'
            "const fake = Router();\n\n"
            'fake.get("/fake", async (req, res) => {\n'
            '  res.json(await purge("x"));\n'
            "});\n"
        ),
        "src/router.js": "function Router() {\n  return {};\n}\n\nmodule.exports = { Router };\n",
    }
    payload, sources, report = load(written(tmp_path / "source", files))
    validate(report, payload, sources)
    services = {a.title: a for a in by_type(report, "service")}
    assert set(services) == {
        "HTTP service in src/admin.ts",
        "HTTP service in src/orphan.ts",
        "HTTP service in src/reports.ts",
    }
    admin = services["HTTP service in src/admin.ts"]
    handler = "DELETE /r/admin/cache/:id handler"[:28]  # Labels are cut to the box width.
    assert edges(admin) == {
        ("DELETE /r/admin/cache/:id", "routes", handler),
        (handler, "calls", "purge"),
        ("purge", "uses", "ioredis"),
    }
    endpoint = labels(admin)["DELETE /r/admin/cache/:id"]
    # Outermost mount first: the application's `/r`, then the router's `/admin`.
    assert quoted(endpoint) == [
        ("src/admin.ts", 6, 'admin.delete("/cache/:id", async (req, res) => {'),
        ("src/server.ts", 5, 'app.use("/r", reports);'),
        ("src/reports.ts", 7, 'reports.use("/admin", admin);'),
    ]
    assert endpoint.anchors == ("/cache/:id", "/r", "/admin")
    # The analyzer also records `Router()` from express as an application; its routes are
    # read once, with their mounts, never again without the prefix.
    every = {c.label for a in report.architectures for c in a.components if c.kind == "endpoint"}
    assert every == {"DELETE /r/admin/cache/:id", "GET /r/:id", "GET /orphan"}
    orphan = services["HTTP service in src/orphan.ts"]
    assert labels(orphan)["GET /orphan"].lines == ("router route",)
    assert "router mount" in {u.topic for u in orphan.unresolved}
    assert "router mount" not in {u.topic for u in admin.unresolved}
    for architecture in report.architectures:
        drawn(architecture)


def test_nextjs_route_handlers_are_routes_read_from_the_file_location(tmp_path: Path) -> None:
    orders = (
        'import { MongoClient } from "mongodb";\n\n'
        'const client = new MongoClient("mongodb://orders-db:27017");\n\n'
        "export async function findOrders(customer: string) {\n"
        '  return client.db("shop").collection("orders").find({ customer }).toArray();\n'
        "}\n\n"
        "export async function placeOrder(order: unknown) {\n"
        '  await client.db("shop").collection("orders").insertOne(order);\n'
        "  return order;\n"
        "}\n"
    )
    files = {
        "lib/orders.ts": orders,
        "app/api/orders/route.ts": (
            'import { findOrders, placeOrder } from "../../../lib/orders";\n\n'
            "export async function GET(request: Request) {\n"
            '  const customer = new URL(request.url).searchParams.get("customer") ?? "";\n'
            "  const orders = await findOrders(customer);\n"
            "  return Response.json(orders);\n"
            "}\n\n"
            "export async function POST(request: Request) {\n"
            "  const order = await placeOrder(await request.json());\n"
            "  return Response.json(order, { status: 201 });\n"
            "}\n"
        ),
        "app/api/orders/[id]/route.ts": (
            'import { findOrders, placeOrder } from "../../../../lib/orders";\n\n'
            "export const PATCH = async (request: Request) => {\n"
            "  const order = await placeOrder(await request.json());\n"
            "  return Response.json(order);\n"
            "};\n\n"
            "async function remove(request: Request) {\n"
            "  return findOrders(request.url);\n"
            "}\n\n"
            "export { remove as DELETE };\n"
        ),
        # A route group adds no path segment; a private folder is not routed at all.
        "app/(admin)/api/stats/route.ts": (
            'import { findOrders } from "../../../../lib/orders";\n\n'
            "export async function GET() {\n"
            '  return Response.json(await findOrders("all"));\n'
            "}\n"
        ),
        "app/_lib/route.ts": (
            'import { findOrders } from "../../lib/orders";\n\n'
            "export async function GET() {\n"
            '  return Response.json(await findOrders("x"));\n'
            "}\n"
        ),
        "app/components/list.ts": (
            "export async function listOrders() {\n"
            '  const response = await fetch("/api/orders");\n'
            "  return response.json();\n"
            "}\n"
        ),
    }
    # Without evidence of Next.js, a file named route.ts declares no route.
    payload, sources, report = load(written(tmp_path / "plain", files))
    validate(report, payload, sources)
    assert by_type(report, "service") == []
    files["package.json"] = (
        '{\n  "name": "shop",\n  "dependencies": {\n    "next": "16.4.6"\n  }\n}\n'
    )
    payload, sources, report = load(written(tmp_path / "next", files))
    validate(report, payload, sources)
    services = {a.title: a for a in by_type(report, "service")}
    assert set(services) == {
        "HTTP service in app/(admin)/api/stats/route.ts",
        "HTTP service in app/api/orders/[id]/route.ts",
        "HTTP service in app/api/orders/route.ts",
    }
    collection = services["HTTP service in app/api/orders/route.ts"]
    assert edges(collection) == {
        ("GET /api/orders", "routes", "GET"),
        ("GET", "calls", "findOrders"),
        ("POST /api/orders", "routes", "POST"),
        ("POST", "calls", "placeOrder"),
        ("findOrders", "uses", "mongodb"),
        ("placeOrder", "uses", "mongodb"),
    }
    parts = labels(collection)
    assert quoted(parts["GET /api/orders"]) == [
        ("app/api/orders/route.ts", 3, "export async function GET(request: Request) {")
    ]
    assert (parts["GET /api/orders"].anchors, parts["GET /api/orders"].lines) == (
        ("GET",),
        ("file-system route",),
    )
    # Platform globals such as URL and Response are not reported as unbound names.
    assert "unbound calls" not in {u.topic for u in collection.unresolved}
    item = services["HTTP service in app/api/orders/[id]/route.ts"]
    assert edges(item) == {
        ("PATCH /api/orders/[id]", "routes", "PATCH"),
        ("PATCH", "calls", "placeOrder"),
        ("DELETE /api/orders/[id]", "routes", "remove"),
        ("remove", "calls", "findOrders"),
        ("placeOrder", "uses", "mongodb"),
        ("findOrders", "uses", "mongodb"),
    }
    # `export { remove as DELETE }`: the route is cited where the method name is exported.
    assert quoted(labels(item)["DELETE /api/orders/[id]"]) == [
        ("app/api/orders/[id]/route.ts", 12, "export { remove as DELETE };")
    ]
    assert {
        c.label for c in services["HTTP service in app/(admin)/api/stats/route.ts"].components
    } >= {"GET /api/stats"}
    (overview,) = by_type(report, "system_overview")
    assert ("list.ts", "http_request", "route.ts") in edges(overview)
    request = next(c for c in overview.connections if c.kind == "http_request")
    assert {c.path for c in request.citations} == {
        "app/components/list.ts",
        "app/api/orders/route.ts",
    }
    for architecture in report.architectures:
        drawn(architecture)


def test_commonjs_exports_bind_what_require_names(tmp_path: Path) -> None:
    files = {
        "lib/store.js": (
            'const { Pool } = require("pg");\n\n'
            "const pool = new Pool();\n\n"
            'function findUser(id) {\n  return pool.query("SELECT 1", [id]);\n}\n\n'
            'function saveUser(user) {\n  return pool.query("INSERT", [user]);\n}\n\n'
            "function hidden(user) {\n  return user;\n}\n\n"
            "module.exports = { findUser, saveUser };\n"
        ),
        "lib/format.js": "function format(row) {\n  return row;\n}\n\nmodule.exports = format;\n",
        "lib/audit.js": "exports.audit = function (entry) {\n  return entry;\n};\n",
        "lib/job.js": (
            'const { findUser, saveUser, hidden } = require("./store");\n'
            'const format = require("./format");\n'
            'const audit = require("./audit");\n\n'
            "function run(id) {\n"
            "  const user = findUser(id);\n"
            "  const shaped = format(user);\n"
            "  saveUser(shaped);\n"
            "  hidden(shaped);\n"
            "  return audit.audit(shaped);\n"
            "}\n\n"
            "module.exports = { run };\n"
        ),
        "lib/controller.js": (
            'const { findUser } = require("./store");\n\n'
            "module.exports = {\n"
            "  async show(req, res) {\n"
            "    const user = await findUser(req.params.id);\n"
            "    res.json(user);\n"
            "  },\n"
            "  list: async (req, res) => {\n"
            "    res.json(await findUser(req.query.id));\n"
            "  },\n"
            "};\n"
        ),
        "lib/server.js": (
            'const express = require("express");\n'
            'const controller = require("./controller");\n\n'
            "const app = express();\n"
            'app.get("/users/:id", controller.show);\n'
            'app.get("/users", controller.list);\n'
            "app.listen(3000);\n"
        ),
    }
    payload, sources, report = load(written(tmp_path / "source", files))
    validate(report, payload, sources)
    (graph,) = by_type(report, "component_graph")
    assert graph.title == "run() in lib/job.js"
    assert {
        ("id", "data", "findUser"),
        ("findUser", "data", "format"),
        ("format", "data", "saveUser"),
        ("format", "data", "audit"),
        ("audit", "data", "result"),
    } <= edges(graph)
    parts = labels(graph)
    # `const { a } = require(...)` of names `module.exports = { ... }` gives: confirmed.
    assert (parts["findUser"].status, parts["saveUser"].status) == ("VERIFIED", "VERIFIED")
    # `const format = require(...)` of `module.exports = format`: the module value. The
    # analyzer counts that declaration as a write, so the binding stays inferred.
    assert (cited(parts["format"]), parts["format"].status) == (
        ("lib/format.js", 1, "function format(row) {"),
        "INFERRED",
    )
    # A function written in place as `exports.audit = ...` is its own definition.
    assert (cited(parts["audit"]), parts["audit"].status) == (
        ("lib/audit.js", 1, "exports.audit = function (entry) {"),
        "INFERRED",
    )
    # `hidden` is declared in store.js but not exported: it stays an unbound name.
    assert "hidden" not in parts
    assert "hidden" in " ".join(u.reason for u in graph.unresolved if u.topic == "unbound calls")
    # Handlers exported as members of an object and reached as `controller.show`.
    (service,) = by_type(report, "service")
    assert edges(service) == {
        ("GET /users/:id", "routes", "show"),
        ("show", "calls", "findUser"),
        ("GET /users", "routes", "list"),
        ("list", "calls", "findUser"),
        ("findUser", "uses", "pg"),
    }
    handlers = labels(service)
    assert (cited(handlers["show"]), cited(handlers["list"])) == (
        ("lib/controller.js", 4, "async show(req, res) {"),
        ("lib/controller.js", 8, "list: async (req, res) => {"),
    )
    assert {handlers["show"].status, handlers["list"].status} == {"INFERRED"}
    for architecture in report.architectures:
        drawn(architecture)


def test_commonjs_exports_are_read_only_when_the_syntax_settles_them() -> None:
    def exported(source: str) -> list[str | None] | None:
        file = SourceFile("lib/m.js", source.encode(), "javascript")
        found = jsflow.commonjs_exports(file.root, file.body)
        return None if found is None else [item.name for item in found]

    assert exported("module.exports = { a, b: c, d() {}, e: () => 1, f: 2 };") == [
        "a",
        "b",
        "d",
        "e",
    ]
    assert exported("module.exports = handler;\nmodule.exports.extra = other;") == [None, "extra"]
    # Assigned twice: which value holds is not settled by the syntax.
    assert exported("module.exports = { a };\nmodule.exports = { b };") is None
    # Replaced by the later module.exports, or no longer reaching it through `exports`.
    assert exported("module.exports.a = a;\nmodule.exports = { b };\nexports.c = c;") == ["b"]
    assert exported("exports.a = a;\nexports.a = b;\nexports.c = function () {};") == ["c"]
    # Only unconditional statements of the file itself.
    assert exported("if (x) {\n  module.exports = { a };\n}\nfunction f() { exports.b = b; }") == []


@pytest.mark.parametrize(
    ("path", "route"),
    [
        ("app/api/items/route.ts", "/api/items"),
        ("src/app/api/items/[id]/route.js", "/api/items/[id]"),
        ("app/(shop)/cart/route.tsx", "/cart"),
        ("app/route.ts", "/"),
        ("app/_private/route.ts", None),
        ("app/@modal/route.ts", None),
        ("app/(.)photo/route.ts", None),
        ("app/api/items/handler.ts", None),
        ("api/items/route.ts", None),
    ],
)
def test_app_router_paths_follow_the_file_location(path: str, route: str | None) -> None:
    assert jsflow.app_route(path) == route


def test_router_paths_join_as_express_mounts_them() -> None:
    assert jsflow.joined("/api/users", "/") == "/api/users"
    assert jsflow.joined("/api/", "/users/", "/:id") == "/api/users/:id"
    assert jsflow.joined("", "/items") == "/items"
    assert jsflow.joined("/", "/") == "/"


def test_destructured_props_are_cited_parameters(tmp_path: Path) -> None:
    files = {
        "web/api.ts": (
            "export async function loadItems(tag: string): Promise<string[]> {\n"
            "  const response = await fetch(`/api/items?tag=${tag}`);\n"
            "  return response.json();\n"
            "}\n"
        ),
        "web/rank.ts": (
            "export function rank(items: string[]): string[] {\n  return [...items].sort();\n}\n"
        ),
        "web/Summary.tsx": (
            "export function Summary({ total, title }: { total: unknown; title: unknown }) {\n"
            "  return (\n    <p>\n      {String(title)}: {String(total)}\n    </p>\n  );\n}\n"
        ),
        "web/Badge.jsx": "export function Badge({ label }) {\n  return <b>{label}</b>;\n}\n",
        "web/Page.tsx": (
            'import { loadItems } from "./api";\n'
            'import { rank } from "./rank";\n'
            'import { Summary } from "./Summary";\n\n'
            "export async function Page({\n"
            "  tag,\n"
            "  limit,\n"
            "}: {\n"
            "  tag: string;\n"
            "  limit: number;\n"
            "}) {\n"
            "  const items = await loadItems(tag);\n"
            "  const ranked = rank(items);\n"
            "  return <Summary total={limit} title={ranked} />;\n"
            "}\n"
        ),
        "web/Card.jsx": (
            'import { rank } from "./rank";\n'
            'import { Summary } from "./Summary";\n'
            'import { Badge } from "./Badge";\n\n'
            "export const Card = ({ rows, heading: title, size = 3 }) => {\n"
            "  const ranked = rank(rows);\n"
            "  return (\n"
            "    <section>\n"
            "      <Summary total={ranked} title={title} />\n"
            "      <Badge label={size} />\n"
            "    </section>\n"
            "  );\n"
            "};\n"
        ),
    }
    payload, sources, report = load(written(tmp_path / "source", files))
    validate(report, payload, sources)
    graphs = {a.title: a for a in by_type(report, "component_graph")}
    assert set(graphs) == {"Page() in web/Page.tsx", "Card() in web/Card.jsx"}
    page, card = graphs["Page() in web/Page.tsx"], graphs["Card() in web/Card.jsx"]
    # Each destructured prop of a multi-line typed signature is cited where it is declared.
    inputs = {c.label: cited(c) for c in page.components if c.kind == "input"}
    assert inputs == {
        "tag": ("web/Page.tsx", 6, "tag,"),
        "limit": ("web/Page.tsx", 7, "limit,"),
    }
    assert {
        ("tag", "data", "loadItems"),
        ("loadItems", "data", "rank"),
        ("rank", "data", "Summary"),
        ("limit", "data", "Summary"),
    } <= edges(page)
    # A renamed prop is the local name it binds; a default value does not hide the name.
    line = "export const Card = ({ rows, heading: title, size = 3 }) => {"
    assert {c.label: cited(c) for c in card.components if c.kind == "input"} == {
        "rows": ("web/Card.jsx", 5, line),
        "title": ("web/Card.jsx", 5, line),
        "size": ("web/Card.jsx", 5, line),
    }
    assert {
        ("rows", "data", "rank"),
        ("rank", "data", "Summary"),
        ("title", "data", "Summary"),
        ("size", "data", "Badge"),
    } <= edges(card)
    # The parameters themselves are what the cited line shows; the analyzer treats a file
    # with destructured parameters as unsafe, so the components they reach are inferred.
    for graph in (page, card):
        assert {c.status for c in graph.components if c.kind == "input"} == {"VERIFIED"}
        assert "binding strength" in {u.topic for u in graph.unresolved}
        drawn(graph)


def test_a_long_multi_language_import_chain_still_fits_the_overview(tmp_path: Path) -> None:
    """Before the overview was bounded by layout, a chain this long raised diagram_overflow."""
    files = {
        f"web/m{i}.ts": (
            f'import {{ step{i + 1} }} from "./m{i + 1}";\n\n'
            f"export function step{i}(x: number): number {{\n  return step{i + 1}(x);\n}}\n"
        )
        for i in range(9)
    }
    files["web/m9.ts"] = "export function step9(x: number): number {\n  return x;\n}\n"
    files["web/m0.ts"] = (
        'import { step1 } from "./m1";\n\n'
        "export async function step0(x: number): Promise<number> {\n"
        '  const response = await fetch("/api/items");\n'
        "  return step1(x);\n"
        "}\n"
    )
    files["backend/app.py"] = (
        "from fastapi import FastAPI\n\napp = FastAPI()\n\n\n"
        '@app.get("/api/items")\ndef items():\n    return []\n'
    )
    payload, sources, report = load(written(tmp_path / "source", files))
    validate(report, payload, sources)
    (overview,) = by_type(report, "system_overview")
    top = [c for c in overview.components if c.parent is None]
    assert len(top) <= 9
    assert {"python", "typescript"} <= {
        f["language"] for f in payload["knowledge"]["coverage"]["files"]
    }
    assert ("m0.ts", "imports", "m1.ts") in edges(overview)
    assert "not drawn" in {u.topic for u in overview.unresolved}
    drawn(overview)  # Would raise LayoutError("diagram_overflow") without the bound.


def test_script_architecture_is_animated_and_narrated(
    loaded: dict[str, Loaded], tmp_path: Path
) -> None:
    engine = media_tools()
    payload, sources, report = loaded["typescript_pipeline"]
    manifest = explainer.explain(report, payload, sources, tmp_path / "architecture", engine=engine)
    (item,) = manifest["architectures"]
    assert (item["type"], item["status"]) == ("component_graph", "VERIFIED")
    assert item["media"]["full_decode"] == "passed"
    bundle = tmp_path / "architecture" / "published" / item["id"]
    narration = json.loads((bundle / "narration.json").read_text(encoding="utf-8"))
    assert item["media"]["video_frames"] == sum(n["frames"] for n in narration)
    assert {n["view"] for n in narration} == {"overview", "inside-scorestore"}
    citations = json.loads((bundle / "citations.json").read_text(encoding="utf-8"))
    assert {c["path"] for c in citations} == {
        "src/ingest.ts",
        "src/pipeline.ts",
        "src/store.ts",
        "src/transform.ts",
    }
    for citation in citations:
        source = sources[citation["path"]].decode().split("\n")
        assert source[citation["line"] - 1].strip() == citation["quote"]
    probed = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-of",
                "json",
                str(bundle / "video.mp4"),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    streams = {s["codec_type"]: s for s in probed["streams"]}
    assert (streams["video"]["width"], streams["video"]["height"]) == (WIDTH, HEIGHT)
    assert streams["audio"]["codec_name"] == "aac"

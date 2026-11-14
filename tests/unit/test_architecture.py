"""Architecture discovery, IR validation, narration, diagram and explainer-video tests.

Fixtures under tests/fixtures/architectures are locally authored synthetic source. They are
parsed as data and never imported or executed. The end-to-end tests use the real FFmpeg and
local speech engine and are skipped with a stated reason when either is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from repovox.analysis.github import Snapshot
from repovox.analysis.sandbox import execute
from repovox.media import explainer
from repovox.media.architecture import (
    Architecture,
    ArchitectureError,
    Citation,
    Component,
    Connection,
    Report,
    check,
    discover,
    validate,
)
from repovox.media.diagram import Diagram
from repovox.media.local import analyze_with_sources
from repovox.media.narration import FPS, Engine, NarrationError, detect
from repovox.media.raster import HEIGHT, WIDTH

FIXTURES = Path(__file__).parents[1] / "fixtures" / "architectures"
Loaded = tuple[dict[str, Any], dict[str, bytes], Report]


def analyzed(root: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    request: dict[str, Any] = {
        "snapshot": Snapshot(
            "example/demo",
            "https://github.com/example/demo",
            1,
            "example",
            "demo",
            True,
            "main",
            "a" * 40,
            "2026-11-14T00:00:00Z",
        ).data(),
        "snapshot_id": "11111111-1111-4111-8111-111111111111",
        "archive_hash": "b" * 64,
        "inputs": {},
    }
    payload: dict[str, Any] = {}
    for stage in (3, 4, 5, 6, 7, 8, 9):
        payload = execute(stage, root, request)
        request["inputs"][str(stage)] = payload
    sources = {
        f["path"]: (root / f["path"]).read_bytes()
        for f in payload["knowledge"]["coverage"]["files"]
        if f["status"] in {"parsed", "context"}
    }
    return payload, sources


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Loaded]:
    result: dict[str, Loaded] = {}
    for fixture in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        root = tmp_path_factory.mktemp(fixture.name) / "source"
        shutil.copytree(fixture, root)
        payload, sources = analyzed(root)
        result[fixture.name] = (payload, sources, discover(payload, sources))
    return result


def only(report: Report) -> Architecture:
    assert len(report.architectures) == 1
    return report.architectures[0]


def every_citation(architecture: Architecture) -> list[Citation]:
    found: list[Citation] = []
    for component in architecture.components:
        found += [*component.citations, *(layer.citation for layer in component.layers)]
    for connection in architecture.connections:
        found += connection.citations
    for flow in architecture.flows:
        for step in flow.steps:
            found += step.citations
    for group in (architecture.decisions, architecture.variants):
        for item in group:
            found += item.citations
    return found


def test_standard_gan_is_derived_from_source(loaded: dict[str, Loaded]) -> None:
    payload, sources, report = loaded["gan_standard"]
    validate(report, payload, sources)
    gan = only(report)
    assert report.explanation == "supported" and not report.rejected
    assert (gan.type, gan.level, gan.status, gan.variants) == ("gan", "model", "VERIFIED", ())
    parts = {c.id: c for c in gan.components}
    assert set(parts) == {
        "generator",
        "discriminator",
        "noise",
        "generated",
        "real",
        "loss_d",
        "opt_d",
        "loss_g",
        "opt_g",
    }
    assert parts["generator"].label == "Generator"
    assert [layer.text for layer in parts["generator"].layers] == [
        "Linear 100 -> 256",
        "LeakyReLU 0.2",
        "Linear 256 -> 512",
        "LeakyReLU 0.2",
        "Linear 512 -> 784",
        "Tanh",
    ]
    assert parts["discriminator"].layers[-1].type == "Sigmoid"
    assert parts["noise"].lines == ("latent size 100",)
    assert parts["loss_d"].lines == ("BCELoss",) and parts["opt_g"].lines[0] == "Adam"
    pairs = {(c.source, c.target, c.kind) for c in gan.connections}
    assert pairs == {
        ("noise", "generator", "data"),
        ("generator", "generated", "data"),
        ("generated", "discriminator", "data"),
        ("real", "discriminator", "data"),
        ("discriminator", "loss_d", "score"),
        ("loss_d", "opt_d", "gradient"),
        ("opt_d", "discriminator", "update"),
        ("discriminator", "loss_g", "score"),
        ("loss_g", "opt_g", "gradient"),
        ("opt_g", "generator", "update"),
    }
    flows = {flow.name: flow for flow in gan.flows}
    training = [step.text for step in flows["training"].steps]
    assert training.index("loss_d.backward() then opt_d.step() update Discriminator.") < (
        training.index("loss_g.backward() then opt_g.step() update Generator.")
    )
    assert flows["inference"].steps[0].citations[0].path == "sample.py"
    assert "torch.no_grad()" in flows["inference"].steps[0].text
    decisions = " ".join(fact.text for fact in gan.decisions)
    assert "discriminator is updated first" in decisions and "detached" in decisions
    assert {u.topic for u in gan.unresolved} == {"tensor shapes", "training outcome"}
    assert gan.inputs == ("noise", "real") and gan.outputs == ("generated",)


def test_every_citation_is_exact_verified_source(loaded: dict[str, Loaded]) -> None:
    for name in ("gan_standard", "gan_conditional", "cnn_classifier", "multi"):
        payload, sources, report = loaded[name]
        verified = {
            v["claim_id"] for v in payload["verification"]["verdicts"] if v["status"] == "verified"
        }
        for architecture in report.architectures:
            citations = every_citation(architecture)
            assert len(citations) > 15
            for citation in citations:
                lines = sources[citation.path].decode().split("\n")
                assert lines[citation.line - 1].strip() == citation.quote
                assert citation.claim_ids and set(citation.claim_ids) <= verified
                assert citation.permalink.endswith(
                    f"/{citation.path}#L{citation.line}-L{citation.line}"
                )
                assert "a" * 40 in citation.permalink


def test_conditional_and_convolutional_variants_need_code_evidence(
    loaded: dict[str, Loaded],
) -> None:
    gan = only(loaded["gan_conditional"][2])
    assert {(v.name, v.status) for v in gan.variants} == {
        ("conditional", "VERIFIED"),
        ("convolutional (DCGAN-style)", "INFERRED"),
    }
    parts = {c.id: c for c in gan.components}
    assert parts["condition"].label == "labels" and parts["noise"].lines == ("latent size 64",)
    assert parts["generator"].layers[1].text == "ConvTranspose2d 128 -> 64 k4 s1 p0"
    pairs = {(c.source, c.target) for c in gan.connections}
    assert {("condition", "generator"), ("condition", "discriminator")} <= pairs
    assert parts["loss_d"].lines == ("binary_cross_entropy_with_logits",)
    assert "inference flow" in {u.topic for u in gan.unresolved}
    assert [flow.name for flow in gan.flows] == ["training"]
    # The plain GAN has neither label path nor convolutions, so neither variant is claimed.
    assert only(loaded["gan_standard"][2]).variants == ()


def test_gan_mention_without_implementation_is_rejected(loaded: dict[str, Loaded]) -> None:
    payload, sources, report = loaded["gan_mention_only"]
    validate(report, payload, sources)
    assert report.explanation == "unsupported" and report.architectures == ()
    assert [(r.candidate, r.reason) for r in report.rejected] == [
        ("gan", "mention_without_implementation")
    ]
    mentioned = {m.path for m in report.rejected[0].mentions}
    assert {"README.md", "gan.py"} <= mentioned
    assert b"torch.randn" in sources["gan.py"] and b"GANConfig" in sources["gan.py"]


def test_non_gan_architecture_is_not_called_a_gan(loaded: dict[str, Loaded]) -> None:
    network = only(loaded["cnn_classifier"][2])
    assert (network.type, network.status) == ("supervised_network", "VERIFIED")
    assert [v.name for v in network.variants] == ["convolutional"]
    assert {c.id for c in network.components} == {
        "model",
        "input",
        "prediction",
        "loss",
        "optimizer",
    }
    assert {c.id: c for c in network.components}["loss"].lines == ("CrossEntropyLoss",)
    assert loaded["cnn_classifier"][2].rejected == ()


def test_multiple_architectures_in_one_repository(loaded: dict[str, Loaded]) -> None:
    payload, sources, report = loaded["multi"]
    validate(report, payload, sources)
    assert [a.type for a in report.architectures] == ["gan", "supervised_network"]
    assert report.architectures[0].scope == ("gan_models.py", "gan_train.py")
    assert report.architectures[1].scope == ("classifier.py",)
    assert "inference flow" in {u.topic for u in report.architectures[0].unresolved}


def test_ambiguous_architecture_is_reported_as_unsupported(loaded: dict[str, Loaded]) -> None:
    payload, sources, report = loaded["gan_incomplete"]
    validate(report, payload, sources)
    assert report.explanation == "unsupported" and report.architectures == ()
    assert [r.reason for r in report.rejected] == ["unbound_models"]
    assert "receives its models as parameters" in report.rejected[0].detail


def rebuild(report: Report, architecture: Architecture) -> Report:
    return report.model_copy(update={"architectures": (architecture,)})


def test_forged_architecture_elements_are_rejected(loaded: dict[str, Loaded]) -> None:
    payload, sources, report = loaded["gan_standard"]
    gan = only(report)
    parts = {c.id: c for c in gan.components}
    links = {c.id: c for c in gan.connections}
    real = parts["real"].citations[0]

    def swap(link: Connection, **changes: Any) -> Architecture:
        others = tuple(c for c in gan.connections if c.id != link.id)
        return gan.model_copy(update={"connections": (*others, link.model_copy(update=changes))})

    forged_component = Component(
        id="encoder",
        role="encoder",
        kind="module",
        label="Encoder",
        status="VERIFIED",
        anchors=("class Encoder",),
        citations=parts["generator"].citations,
    )
    invented_link = Connection(
        id="noise-to-discriminator",
        source="noise",
        target="discriminator",
        kind="data",
        label="noise in",
        phase="training",
        status="VERIFIED",
        anchors=("discriminator(", "z"),
        citations=links["real-to-discriminator"].citations,
    )
    generator = parts["generator"]
    extra_layer = generator.layers[0].model_copy(update={"index": 6, "type": "Conv2d"})
    cases = {
        "unsupported_element": [
            gan.model_copy(update={"components": (*gan.components, forged_component)}),
            gan.model_copy(update={"connections": (*gan.connections, invented_link)}),
            gan.model_copy(
                update={
                    "components": tuple(
                        c.model_copy(update={"layers": (*c.layers, extra_layer)})
                        if c.id == "generator"
                        else c
                        for c in gan.components
                    )
                }
            ),
        ],
        "unsupported_connection": [
            swap(links["real-to-discriminator"], target="critic"),
            swap(links["opt_g-to-generator"], source="generator"),
        ],
        "gan_core_missing": [
            swap(links["generator-to-generated"], source="generated", target="generator"),
            swap(links["real-to-discriminator"], target="generator"),
        ],
        "false_citation": [
            gan.model_copy(
                update={
                    "components": tuple(
                        c.model_copy(update={"citations": (real.model_copy(update=change),)})
                        if c.id == "real"
                        else c
                        for c in gan.components
                    )
                }
            )
            for change in (
                {"quote": "for real, _ in fabricated_loader:"},
                {"line": real.line + 1},
                {"file_sha256": "0" * 64},
                {"path": "missing.py"},
                {"permalink": "https://github.com/other/repo/blob/main/train.py#L1-L1"},
            )
        ],
        "unverified_claim": [
            gan.model_copy(
                update={
                    "components": tuple(
                        c.model_copy(update={"citations": (real.model_copy(update=change),)})
                        if c.id == "real"
                        else c
                        for c in gan.components
                    )
                }
            )
            for change in (
                {"claim_ids": ("claim-forged",)},
                {"claim_ids": parts["generator"].citations[0].claim_ids},
            )
        ],
        "unsupported_flow": [
            gan.model_copy(update={"outputs": ("images",)}),
            # Dropping the discriminator leaves flow steps pointing at nothing.
            gan.model_copy(
                update={"components": tuple(c for c in gan.components if c.id != "discriminator")}
                | {
                    "connections": tuple(
                        c for c in gan.connections if "discriminator" not in (c.source, c.target)
                    )
                }
            ),
        ],
    }
    for code, candidates in cases.items():
        for candidate in candidates:
            with pytest.raises(ArchitectureError) as raised:
                check(rebuild(report, candidate), payload, sources)
            assert raised.value.code == code, code
    relabelled = gan.model_copy(update={"title": "GAN: a better title"})
    check(rebuild(report, relabelled), payload, sources)
    with pytest.raises(ArchitectureError) as raised:
        validate(rebuild(report, relabelled), payload, sources)
    assert raised.value.code == "architecture_not_reproducible"


def test_unsupported_architecture_claims_are_rejected(loaded: dict[str, Loaded]) -> None:
    payload, sources, report = loaded["cnn_classifier"]
    network = only(report)
    as_gan = rebuild(report, network.model_copy(update={"type": "gan", "id": "gan-1"}))
    with pytest.raises(ArchitectureError) as raised:
        check(as_gan, payload, sources)
    assert raised.value.code == "gan_core_missing"
    mention_payload, mention_sources, mention_report = loaded["gan_mention_only"]
    claimed = mention_report.model_copy(
        update={
            "architectures": loaded["gan_standard"][2].architectures,
            "explanation": "supported",
        }
    )
    with pytest.raises(ArchitectureError) as raised:
        check(claimed, mention_payload, mention_sources)
    assert raised.value.code == "false_citation"
    with pytest.raises(ArchitectureError) as raised:
        check(
            mention_report.model_copy(update={"explanation": "supported"}),
            mention_payload,
            mention_sources,
        )
    assert raised.value.code == "explanation_mismatch"
    with pytest.raises(ArchitectureError) as raised:
        discover(mention_payload, {**mention_sources, "gan.py": b"class Generator: ...\n"})
    assert raised.value.code == "source_mismatch"


def test_narration_only_says_what_the_ir_holds(loaded: dict[str, Loaded]) -> None:
    gan = only(loaded["gan_conditional"][2])
    lines = explainer.narrate(gan)
    explainer.check_narration(lines, gan)
    sections = [line.section for line in lines]
    assert list(dict.fromkeys(sections)) == [
        "purpose",
        "components",
        "inputs and outputs",
        "flow",
        "decisions",
        "unknowns",
    ]
    text = " ".join(line.text for line in lines)
    assert "Variant: conditional." in text and "not established" in text
    assert all(line.citations for line in lines if line.status in {"VERIFIED", "INFERRED"})
    assert any(line.status == "UNRESOLVED" for line in lines)
    animated = [line for line in lines if line.connection_ids]
    assert len(animated) >= 8
    stranger = only(loaded["cnn_classifier"][2]).components[0].citations[0]
    forged = {
        "narration_false_citation": lines[0].model_copy(update={"citations": (stranger,)}),
        "narration_unsupported_element": lines[0].model_copy(
            update={"connection_ids": ("noise-to-discriminator",)}
        ),
        "narration_uncited": lines[0].model_copy(update={"citations": ()}),
        "narration_speech_mismatch": lines[0].model_copy(update={"spoken": "Trust me."}),
        "narration_not_reproducible": lines[0].model_copy(
            update={
                "text": "This GAN is state of the art.",
                "spoken": "This GAN is state of the art.",
            }
        ),
    }
    for code, line in forged.items():
        with pytest.raises(ArchitectureError) as raised:
            explainer.check_narration((line, *lines[1:]), gan)
        assert raised.value.code == code


def test_diagram_draws_only_ir_elements_and_animates(loaded: dict[str, Loaded]) -> None:
    for name in ("gan_standard", "gan_conditional", "cnn_classifier"):
        architecture = only(loaded[name][2])
        diagram = Diagram(architecture, "example/demo", "a" * 40)
        assert set(diagram.boxes) == {c.id for c in architecture.components}
        assert set(diagram.routes) == {c.id for c in architecture.connections}
        for points in diagram.routes.values():
            assert len(points) >= 2
            assert all(0 <= x <= WIDTH and 0 <= y <= HEIGHT for x, y in points)
            assert all(
                a[0] == b[0] or a[1] == b[1] for a, b in zip(points, points[1:], strict=False)
            )
        placed = list(diagram.boxes.values())
        for i, (ax, ay, aw, ah) in enumerate(placed):
            for bx, by, bw, bh in placed[i + 1 :]:
                assert ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay
    gan = only(loaded["gan_standard"][2])
    diagram = Diagram(gan, "example/demo", "a" * 40)
    assert "condition" not in diagram.boxes
    line = next(x for x in explainer.narrate(gan) if x.connection_ids)
    idle = diagram.base((), (), "CONTEXT", "Nothing highlighted.", None, 0, 2)
    active = diagram.base(
        line.component_ids, line.connection_ids, line.status, line.text, line.citations[0], 1, 2
    )
    assert idle.png() != active.png()
    first = diagram.animate(active, line.connection_ids, 0.0)
    second = diagram.animate(active, line.connection_ids, 0.25)
    assert first.startswith(b"\x89PNG") and first != second and first != active.png(1)


def git(repository: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Synthetic Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    ).stdout.strip()


def repository_from(fixture: str, target: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is not installed; pinned-commit test not run")
    shutil.copytree(FIXTURES / fixture, target)
    git(target, "init", "-q")
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "synthetic fixture")
    return target


def test_architecture_changes_across_pinned_commits(tmp_path: Path) -> None:
    repository = repository_from("gan_standard", tmp_path / "repository")
    url = "https://github.com/example/gan-fixture"
    first_sha = git(repository, "rev-parse", "HEAD")
    for name in ("models.py", "train.py", "sample.py"):
        path = repository / name
        body = path.read_bytes().replace(b"LATENT_DIM = 100", b"LATENT_DIM = 64")
        body = body.replace(
            b"            nn.Linear(256, 512),\n            nn.LeakyReLU(0.2),\n"
            b"            nn.Linear(512, IMAGE_DIM),\n            nn.Tanh(),",
            b"            nn.Linear(256, 512),\n            nn.BatchNorm1d(512),\n"
            b"            nn.LeakyReLU(0.2),\n            nn.Linear(512, IMAGE_DIM),\n"
            b"            nn.Tanh(),",
        )
        path.write_bytes(body)
    git(repository, "commit", "-q", "-am", "change latent size and add normalisation")
    second_sha = git(repository, "rev-parse", "HEAD")
    old_payload, old_sources = analyze_with_sources(repository, url, first_sha)
    new_payload, new_sources = analyze_with_sources(repository, url, second_sha)
    old, new = discover(old_payload, old_sources), discover(new_payload, new_sources)
    assert (old.commit_sha, new.commit_sha) == (first_sha, second_sha)

    def facts(report: Report) -> tuple[tuple[str, ...], list[str]]:
        parts = {c.id: c for c in only(report).components}
        return parts["noise"].lines, [layer.type for layer in parts["generator"].layers]

    assert facts(old) == (("latent size 100",), ["Linear", "LeakyReLU"] * 2 + ["Linear", "Tanh"])
    assert facts(new) == (
        ("latent size 64",),
        ["Linear", "LeakyReLU", "Linear", "BatchNorm1d", "LeakyReLU", "Linear", "Tanh"],
    )
    assert all(f"/blob/{second_sha}/" in c.permalink for c in every_citation(only(new)))
    # An IR pinned to one commit is not accepted as evidence about another.
    with pytest.raises(ArchitectureError) as raised:
        check(old, new_payload, new_sources)
    assert raised.value.code == "analysis_mismatch"
    relabelled = old.model_copy(
        update={"commit_sha": second_sha, "analysis_sha256": new.analysis_sha256}
    )
    with pytest.raises(ArchitectureError) as raised:
        check(relabelled, new_payload, new_sources)
    assert raised.value.code == "false_citation"


def media_tools() -> Engine:
    for name in ("ffmpeg", "ffprobe"):
        if shutil.which(name) is None:
            pytest.skip(f"{name} is not installed; architecture video test not run")
    try:
        return detect()
    except NarrationError:
        pytest.skip("no local speech engine installed; architecture video test not run")


def gray_frame(video: Path, seconds: float) -> bytes:
    return subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{seconds:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout


def test_unsupported_repository_gets_no_architecture_video(
    loaded: dict[str, Loaded], tmp_path: Path
) -> None:
    payload, sources, report = loaded["gan_mention_only"]
    manifest = explainer.explain(report, payload, sources, tmp_path / "architecture")
    published = tmp_path / "architecture" / "published"
    assert manifest["architecture_explanation"] == "unsupported"
    assert manifest["architectures"] == [] and manifest["narration_engine"] is None
    assert manifest["rejected"][0]["reason"] == "mention_without_implementation"
    assert sorted(p.name for p in published.iterdir()) == [
        "architecture-report.json",
        "manifest.json",
    ]
    stored = Report.model_validate_json((published / "architecture-report.json").read_bytes())
    assert stored == report and not list(published.rglob("*.mp4"))


def test_gan_architecture_explainer_video(loaded: dict[str, Loaded], tmp_path: Path) -> None:
    engine = media_tools()
    payload, sources, report = loaded["gan_conditional"]
    manifest = explainer.explain(report, payload, sources, tmp_path / "architecture", engine=engine)
    bundle = tmp_path / "architecture" / "published" / "gan-1"
    item = manifest["architectures"][0]
    assert not (tmp_path / "architecture" / "work").exists()
    assert manifest["model_inference"] == "none" and manifest["paid_services"] == "none"
    assert item["variants"] == [
        {"name": "conditional", "status": "VERIFIED"},
        {"name": "convolutional (DCGAN-style)", "status": "INFERRED"},
    ]
    stored = Architecture.model_validate_json((bundle / "architecture.json").read_bytes())
    assert stored == only(report)
    narration = json.loads((bundle / "narration.json").read_text(encoding="utf-8"))
    lines = explainer.narrate(stored)
    assert [n["text"] for n in narration] == [line.text for line in lines]
    frames = sum(n["frames"] for n in narration)
    assert item["media"]["video_frames"] == frames and item["animation_frames"] > len(lines)
    captions = (bundle / "captions.vtt").read_text(encoding="utf-8")
    assert captions.startswith("WEBVTT") and captions.count("-->") == len(lines)
    citations = json.loads((bundle / "citations.json").read_text(encoding="utf-8"))
    assert len(citations) == item["citations"] and len(citations) >= 30
    elements = {c.id for c in stored.components} | {c.id for c in stored.connections}
    assert elements <= {c["element"] for c in citations}
    for citation in citations:
        source = sources[citation["path"]].decode().split("\n")
        assert source[citation["line"] - 1].strip() == citation["quote"]
    for name, recorded in item["artifacts"].items():
        body = (bundle / name).read_bytes()
        assert len(body) == recorded["bytes"]
        assert __import__("hashlib").sha256(body).hexdigest() == recorded["sha256"]
    assert len(list(bundle.glob("key*.png"))) == len(lines)

    video = bundle / "video.mp4"
    probed = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(video),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    streams = {s["codec_type"]: s for s in probed["streams"]}
    assert streams["video"]["codec_name"] == "h264" and streams["audio"]["codec_name"] == "aac"
    assert (streams["video"]["width"], streams["video"]["height"]) == (WIDTH, HEIGHT)
    assert int(streams["video"]["nb_read_frames"]) == frames
    assert abs(float(probed["format"]["duration"]) - frames / FPS) < 0.1
    loud = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(video), "-af", "volumedetect", "-f", "null", "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stderr
    assert float(loud.split("max_volume:")[1].split("dB")[0]) > -30

    # Visual: the diagram really moves while a connection is narrated, stays still when no
    # connection is active, and shows a different highlight for a different narration line.
    moving = next(n for n in narration if n["connection_ids"] and n["frames"] >= 60)
    still = next(n for n in narration if not n["connection_ids"] and n["frames"] >= 60)
    start = moving["start_frame"] / FPS
    assert gray_frame(video, start + 0.4) != gray_frame(video, start + 1.0)
    pause = still["start_frame"] / FPS
    one, two = gray_frame(video, pause + 0.4), gray_frame(video, pause + 1.0)
    assert len(one) == WIDTH * HEIGHT
    assert sum(a != b for a, b in zip(one, two, strict=True)) < WIDTH * HEIGHT // 500
    assert sum(a != b for a, b in zip(one, gray_frame(video, start + 0.4), strict=True)) > 2000

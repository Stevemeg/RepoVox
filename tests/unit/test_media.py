"""Grounded storyboard, narration assembly, raster and end-to-end video tests.

Fixtures are locally authored synthetic source. The end-to-end test uses the real FFmpeg and
the real local speech engine; it is skipped with a stated reason when either is not installed.
"""

import io
import json
import shutil
import struct
import subprocess
import wave
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from repovox.analysis.common import AnalysisError
from repovox.analysis.github import Snapshot
from repovox.analysis.sandbox import execute
from repovox.media import raster
from repovox.media.local import analyze
from repovox.media.narration import (
    FPS,
    Engine,
    NarrationError,
    Speech,
    assemble,
    detect,
    read_wave,
    synthesize,
)
from repovox.media.render import RenderError, produce
from repovox.media.storyboard import (
    GroundingError,
    Storyboard,
    build,
    check_grounding,
    display,
    speakable,
    validate,
)

FILES = {
    "service/app.py": (
        b"from fastapi import FastAPI\n"
        b"from service.store import Store\n\n"
        b"app = FastAPI()\n\n\n"
        b"def handle(request, store):\n"
        b"    record = store.load(request)\n"
        b"    return record\n\n\n"
        b'if __name__ == "__main__":\n'
        b"    handle(1, Store())\n"
    ),
    "service/store.py": (
        b"class Base:\n"
        b"    def load(self, key):\n"
        b"        return key\n\n\n"
        b"class Store(Base):\n"
        b"    def save(self, key, value):\n"
        b"        self.key = key\n"
        b"        return value\n"
    ),
    "web/view.ts": (
        b"export function render(name: string): string {\n"
        b"  const label = name.trim();\n"
        b"  return label;\n"
        b"}\n"
    ),
}


def payload_for(root: Path, files: dict[str, bytes] = FILES) -> dict[str, Any]:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
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
            "2026-11-13T00:00:00Z",
        ).data(),
        "snapshot_id": "11111111-1111-4111-8111-111111111111",
        "archive_hash": "b" * 64,
        "inputs": {},
    }
    result: dict[str, Any] = {}
    for stage in (3, 4, 5, 6, 7, 8, 9):
        result = execute(stage, root, request)
        request["inputs"][str(stage)] = result
    return result


@pytest.fixture(scope="module")
def payload(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return payload_for(tmp_path_factory.mktemp("source"))


@pytest.fixture(scope="module")
def board(payload: dict[str, Any]) -> Storyboard:
    return build(payload)


def test_storyboard_is_deterministic_and_fully_cited(
    payload: dict[str, Any], board: Storyboard
) -> None:
    assert build(payload) == board
    validate(board, payload)
    verdicts = {v["claim_id"]: v["status"] for v in payload["verification"]["verdicts"]}
    valid = {e["id"] for e in payload["evidence"]["items"] if e["validation_status"] == "valid"}
    kinds = [scene.type for scene in board.scenes]
    assert kinds[0] == "title" and kinds[-1] == "summary"
    assert {"stack", "architecture", "flow", "code"} <= set(kinds)
    technical = 0
    for scene in board.scenes:
        assert scene.claim_ids and set(scene.evidence_ids) <= valid
        for sentence in scene.sentences:
            if sentence.technical:
                technical += 1
                assert sentence.claim_ids and sentence.evidence_ids
                assert all(verdicts[c] in {"verified", "inferred"} for c in sentence.claim_ids)
            else:
                assert not sentence.claim_ids and sentence.uncertainty == "none"
    assert technical >= 6


def test_narrated_facts_come_from_the_analyzed_source(board: Storyboard) -> None:
    text = " ".join(s.text for scene in board.scenes for s in scene.sentences)
    assert "service/app.py contains a Python main guard" in text
    assert "An import of fastapi is observed in service/app.py" in text
    assert "Store inherits from Base" in text
    assert "purpose of the project is not inferred" in text
    code = [scene for scene in board.scenes if scene.type == "code"]
    assert code and code[0].excerpt is not None
    assert code[0].excerpt.lines[0] == "def handle(request, store):"
    assert code[0].excerpt.file_sha256 in {
        __import__("hashlib").sha256(body).hexdigest() for body in FILES.values()
    }


def mutate(board: Storyboard, scene_index: int, **changes: Any) -> Storyboard:
    scenes = list(board.scenes)
    scenes[scene_index] = scenes[scene_index].model_copy(update=changes)
    return board.model_copy(update={"scenes": tuple(scenes)})


def test_forged_storyboards_are_rejected(payload: dict[str, Any], board: Storyboard) -> None:
    position = next(i for i, s in enumerate(board.scenes) if s.type == "code")
    scene = board.scenes[position]
    sentence = scene.sentences[0]
    assert scene.excerpt is not None
    forged = {
        "unverified_claim": mutate(
            board,
            position,
            claim_ids=("claim-forged",),
            sentences=(sentence.model_copy(update={"claim_ids": ("claim-forged",)}),),
        ),
        "uncited_technical_sentence": mutate(
            board,
            position,
            sentences=(sentence.model_copy(update={"claim_ids": (), "evidence_ids": ()}),),
        ),
        "invalid_evidence": mutate(
            board, position, evidence_ids=(board.scenes[0].evidence_ids[0],)
        ),
        "excerpt_mismatch": mutate(
            board,
            position,
            excerpt=scene.excerpt.model_copy(update={"lines": ("def handle(): os.system()",)}),
        ),
        "speech_text_mismatch": mutate(
            board,
            position,
            sentences=(sentence.model_copy(update={"spoken": "Something else entirely."}),),
        ),
        "analysis_mismatch": board.model_copy(update={"analysis_sha256": "0" * 64}),
    }
    for code, candidate in forged.items():
        with pytest.raises(GroundingError) as raised:
            check_grounding(candidate, payload)
        assert raised.value.code == code
    reworded = mutate(
        board,
        0,
        sentences=(
            board.scenes[0]
            .sentences[0]
            .model_copy(update={"text": "It is fast.", "spoken": "It is fast."}),
            *board.scenes[0].sentences[1:],
        ),
    )
    check_grounding(reworded, payload)  # Structurally cited, but not the deterministic output.
    with pytest.raises(GroundingError) as raised:
        validate(reworded, payload)
    assert raised.value.code == "storyboard_not_reproducible"


def test_unsupported_or_invalid_material_is_never_narrated(
    payload: dict[str, Any], board: Storyboard
) -> None:
    cited = {c for scene in board.scenes for c in scene.claim_ids}
    downgraded = deepcopy(payload)
    for verdict in downgraded["verification"]["verdicts"]:
        if verdict["claim_id"] in cited:
            verdict["status"] = "unsupported"
    for claim in downgraded["knowledge"]["claims"]:
        if claim["id"] in cited:
            claim["status"] = "unsupported"
    try:
        rebuilt = build(downgraded)
    except GroundingError as error:
        assert error.code == "insufficient_evidence"
    else:
        assert not cited & {c for scene in rebuilt.scenes for c in scene.claim_ids}
    invalid = deepcopy(payload)
    for item in invalid["evidence"]["items"]:
        item["validation_status"] = "invalid"
    with pytest.raises(GroundingError) as raised:
        build(invalid)
    assert raised.value.code == "insufficient_evidence"


@pytest.mark.parametrize("value", [{}, {"knowledge": {}}, {"verification": {"verdicts": []}}])
def test_malformed_payload_is_rejected_before_output(value: dict[str, Any]) -> None:
    with pytest.raises(GroundingError) as raised:
        build(value)
    assert raised.value.code == "invalid_analysis_payload"


def test_repository_text_is_only_data() -> None:
    hostile = "a/b/$(rm -rf ~)`id`;|&<script>\x00‮\n.py"
    spoken = speakable(hostile)
    assert all(c.isalnum() or c in " .,;:'-" for c in spoken)
    shown = display(hostile, 30)
    assert len(shown) <= 30 and all(32 <= ord(c) < 127 for c in shown)
    assert display("x" * 50, 10) == "xxxxxxx..."
    assert speakable("apps/api/pkg/mod_one.py") == "pkg slash mod one dot py"


def test_frames_are_valid_png_and_overflow_fails(board: Storyboard) -> None:
    canvas = raster.base(board, board.scenes[0], 0)
    image = raster.frame(canvas, board.scenes[0].sentences[0])
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", image[16:24]) == (1280, 720)
    assert image != raster.frame(canvas, board.scenes[0].sentences[1])
    with pytest.raises(raster.LayoutError):
        raster.Canvas().text(64, 64, "x" * 200, 2)
    with pytest.raises(raster.LayoutError):
        raster.wrap("word " * 200, 96, 4)
    for scene_position, scene in enumerate(board.scenes):
        base = raster.base(board, scene, scene_position)
        for sentence in scene.sentences:
            raster.frame(base, sentence)


def tone(seconds: float, rate: int = 22050) -> Speech:
    return Speech(rate, struct.pack("<h", 4000) * round(seconds * rate))


def test_narration_assembly_is_frame_exact() -> None:
    parts = [tone(1.0), tone(2.37), tone(0.5)]
    audio, timings = assemble(parts)
    with wave.open(io.BytesIO(audio), "rb") as source:
        assert (source.getnchannels(), source.getsampwidth(), source.getframerate()) == (
            1,
            2,
            22050,
        )
        samples = source.getnframes()
    total = timings[-1].start_frame + timings[-1].frames
    assert samples == total * 22050 // FPS
    assert [t.start_frame for t in timings] == [
        0,
        timings[0].frames,
        timings[0].frames + timings[1].frames,
    ]
    for part, timing in zip(parts, timings, strict=True):
        assert timing.frames / FPS >= part.seconds + 0.35
        assert timing.frames / FPS < part.seconds + 0.35 + 1 / FPS + 1e-9
    with pytest.raises(NarrationError):
        assemble([tone(1.0), tone(1.0, 16000)])
    with pytest.raises(NarrationError):
        assemble([])


def test_speech_input_and_format_are_validated(tmp_path: Path) -> None:
    engine = Engine("windows-sapi", Path("unused"))
    for text in ["", "line\nbreak", "café", "x" * 601]:
        with pytest.raises(NarrationError) as raised:
            synthesize(engine, text, tmp_path, "speech")
        assert raised.value.code == "narration_text_rejected"
    assert not list(tmp_path.iterdir())
    with pytest.raises(NarrationError):
        read_wave(b"not a wave file")
    with pytest.raises(NarrationError) as raised:
        synthesize(Engine("unknown-engine", Path("unused")), "Hello.", tmp_path, "speech")
    assert raised.value.code == "narration_engine_unavailable"


def test_local_analysis_rejects_unsafe_arguments(tmp_path: Path) -> None:
    url = "https://github.com/example/demo"
    for revision, paths in [("HEAD; rm", ()), ("--upload-pack=x", ()), ("HEAD", ("../x",))]:
        with pytest.raises(AnalysisError):
            analyze(tmp_path, url, revision, paths)
    with pytest.raises(AnalysisError):
        analyze(tmp_path, "https://example.com/a/b")
    with pytest.raises(AnalysisError):
        analyze(tmp_path / "missing", url)


def media_tools() -> Engine:
    for name in ("ffmpeg", "ffprobe", "git"):
        if shutil.which(name) is None:
            pytest.skip(f"{name} is not installed; end-to-end media test not run")
    try:
        return detect()
    except NarrationError:
        pytest.skip("no local speech engine installed; end-to-end media test not run")


def test_failed_narration_publishes_nothing(payload: dict[str, Any], tmp_path: Path) -> None:
    media_tools()
    output = tmp_path / "run"
    with pytest.raises(NarrationError):
        produce(payload, output, engine=Engine("espeak-ng", tmp_path / "missing-binary"))
    assert not (output / "published").exists()
    with pytest.raises(RenderError):
        produce(payload, output)  # A used directory is never reopened.
    with pytest.raises(RenderError):
        produce(payload, Path("relative-run"))


def test_local_repository_to_narrated_video(tmp_path: Path) -> None:
    engine = media_tools()
    repository = tmp_path / "repository"
    repository.mkdir()
    for name, body in FILES.items():
        path = repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        ).stdout.strip()

    git("init", "-q")
    git("add", "-A")
    git(
        "-c",
        "user.name=Synthetic Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "synthetic fixture",
    )
    sha = git("rev-parse", "HEAD")
    payload = analyze(repository, "https://github.com/example/demo")
    assert payload["knowledge"]["repository"]["commit_sha"] == sha
    video = produce(payload, tmp_path / "run", engine=engine, source_note="local-git-archive")
    bundle = video.parent
    assert video.is_file() and video.stat().st_size > 10_000 and bundle.name == "published"
    assert not (tmp_path / "run" / "work").exists()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    narration = json.loads((bundle / "narration.json").read_text(encoding="utf-8"))
    stored = Storyboard.model_validate_json((bundle / "storyboard.json").read_bytes())
    validate(stored, payload)
    frames = sum(item["frames"] for item in narration)
    assert manifest["commit_sha"] == sha and manifest["media"]["video_frames"] == frames
    assert manifest["model_inference"] == "none" and manifest["paid_services"] == "none"
    assert len(narration) == manifest["sentences"] == sum(len(s.sentences) for s in stored.scenes)
    assert all(item["speech_seconds"] > 0.2 for item in narration)
    captions = (bundle / "captions.vtt").read_text(encoding="utf-8")
    assert captions.startswith("WEBVTT") and captions.count("-->") == len(narration)
    # Independent check of the published file, separate from the renderer's own validation.
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
    assert int(streams["video"]["nb_read_frames"]) == frames
    assert abs(float(probed["format"]["duration"]) - frames / FPS) < 0.1
    loud = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(video), "-af", "volumedetect", "-f", "null", "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stderr
    peak = float(loud.split("max_volume:")[1].split("dB")[0])
    assert peak > -30  # Decoded audio contains speech-level signal, not silence.

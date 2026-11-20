"""Technical pronunciation, the local neural voice seam, layered animated architecture frames
and the scaled encode limit (ADR-0031).

Every repository here is locally authored synthetic source. The neural voice is a stand-in that
records what it is asked to say; no model is downloaded or loaded. The encode test runs the
real FFmpeg and is skipped with a stated reason where FFmpeg is not installed.
"""

import io
import json
import math
import shutil
import struct
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from repovox.core.config import Settings
from repovox.media import stages
from repovox.media.architecture import Citation, Component
from repovox.media.diagram import AREA_BOTTOM, AREA_TOP, Diagram, classify
from repovox.media.narration import FPS, Speech, Timing
from repovox.media.pronunciation import LIMIT, pronounce
from repovox.media.speech import (
    KokoroOnnxSynthesizer,
    SpeechCache,
    audio_text,
    voice_from_settings,
    voice_record,
)
from repovox.media.storyboard import speakable
from test_engineering_story import STRONG, Shape, shape

SETTINGS: dict[str, Any] = {
    "database_url": "postgresql+psycopg://rv_app:p@localhost/repovox",
    "session_secret": "x" * 40,
    "storage_access_key": "a",
    "storage_secret_key": "s",
    "environment": "development",
    "dev_auth": True,
}


@pytest.fixture(scope="module")
def strong(tmp_path_factory: pytest.TempPathFactory) -> Shape:
    return shape(tmp_path_factory.mktemp("strong"), STRONG)


@pytest.fixture(scope="module")
def fullstack(tmp_path_factory: pytest.TempPathFactory) -> Shape:
    return shape(tmp_path_factory.mktemp("fullstack"), {}, fixture="fullstack_web")


@pytest.fixture
def assets(tmp_path: Path) -> tuple[str, str]:
    model, voices = tmp_path / "kokoro-v1.0.onnx", tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"synthetic model placeholder")
    voices.write_bytes(b"synthetic voices placeholder")
    return str(model), str(voices)


def tone(seconds: float = 0.6, rate: int = 24000) -> list[float]:
    return [0.4 * math.sin(2 * math.pi * 220 * i / rate) for i in range(int(seconds * rate))]


class RecordingKokoro:
    """Stands in for `kokoro_onnx.Kokoro`; records every text it is asked to say."""

    said: list[str] = []
    sessions: list[Any] = []

    def __init__(self, model: str, voices: str) -> None:
        self.model, self.voices = model, voices

    @classmethod
    def from_session(cls, session: Any, voices: str) -> "RecordingKokoro":
        cls.sessions.append(session)
        return cls(session.path, voices)

    def create(self, text: str, voice: str, speed: float, lang: str) -> Any:
        RecordingKokoro.said.append(text)
        return tone(), 24000


def kokoro(assets: tuple[str, str], **kwargs: Any) -> KokoroOnnxSynthesizer:
    loader = lambda: SimpleNamespace(Kokoro=RecordingKokoro)  # noqa: E731
    return KokoroOnnxSynthesizer(Path(assets[0]), Path(assets[1]), loader=loader, **kwargs)


# ---------------------------------------------------------------- 1. technical pronunciation


@pytest.mark.parametrize(
    "written,spoken",
    [
        ("FastAPI", "Fast Eh P I."),
        ("PostgreSQL", "Postgres Q L."),
        ("SQLite", "S Q Lite."),
        ("PyTorch", "Pie Torch."),
        ("NumPy", "Num Pie."),
        ("TSX", "T S X."),
        ("JSX", "J S X."),
        ("README", "Read me."),
        ("JSON", "Jason."),
        ("YAML", "Yammel."),
        ("OAuth", "Oh Auth."),
        ("API", "Eh P I."),
        ("URL", "U R L."),
        ("CLI", "C L I."),
        ("SDK", "S D K."),
        ("SQL", "S Q L."),
        ("UUID", "U U I D."),
        ("HTTP", "H T T P."),
        ("HTTPS", "H T T P S."),
        ("CI/CD", "C I C D."),
        ("LLM", "L L M."),
        ("GAN", "G Eh N."),
        ("VAE", "V Eh E."),
        ("MRI", "M R I."),
        ("UI/UX", "U I U X."),
        ("UI", "U I."),
        ("UX", "U X."),
    ],
)
def test_acronyms_and_libraries_have_their_spoken_form(written: str, spoken: str) -> None:
    assert pronounce(written) == spoken


@pytest.mark.parametrize(
    "written,spoken",
    [
        (
            "backend/app/services/inputs.py declares parse_inputs.",
            "inputs dot pie in backend app services declares parse inputs.",
        ),
        (
            "build_prompt calls getApiUrl on VectorStore.",
            "build prompt calls get Eh P I U R L on Vector Store.",
        ),
        ("MedSynth Guard v0.6.0 ships.", "Med Synth Guard version 0 point 6 point 0 ships."),
        ("See frontend/src/App.tsx:12 now.", "See App dot T S X in frontend src, line 12 now."),
        (
            "This is the story of synthetic/synthetic-data at pinned commit 8e8733505b61.",
            "This is the story of synthetic synthetic data at pinned commit.",
        ),
        (
            "It asserts settings.port == 5100 (default).",
            "It asserts settings port equals 5100, default.",
        ),
        (
            "README.md and package.json, e.g. the S3 IDs.",
            "Read me dot markdown and package dot Jason, for example, the S 3 I Ds.",
        ),
        ("AUTH_MODE=development is local.", "auth mode equals development is local."),
        ("The 10,000-fact cap; see ADR-0019.", "The 10,000-fact cap, see Eh D R 0019."),
        ("Docs live at https://example.test/a?b=c today", "Docs live at a web link today."),
    ],
)
def test_identifiers_paths_versions_and_hashes_are_read_as_words(written: str, spoken: str) -> None:
    assert pronounce(written) == spoken


def test_pronunciation_is_pure_ascii_and_never_spells_a_slash_or_underscore() -> None:
    text = "frontend/src/features/x_y/Thing.tsx calls snake_case_name and CamelName -- twice"
    said = pronounce(text)
    assert said == pronounce(text)  # deterministic
    assert all(32 <= ord(c) < 127 for c in said)
    assert "/" not in said and "_" not in said and "slash" not in said
    assert said.endswith(".") and ",," not in said and " ," not in said


def test_audio_text_pronounces_the_caption_or_the_ir_spoken_form() -> None:
    caption = "backend/app/services/inputs.py imports FastAPI."
    assert audio_text(caption, speakable(caption)) == pronounce(caption)  # the whole path
    worded = "The generator is backpropagated."  # an IR role name, not the caption's words
    assert audio_text("loss_g.backward() then opt_g.step() update G.", worded) == pronounce(worded)
    long = "API " * 200
    assert audio_text(long, "short spoken form") == pronounce("short spoken form")
    assert len(audio_text(long, speakable(long[:300]))) <= LIMIT


# ------------------------------------------- 2. the voice hears it, captions keep exact text


def test_the_voice_hears_pronunciation_while_captions_and_citations_stay_exact(
    strong: Shape, assets: tuple[str, str], tmp_path: Path
) -> None:
    storyboard = stages.storyboard_stage(strong.payload, strong.story, strong.report)
    script = stages.narration_stage(strong.payload, storyboard, strong.sources)  # Stage 11
    sentences = json.loads(script)
    RecordingKokoro.said.clear()
    speech = stages.tts_stage(storyboard, script, kokoro(assets), tmp_path)
    expected = [audio_text(s["text"], s["spoken"]) for s in sentences]
    assert RecordingKokoro.said == expected
    assert any("dot pie" in said for said in RecordingKokoro.said)  # ledger/matching.py
    assert all(".py" not in said and "/" not in said for said in RecordingKokoro.said)
    # The approved script, the storyboard and every citation are exactly what Stage 11 checked.
    assert stages.narration_stage(strong.payload, storyboard, strong.sources) == script
    assert all(s["spoken"] == speakable(s["text"]) for s in sentences)
    frames = stages.unbundle(stages.render_stage(storyboard, script, speech))
    captions = frames["captions.vtt"].decode()
    assert all(s["text"] in captions for s in sentences)
    assert any(".py" in s["text"] for s in sentences) and ".py" in captions
    assert json.loads(stages.unbundle(speech)["voice.json"])["tts_provider"] == "kokoro_onnx"


def test_kokoro_threads_open_one_bounded_session(
    assets: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[Any] = []

    class Runtime:
        @staticmethod
        def SessionOptions() -> Any:  # noqa: N802 - mirrors onnxruntime
            return SimpleNamespace()

        @staticmethod
        def InferenceSession(path: str, options: Any, providers: list[str]) -> Any:  # noqa: N802
            built.append((options, providers))
            return SimpleNamespace(path=path)

    RecordingKokoro.sessions.clear()
    voice = kokoro(assets, threads=3, runtime=lambda: Runtime)
    voice.engine()
    options, providers = built[0]
    assert (options.intra_op_num_threads, options.inter_op_num_threads) == (3, 1)
    assert providers == ["CPUExecutionProvider"] and len(RecordingKokoro.sessions) == 1
    settings = Settings(
        **SETTINGS,
        tts_provider="kokoro_onnx",
        tts_model_path=assets[0],
        tts_voices_path=assets[1],
        tts_threads=3,
    )
    # The thread count reaches the voice the settings choose; loading is tested just above.
    monkeypatch.setattr(KokoroOnnxSynthesizer, "engine", lambda self: object())
    chosen = voice_from_settings(settings, loader=lambda: SimpleNamespace(Kokoro=RecordingKokoro))
    assert isinstance(chosen, KokoroOnnxSynthesizer) and chosen.threads == 3
    assert voice_record(chosen)["tts_provider"] == "kokoro_onnx"


def test_the_speech_library_scratch_is_used_only_while_kokoro_runs(
    assets: tuple[str, str], tmp_path: Path
) -> None:
    import tempfile

    seen: list[str] = []

    class Phonemizing(RecordingKokoro):
        def __init__(self, model: str, voices: str) -> None:
            seen.append(tempfile.gettempdir())  # where a library copy would be made
            super().__init__(model, voices)

        def create(self, text: str, voice: str, speed: float, lang: str) -> Any:
            seen.append(tempfile.gettempdir())
            return super().create(text, voice, speed, lang)

    before = tempfile.gettempdir()
    library = tmp_path / "speech-library"
    library.mkdir()
    voice = KokoroOnnxSynthesizer(
        Path(assets[0]),
        Path(assets[1]),
        loader=lambda: SimpleNamespace(Kokoro=Phonemizing),
        library_dir=library,
    )
    voice.speak("Fast Eh P I.", tmp_path, "s000")
    assert seen == [str(library), str(library)] and tempfile.gettempdir() == before
    settings = Settings(
        **SETTINGS,
        tts_model_path=assets[0],
        tts_voices_path=assets[1],
        tts_library_dir="/run/repovox-speech",
    )
    assert settings.tts_library_dir == "/run/repovox-speech"
    for outside in ("/tmp", "/tmp/speech", "/run/../tmp", "relative"):
        with pytest.raises(ValueError):
            Settings(**SETTINGS, tts_library_dir=outside)  # /tmp stays noexec


class CountingVoice:
    name = "counting-voice"

    def __init__(self) -> None:
        self.calls = 0

    def speak(self, text: str, scratch: Path, stem: str) -> Speech:
        self.calls += 1
        values = tone(0.3 + len(text) / 2000)
        return Speech(24000, struct.pack(f"<{len(values)}h", *(round(v * 32767) for v in values)))


def test_narration_stage_speaks_ahead_and_speech_stage_reuses_it(
    strong: Shape, tmp_path: Path
) -> None:
    storyboard = stages.storyboard_stage(strong.payload, strong.story, strong.report)
    script = stages.narration_stage(strong.payload, storyboard, strong.sources)
    count = len(json.loads(script))
    voice, cache = CountingVoice(), SpeechCache()
    assert stages.prewarm(storyboard, script, voice, tmp_path, cache, 0) == 0  # off
    assert stages.prewarm(storyboard, script, voice, tmp_path, cache, 300) == count
    assert voice.calls == count
    warm = stages.tts_stage(storyboard, script, voice, tmp_path, cache=cache)
    assert voice.calls == count  # Stage 12 spoke nothing again.
    cold = stages.tts_stage(storyboard, script, CountingVoice(), tmp_path)
    assert warm == cold  # A cached sentence is the sentence the voice would say.
    small = SpeechCache(limit_bytes=1)
    small.put(voice, "x", Speech(24000, b"\0\1" * 100))
    assert small.get(voice, "x") is None and small.size == 0  # bounded


# --------------------------------------------------- 3. layered animated architecture frames


def component(identity: str, kind: str, group: str, path: str, role: str = "") -> Component:
    citation = Citation(
        path=path,
        file_sha256="a" * 64,
        line=1,
        quote="x",
        claim_ids=("claim-1",),
        permalink="https://github.com/example/demo/blob/" + "a" * 40 + f"/{path}#L1",
    )
    return Component(
        id=identity,
        role=role or kind,
        kind=kind,
        label=identity,
        status="VERIFIED",
        anchors=("a",),
        citations=(citation,),
        group=group,
    )


@pytest.mark.parametrize(
    "made,tier,badge",
    [
        (("page", "source_file", "frontend", "frontend/page.tsx"), "client", "UI"),
        (("app", "source_file", "backend", "backend/app.py"), "api", "API"),
        (("route", "endpoint", "backend/routes.py", "backend/routes.py"), "api", "API"),
        (("svc", "function", "backend/services/x.py", "backend/services/x.py"), "service", "SVC"),
        (("gen", "module", "models/gan.py", "models/gan.py"), "platform", "ML"),
        (("db", "database", "external", "backend/db.py"), "platform", "DATA"),
        (("http", "http_client", "external", "web/api.ts"), "platform", "EXT"),
        (
            ("job", "function", "backend/workers/tasks.py", "backend/workers/tasks.py"),
            "platform",
            "SVC",
        ),
    ],
)
def test_components_are_tiered_from_what_the_ir_records(
    made: tuple[str, str, str, str], tier: str, badge: str
) -> None:
    assert classify(component(*made)) == (tier, badge)


def test_layered_topology_is_inside_its_bands_and_never_overlaps(fullstack: Shape) -> None:
    assert fullstack.report is not None
    architecture = fullstack.report.architectures[0]
    diagram = Diagram(architecture, "example/demo", "a" * 40, architecture.views[0])
    assert [t for t, _ in diagram.bands] == ["client", "api", "service", "platform"]
    placed = list(diagram.boxes.values())
    for i, (ax, ay, aw, ah) in enumerate(placed):
        assert 182 <= ax and ax + aw <= 1234 and AREA_TOP <= ay and ay + ah <= AREA_BOTTOM
        for bx, by, bw, bh in placed[i + 1 :]:
            assert ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay
    for identity, (x, y, w, h) in diagram.boxes.items():
        group = diagram.parts[identity].group
        assert any(
            label == group and lx <= x and x + w <= lx + lw and ly <= y and y + h <= ly + lh
            for label, (lx, ly, lw, lh) in diagram.lanes
        )
        tier = diagram.tier_of[identity]
        _, (bx, by, bw, bh) = next(b for b in diagram.bands if b[0] == tier)
        assert by <= y and y + h <= by + bh
    bands = [area for _, area in diagram.bands]
    assert all(a[1] + a[3] <= b[1] for a, b in zip(bands, bands[1:], strict=False))


def changed(a: bytes, b: bytes) -> bool:
    return a != b and a.startswith(b"\x89PNG\r\n\x1a\n") and b.startswith(b"\x89PNG\r\n\x1a\n")


def test_reveal_spotlight_and_flow_frames_actually_move(fullstack: Shape) -> None:
    assert fullstack.report is not None
    architecture = fullstack.report.architectures[0]
    view = architecture.views[0]
    diagram = Diagram(architecture, "example/demo", "a" * 40, view)
    every = tuple(view.component_ids)
    link = next(c for c in architecture.connections if c.id in view.connection_ids)
    one = (link.source,)

    def frames(components: tuple[str, ...], connections: tuple[str, ...], mode: str) -> list[bytes]:
        return stages.diagram_frames(
            diagram,
            components,
            connections,
            "VERIFIED",
            "Caption.",
            link.citations[0],
            0,
            9,
            FPS * 6,
            mode=mode,
            step=(2, 5) if connections else None,
        )

    reveal = frames(every, (), "reveal")
    assert len(reveal) == (len(diagram.bands) - 1) * stages.REVEAL_STEPS + 1
    assert all(changed(a, b) for a, b in zip(reveal[::2], reveal[2::2], strict=False))
    spotlight = frames(one, (), "spotlight")
    assert len(spotlight) == len(stages.SPOTLIGHT) + 1
    assert all(changed(a, b) for a, b in zip(spotlight, spotlight[1:], strict=False))
    flow = frames((), (link.id,), "flow")
    assert len(flow) == stages.animation_count(FPS * 6)
    assert sum(changed(a, b) for a, b in zip(flow, flow[1:], strict=False)) >= len(flow) - 2
    assert frames(one, (), "still") == [spotlight[-1]]  # the held image is the final still
    # Nothing narrated means nothing is spotlit or dimmed: one plain still.
    assert len(frames((), (), "spotlight")) == 1


def test_a_long_story_never_exceeds_its_animation_budget(fullstack: Shape) -> None:
    assert fullstack.report is not None
    architecture = fullstack.report.architectures[0]
    diagram = Diagram(architecture, "example/demo", "a" * 40, architecture.views[0])
    link = architecture.connections[0]
    images = stages.diagram_frames(
        diagram,
        (),
        (link.id,),
        "VERIFIED",
        "Caption.",
        None,
        0,
        1,
        FPS * 60,
        mode="flow",
        budget=10,
    )
    assert len(images) == 1  # Over budget: drawn as its final still image.


def test_walkthrough_diagram_scenes_are_drawn_never_text_slides(
    fullstack: Shape, tmp_path: Path
) -> None:
    storyboard = stages.storyboard_stage(fullstack.payload, fullstack.story, fullstack.report)
    board = stages.load_board(storyboard)
    kinds = {scene.type: scene.diagram for scene in board.scenes}
    assert kinds.get("architecture") is True and kinds.get("workflow") is True
    script = stages.narration_stage(fullstack.payload, storyboard, fullstack.sources)
    speech = stages.tts_stage(storyboard, script, CountingVoice(), tmp_path)
    images = stages.unbundle(stages.render_stage(storyboard, script, speech))
    timings = stages.timings_of(stages.unbundle(speech), len(json.loads(script)))
    entries = stages.sequence_entries(
        {k: v for k, v in images.items() if k.endswith(".png")}, timings
    )
    assert sum(frames for _, frames in entries) == sum(t.frames for t in timings)
    assert any("-" in name for name, _ in entries)  # animated sequences are present


def test_sequences_hold_their_last_image_and_refuse_gaps() -> None:
    timings = [Timing(0, 30, 1.0), Timing(30, 40, 1.2)]
    png = b"\x89PNG\r\n\x1a\nbody"
    good = {"frame000.png": png, "frame001-000.png": png, "frame001-001.png": png}
    assert stages.sequence_entries(good, timings) == [
        ("frame000.png", 30),
        ("frame001-000.png", stages.ANIMATION_STEP),
        ("frame001-001.png", 40 - stages.ANIMATION_STEP),
    ]
    for bad in (
        {"frame000.png": png, "frame001-000.png": png, "frame001-002.png": png},  # a gap
        {**good, "frame002.png": png},  # an extra image
        {"frame000.png": png, **{f"frame001-{j:03d}.png": png for j in range(9)}},  # too long
    ):
        with pytest.raises(stages.RenderError, match="media_bundle_invalid"):
            stages.sequence_entries(bad, timings)


# ------------------------------------------------------------ 4. encode time scales, bounded


def test_encode_time_limit_scales_with_length_and_is_capped() -> None:
    assert stages.encode_timeout(0) == 170
    assert stages.encode_timeout(60) == 200
    assert stages.encode_timeout(542) == pytest.approx(170 + 30 * 542 / 60)
    assert stages.encode_timeout(60 * 60) == 900
    assert stages.encode_timeout(600, base=60, per_minute=10, cap=100) == 100
    settings = Settings(**SETTINGS)
    assert (
        settings.media_encode_base_seconds,
        settings.media_encode_seconds_per_minute,
        settings.media_encode_max_seconds,
        settings.media_speech_prewarm_seconds,
        settings.tts_threads,
    ) == (170, 30, 900, 240, None)
    for bad in (
        {"media_encode_max_seconds": 4000},
        {"media_speech_prewarm_seconds": 301},
        {"tts_threads": 0},
    ):
        with pytest.raises(ValueError):
            Settings(**SETTINGS, **bad)


def test_one_decode_counts_the_frames_it_verifies() -> None:
    report = "frame=10\nprogress=continue\nframe=150\nfps=0.0\nprogress=end\n"
    assert stages.decoded_frames(report) == 150
    for bad in ("frame=150\nprogress=continue\n", "progress=end\n"):
        with pytest.raises(stages.RenderError, match="media_video"):
            stages.decoded_frames(bad)


def wav(seconds: float, rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    values = tone(seconds, rate)
    with wave.open(buffer, "wb") as target:
        target.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        target.writeframes(struct.pack(f"<{len(values)}h", *(round(v * 32767) for v in values)))
    return buffer.getvalue()


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and ffprobe are not installed here; the integration image has them",
)
def test_an_animated_architecture_sequence_encodes_and_decodes(
    fullstack: Shape, tmp_path: Path
) -> None:
    assert fullstack.report is not None
    architecture = fullstack.report.architectures[0]
    diagram = Diagram(architecture, "example/demo", "a" * 40, architecture.views[0])
    link = architecture.connections[0]
    images = stages.diagram_frames(
        diagram, (), (link.id,), "VERIFIED", "Caption.", None, 0, 1, FPS * 2, mode="flow"
    )
    still = stages.diagram_frames(
        diagram, (link.source,), (), "VERIFIED", "Caption.", None, 1, 2, FPS, mode="still"
    )
    files = {f"frame000-{j:03d}.png": image for j, image in enumerate(images)}
    files["frame001.png"] = still[0]
    timings = [Timing(0, FPS * 2, 1.9), Timing(FPS * 2, FPS, 0.9)]
    entries = stages.sequence_entries(files, timings)
    for name, _ in entries:
        (tmp_path / name).write_bytes(files[name])
    video, summary = stages.encode_sequence(tmp_path, entries, wav(3.0), timeout=120)
    assert video[4:8] == b"ftyp" and summary["video_frames"] == FPS * 3
    assert summary["full_decode"] == "passed" and summary["duration_seconds"] == pytest.approx(3)

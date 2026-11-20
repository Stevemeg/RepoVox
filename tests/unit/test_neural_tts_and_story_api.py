"""Milestone 3: the optional local neural voice, its fail-closed settings, the video metadata
that names it, and the read-only story API.

No model weights are downloaded and `kokoro_onnx` is never imported for real: the neural
voice is exercised through a stand-in module that returns synthetic float samples. API
routes run against a recorded database that only answers for the owner it is scoped to.
"""

import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from repovox.api.routes import authenticated
from repovox.auth.session import Identity
from repovox.core.config import Settings
from repovox.main import create_app
from repovox.media import stages
from repovox.media.narration import Engine, NarrationError, Speech, synthesize
from repovox.media.speech import (
    NEURAL_RATE,
    KokoroOnnxSynthesizer,
    SpeechError,
    kokoro_module,
    neural_speech,
    voice_from_settings,
    voice_record,
)
from repovox.media.story_view import (
    QUOTE_LIMIT,
    REFS_PER_CLAIM,
    STATUS_LABELS,
    NarrationView,
    story_view,
    trimmed_claim,
)
from repovox.media.worker import MediaWorker
from test_engineering_story import STRONG, Shape, Store, shape
from test_media_runtime import Database

ROOT = Path(__file__).resolve().parents[2]
BASE: dict[str, Any] = {
    "database_url": "postgresql+psycopg://rv_app:p@localhost/repovox",
    "session_secret": "x" * 40,
    "storage_access_key": "a",
    "storage_secret_key": "s",
    "environment": "development",
    "dev_auth": True,
}
OWNER = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture(autouse=True)
def no_ambient_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.upper().startswith("REPOVOX_")]:
        monkeypatch.delenv(name)


@pytest.fixture(scope="module")
def strong(tmp_path_factory: pytest.TempPathFactory) -> Shape:
    return shape(tmp_path_factory.mktemp("strong"), STRONG)


@pytest.fixture
def assets(tmp_path: Path) -> tuple[str, str]:
    model, voices = tmp_path / "kokoro-v1.0.onnx", tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"synthetic model placeholder")
    voices.write_bytes(b"synthetic voices placeholder")
    return str(model), str(voices)


def tone(seconds: float = 0.8, rate: int = 24000, level: float = 0.4) -> list[float]:
    return [level * math.sin(2 * math.pi * 220 * i / rate) for i in range(int(seconds * rate))]


class FakeKokoro:
    """Stands in for `kokoro_onnx.Kokoro`: records its inputs, returns synthetic samples."""

    loads: list[tuple[str, str]] = []

    def __init__(self, model: str, voices: str) -> None:
        FakeKokoro.loads.append((model, voices))
        self.calls: list[dict[str, Any]] = []
        self.answer: Any = (tone(), 24000)

    def create(self, text: str, voice: str, speed: float, lang: str) -> Any:
        self.calls.append({"text": text, "voice": voice, "speed": speed, "lang": lang})
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def fake_loader() -> Any:
    return SimpleNamespace(Kokoro=FakeKokoro)


def missing_package() -> Any:
    raise ImportError("No module named 'kokoro_onnx'")


def kokoro(assets: tuple[str, str], loader: Any = fake_loader, **kwargs: Any) -> Any:
    return KokoroOnnxSynthesizer(Path(assets[0]), Path(assets[1]), loader=loader, **kwargs)


# ------------------------------------------------------------------ 1. fail-closed settings


def test_voice_settings_default_to_auto_with_a_safe_voice() -> None:
    settings = Settings(**BASE)
    assert (settings.tts_provider, settings.tts_voice, settings.tts_speed) == (
        "auto",
        "af_heart",
        1.0,
    )
    assert settings.tts_model_path is None and settings.tts_voices_path is None


def test_voice_settings_are_read_from_repovox_tts_variables(
    monkeypatch: pytest.MonkeyPatch, assets: tuple[str, str]
) -> None:
    monkeypatch.setenv("REPOVOX_TTS_PROVIDER", "kokoro_onnx")
    monkeypatch.setenv("REPOVOX_TTS_MODEL_PATH", assets[0])
    monkeypatch.setenv("REPOVOX_TTS_VOICES_PATH", assets[1])
    monkeypatch.setenv("REPOVOX_TTS_VOICE", "bm_george")
    monkeypatch.setenv("REPOVOX_TTS_SPEED", "1.25")
    settings = Settings(**BASE)
    assert (settings.tts_provider, settings.tts_voice, settings.tts_speed) == (
        "kokoro_onnx",
        "bm_george",
        1.25,
    )
    assert (settings.tts_model_path, settings.tts_voices_path) == assets


def test_a_demanded_neural_voice_needs_both_files(assets: tuple[str, str]) -> None:
    with pytest.raises(ValidationError, match="requires its model and voices files"):
        Settings(**BASE, tts_provider="kokoro_onnx")
    with pytest.raises(ValidationError, match="requires its model and voices files"):
        Settings(**BASE, tts_provider="kokoro_onnx", tts_model_path=" ", tts_voices_path="")
    for one in ({"tts_model_path": assets[0]}, {"tts_voices_path": assets[1]}):
        for provider in ("auto", "kokoro_onnx", "deterministic"):
            with pytest.raises(ValidationError, match="both its model and its voices file"):
                Settings(**BASE, tts_provider=provider, **one)
    ok = Settings(
        **BASE, tts_provider="kokoro_onnx", tts_model_path=assets[0], tts_voices_path=assets[1]
    )
    assert ok.tts_model_path == assets[0]


@pytest.mark.parametrize(
    "change",
    [
        lambda m, v: (os.path.join("models", "kokoro.onnx"), v),  # Relative.
        lambda m, v: (os.path.join(os.path.dirname(m), "..", "kokoro.onnx"), v),  # Traversal.
        lambda m, v: (m[:-5] + chr(0) + ".onnx", v),  # NUL byte.
        lambda m, v: (m[:-5] + chr(10) + ".onnx", v),  # Control character.
        lambda m, v: (v, v),  # The voices file named as the model.
        lambda m, v: (m, m),  # The model named as the voices file.
        lambda m, v: (m, os.path.join(os.path.dirname(v), "..", "voices.bin")),
    ],
)
def test_unsafe_neural_voice_paths_are_refused(change: Any, assets: tuple[str, str]) -> None:
    model, voices = change(*assets)
    with pytest.raises(ValidationError, match="neural voice"):
        Settings(**BASE, tts_provider="auto", tts_model_path=model, tts_voices_path=voices)


@pytest.mark.parametrize(
    "voice", ["AF_HEART", "a", "af heart", "../af", "af/heart", "x" * 33, "af_heart;rm", ""]
)
def test_voice_names_are_safe_identifiers(voice: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**BASE, tts_voice=voice)


@pytest.mark.parametrize("voice", ["af_heart", "bm_george", "am-michael", "zf_001"])
def test_documented_voice_names_are_accepted(voice: str) -> None:
    assert Settings(**BASE, tts_voice=voice).tts_voice == voice


@pytest.mark.parametrize("speed", [0.49, 2.01, 0, -1])
def test_voice_speed_is_bounded(speed: float) -> None:
    with pytest.raises(ValidationError):
        Settings(**BASE, tts_speed=speed)


# ---------------------------------------------------------------- 2. the local neural voice


def test_the_neural_voice_produces_validated_pcm(assets: tuple[str, str], tmp_path: Path) -> None:
    FakeKokoro.loads.clear()
    voice = kokoro(assets, voice="bf_emma", speed=1.1)
    found = synthesize(voice, "The README states the problem.", tmp_path, "s000")
    assert found.rate == NEURAL_RATE and len(found.samples) == 2 * int(0.8 * 24000)
    assert 0.79 < found.seconds < 0.81
    engine = voice.engine()
    assert engine.calls == [
        {
            "text": "The README states the problem.",
            "voice": "bf_emma",
            "speed": 1.1,
            "lang": "en-us",
        }
    ]
    synthesize(voice, "Second sentence.", tmp_path, "s001")
    assert FakeKokoro.loads == [assets]  # The model is loaded once per voice.
    assert assets[0] not in repr(voice) and "bf_emma" in repr(voice)


def test_neural_samples_are_resampled_and_mixed_to_one_channel() -> None:
    rate = 22050
    found = neural_speech(tone(1.0, rate), rate)
    assert found.rate == NEURAL_RATE and abs(len(found.samples) // 2 - NEURAL_RATE) <= 1
    stereo = [[v, v] for v in tone(0.5)]
    assert neural_speech(stereo, 24000).samples == neural_speech(tone(0.5), 24000).samples
    planar = [tone(0.5), tone(0.5)]
    assert neural_speech(planar, 24000).samples == neural_speech(tone(0.5), 24000).samples
    loud = neural_speech([2.0, -3.0] * 12000, 24000)  # Out-of-range samples are clipped.
    assert (
        max(abs(int.from_bytes(loud.samples[i : i + 2], "little", signed=True)) for i in (0, 2))
        == 32767
    )


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        ((tone(), float("nan")), "speech_corrupt"),
        (([0.1, float("nan")] * 12000, 24000), "speech_corrupt"),
        (([0.1, float("inf")] * 12000, 24000), "speech_corrupt"),
        ((["loud", "quiet"], 24000), "speech_corrupt"),
        (([], 24000), "speech_corrupt"),
        ((tone(), 1000), "speech_format_unsupported"),
        ((tone(), 96000), "speech_format_unsupported"),
        (([0.1] * (24000 * 121), 24000), "speech_too_long"),
        (RuntimeError("onnx session failed"), "neural_speech_failed"),
    ],
)
def test_corrupt_neural_audio_fails_with_a_fixed_code(
    assets: tuple[str, str], tmp_path: Path, answer: Any, code: str
) -> None:
    voice = kokoro(assets)
    voice.engine().answer = answer
    with pytest.raises(SpeechError) as raised:
        synthesize(voice, "Hello there.", tmp_path, "s")
    assert raised.value.code == code and assets[0] not in str(raised.value)


@pytest.mark.parametrize(
    ("answer", "code"),
    [(([0.0] * 24000, 24000), "speech_silent"), ((tone(0.1), 24000), "speech_silent")],
)
def test_silent_or_too_short_neural_audio_is_not_narration(
    assets: tuple[str, str], tmp_path: Path, answer: Any, code: str
) -> None:
    voice = kokoro(assets)
    voice.engine().answer = answer
    with pytest.raises(NarrationError) as raised:  # The same check as the OS voices.
        synthesize(voice, "Hello there.", tmp_path, "s")
    assert raised.value.code == code


def test_a_missing_package_or_model_fails_cleanly(assets: tuple[str, str], tmp_path: Path) -> None:
    def broken(model: str, voices: str) -> Any:
        raise RuntimeError("bad model file")

    cases = [
        (kokoro(assets, loader=missing_package), "neural_tts_unavailable"),
        (kokoro((assets[0] + ".gone", assets[1])), "neural_tts_files_missing"),
        (kokoro(assets, loader=lambda: SimpleNamespace(Kokoro=broken)), "neural_tts_load_failed"),
    ]
    for voice, code in cases:
        assert not voice.available()
        with pytest.raises(SpeechError) as raised:
            synthesize(voice, "Hello there.", tmp_path, "s")
        assert raised.value.code == code
    # The real loader: the optional package is not part of the default install or of CI.
    try:
        kokoro_module()
    except ImportError:
        assert not kokoro(assets, loader=kokoro_module).available()


# ------------------------------------------------------------ 3. voice selection and records


def os_voice() -> Engine:
    return Engine("espeak-ng", Path("/usr/bin/espeak-ng"))


def no_fallback() -> Any:
    raise AssertionError("a demanded neural voice fell back to another voice")


def test_auto_uses_the_neural_voice_only_when_it_loads(assets: tuple[str, str]) -> None:
    plain = Settings(**BASE)
    assert voice_from_settings(plain, fake_loader, os_voice) == os_voice()
    configured = Settings(**BASE, tts_model_path=assets[0], tts_voices_path=assets[1])
    chosen = voice_from_settings(configured, fake_loader, os_voice)
    assert isinstance(chosen, KokoroOnnxSynthesizer) and chosen.voice == "af_heart"
    assert voice_from_settings(configured, missing_package, os_voice) == os_voice()
    # The real loader: the package is absent here, and placeholder files would not load.
    assert voice_from_settings(configured, kokoro_module, os_voice) == os_voice()
    gone = Settings(**BASE, tts_model_path=assets[0] + "x.onnx", tts_voices_path=assets[1])
    assert voice_from_settings(gone, fake_loader, os_voice) == os_voice()
    forced = Settings(
        **BASE, tts_provider="deterministic", tts_model_path=assets[0], tts_voices_path=assets[1]
    )
    assert voice_from_settings(forced, fake_loader, os_voice) == os_voice()


def test_a_demanded_neural_voice_never_falls_back(assets: tuple[str, str]) -> None:
    demanded = Settings(
        **BASE, tts_provider="kokoro_onnx", tts_model_path=assets[0], tts_voices_path=assets[1]
    )
    assert isinstance(
        voice_from_settings(demanded, fake_loader, no_fallback), KokoroOnnxSynthesizer
    )
    with pytest.raises(SpeechError, match="neural_tts_unavailable"):
        voice_from_settings(demanded, missing_package, no_fallback)
    gone = Settings(
        **BASE,
        tts_provider="kokoro_onnx",
        tts_model_path=assets[0] + "x.onnx",
        tts_voices_path=assets[1],
    )
    with pytest.raises(SpeechError, match="neural_tts_files_missing"):
        voice_from_settings(gone, fake_loader, no_fallback)


def test_voice_records_name_the_voice_and_never_a_path(assets: tuple[str, str]) -> None:
    assert voice_record(kokoro(assets, voice="am_adam")) == {
        "tts_provider": "kokoro_onnx",
        "tts_engine": "kokoro-onnx",
        "tts_voice": "am_adam",
    }
    assert voice_record(os_voice()) == {
        "tts_provider": "deterministic",
        "tts_engine": "espeak-ng",
        "tts_voice": "espeak-ng",
    }

    class Custom:
        name = "C:/voices/secret path"

        def speak(self, text: str, scratch: Path, stem: str) -> Speech:
            return Speech(24000, b"")

    assert voice_record(Custom()) == {
        "tts_provider": "local",
        "tts_engine": "unnamed",
        "tts_voice": "unnamed",
    }


def test_stage_12_records_the_neural_voice_and_stage_14_reports_it(
    strong: Shape, assets: tuple[str, str], tmp_path: Path
) -> None:
    storyboard = stages.storyboard_stage(strong.payload, strong.story, strong.report)
    script = stages.narration_stage(strong.payload, storyboard, strong.sources)
    speech = stages.tts_stage(storyboard, script, kokoro(assets), tmp_path)
    files = stages.unbundle(speech)
    assert set(files) == {"narration.wav", "timings.json", "voice.json"}
    assert json.loads(files["voice.json"]) == {
        "tts_provider": "kokoro_onnx",
        "tts_engine": "kokoro-onnx",
        "tts_voice": "af_heart",
    }
    assert str(tmp_path).encode() not in speech
    frames = stages.render_stage(storyboard, script, speech)  # Stage 13 accepts the voice record.
    assert b"WEBVTT" in stages.unbundle(frames)["captions.vtt"]
    narration = stages.video_narration(storyboard, speech)
    assert NarrationView.model_validate(narration).tts_provider == "kokoro_onnx"
    assert (narration["refiner"], narration["provider"], narration["scenes_refined"]) == (
        "deterministic-template-1.0",
        "deterministic",
        0,
    )
    assert narration["scenes_total"] == len(json.loads(storyboard)["scenes"])
    older = stages.bundle({k: v for k, v in files.items() if k != "voice.json"})
    assert stages.video_narration(storyboard, older)["tts_provider"] is None
    forged = stages.bundle({**files, "voice.json": b'{"tts_provider": "kokoro_onnx"}'})
    for bad in (forged, stages.bundle({**files, "voice.json": b"not json"})):
        with pytest.raises(stages.RenderError, match="media_bundle_invalid"):
            stages.video_narration(storyboard, bad)
    count = len(json.loads(script))
    assert len(stages.timings_of(files, count)) == count
    with pytest.raises(stages.RenderError, match="media_bundle_invalid"):
        stages.timings_of({**files, "extra.json": b"{}"}, count)  # Only voice.json is optional.


def run_stage(store: Store, ordinal: int, outputs: list[dict[str, Any]], worker: Any) -> Database:
    stage, fence, owner, job = uuid4(), 2, uuid4(), uuid4()
    scope = {
        "job_id": str(job),
        "owner_id": str(owner),
        "ordinal": ordinal,
        "analysis": {"owner_id": str(owner), "commit_sha": "c" * 40},
        "outputs": outputs,
    }

    def answer(sql: str, params: dict[str, Any]) -> Any:
        if "mv.claim(" in sql:
            return [{"o_stage": stage, "o_fence": fence, "o_job": job, "o_ordinal": ordinal}]
        if "mv.scope(" in sql:
            return scope
        return "mv.heartbeat(" in sql or "mv.finish(" in sql or "mv.fail(" in sql or None

    database = Database(answer)
    worker.engine = database
    assert worker.run_once()
    return database


def test_a_demanded_but_missing_neural_voice_fails_the_speech_stage_explicitly(
    assets: tuple[str, str],
) -> None:
    settings = Settings(
        **BASE, tts_provider="kokoro_onnx", tts_model_path=assets[0], tts_voices_path=assets[1]
    )
    store = Store(b"")
    store.objects["board"], store.objects["script"] = b"{}", b"[]"
    worker = MediaWorker(
        None,  # type: ignore[arg-type]
        store,  # type: ignore[arg-type]
        "unit",
        voices=lambda: voice_from_settings(settings, missing_package, no_fallback),
    )
    outputs = [
        {"ordinal": 10, "key": "board", "bytes": 2},
        {"ordinal": 11, "key": "script", "bytes": 2},
    ]
    database = run_stage(store, 12, outputs, worker)
    assert database.called("mv.finish") == []
    (failure,) = database.called("mv.fail")
    assert failure["code"] == "neural_tts_unavailable" and failure["transient"] is False
    assert worker.speech is None  # Nothing was remembered; a fixed install is picked up.


# ------------------------------------------------------------------ 4. the public story view


def test_the_story_view_keeps_every_status_and_is_bounded(strong: Shape) -> None:
    view = story_view(strong.story)
    assert view is not None and view.status_labels == STATUS_LABELS
    assert view.status_labels["DOCUMENTATION_ONLY"] == "AUTHOR-STATED / NOT VERIFIED BY CODE"
    original = {c.id: c for c in strong.story.claims().values()}
    shown = [
        c
        for group in (
            view.problem_statement.claims,
            view.problem_context.claims,
            view.intended_solution.claims,
            view.implementation_approach.claims,
            view.implementation_approach.decisions,
            view.architecture.claims,
            view.architecture.workflow,
            view.implementation_evidence.claims,
            view.demonstrated_outcomes.claims,
            view.limitations.claims,
            view.unresolved_questions.claims,
        )
        for c in group
    ]
    assert {c.id for c in shown} == set(original)
    for item in shown:
        source = original[item.id]
        assert (item.status, item.evidence_type, item.text) == (
            source.status,
            source.evidence_type,
            source.text,
        )
        assert len(item.evidence_refs) <= REFS_PER_CLAIM
        assert all(len(ref.quote) <= QUOTE_LIMIT for ref in item.evidence_refs)
        assert item.source_location == source.source_location
    assert sum(view.status_counts.values()) == len(original)
    assert sum(view.source_counts.values()) == len(strong.story.sources)
    assert view.mismatches == strong.story.mismatches and not view.evidence_trimmed
    body = json.dumps(view.model_dump(mode="json"))
    assert str(strong.root) not in body and str(strong.root).replace("\\", "/") not in body
    assert '"sources"' not in body and "file_sha256" in body


def test_long_evidence_is_trimmed_and_an_oversized_view_is_withheld(
    strong: Shape, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim = next(c for c in strong.story.claims().values() if c.evidence_refs)
    ref = claim.evidence_refs[0].model_copy(update={"quote": "q" * 1000})
    longer = claim.model_copy(update={"evidence_refs": (ref,)})
    trimmed, cut = trimmed_claim(longer)
    assert cut and len(trimmed.evidence_refs[0].quote) == QUOTE_LIMIT
    assert trimmed.evidence_refs[0].quote.endswith("...")
    monkeypatch.setattr("repovox.media.story_view.VIEW_LIMIT", 100)
    assert story_view(strong.story) is None
    assert (
        stages.video_story(stages.storyboard_stage(strong.payload, strong.story, strong.report))
        is None
    )


def test_narration_records_are_consistent() -> None:
    good = {
        "refiner": "deterministic-template-1.0",
        "provider": "deterministic",
        "model": None,
        "blueprint_sha256": None,
        "scenes_total": 9,
        "scenes_refined": 0,
        "scenes_fallback": 0,
        "refined_scene_ids": [],
        "fallback_reason": None,
        "rejection_reasons": {},
        "tts_provider": "deterministic",
        "tts_engine": "espeak-ng",
        "tts_voice": "espeak-ng",
    }
    NarrationView.model_validate(good)
    for change in (
        {"model": "llama3"},
        {"refiner": "grounded-llm-refiner-1.0"},
        {"provider": "anthropic"},
        {"scenes_refined": 9, "scenes_fallback": 1},
        {"tts_voice": "../etc/passwd"},
        {"tts_provider": "hosted"},
        {"extra": True},
    ):
        with pytest.raises(ValidationError):
            NarrationView.model_validate({**good, **change})


# -------------------------------------------------------------------- 5. the read-only API


def story_app(found: Shape, record: dict[str, Any] | None, owner: UUID | None) -> TestClient:
    """The real story route and `MediaJobs.story` over a recorded, owner-scoped database."""
    settings = Settings(
        environment="test",
        dev_auth=True,
        analysis=True,
        video=True,
        database_url="postgresql+psycopg://u:p@localhost/core",
        media_database_url="postgresql+psycopg://u:p@localhost/media",
        session_secret="s" * 32,
        storage_access_key="a",
        storage_secret_key="s",
    )
    app = create_app(settings)  # Not entered, so nothing connects.

    def answer(sql: str, params: dict[str, Any]) -> Any:
        if "metadata->'story'" in sql and record is not None and params.get("owner") == OWNER:
            return [dict(record)]
        return [] if "media_videos" in sql else None

    app.state.media.engine = Database(answer)
    if owner is not None:
        app.dependency_overrides[authenticated] = lambda: Identity(owner, uuid4(), "", "n", "e")
    return TestClient(app)


def stored_record(found: Shape) -> dict[str, Any]:
    storyboard = stages.storyboard_stage(found.payload, found.story, found.report)
    speech = stages.bundle(
        {
            "narration.wav": b"RIFF",
            "timings.json": b"[]",
            "voice.json": stages.encoded(voice_record(os_voice())),
        }
    )
    return {
        "id": uuid4(),
        "job_id": uuid4(),
        "category": "walkthrough",
        "story": stages.video_story(storyboard),
        "narration": stages.video_narration(storyboard, speech),
    }


def test_the_story_route_serves_the_owners_verified_story(strong: Shape) -> None:
    record = stored_record(strong)
    route = f"/v1/video-jobs/{record['job_id']}/videos/{record['id']}/story"
    response = story_app(strong, record, OWNER).get(route)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"video_id", "job_id", "category", "narration", "story"}
    assert body["video_id"] == str(record["id"]) and body["category"] == "walkthrough"
    assert body["narration"]["tts_provider"] == "deterministic"
    story = body["story"]
    assert story["problem_statement"]["sufficiency"] == "documented"
    assert story["status_labels"] == STATUS_LABELS
    for artifact in (
        "problem_statement",
        "problem_context",
        "intended_solution",
        "implementation_approach",
        "architecture",
        "implementation_evidence",
        "demonstrated_outcomes",
        "limitations",
        "unresolved_questions",
    ):
        assert "claims" in story[artifact]
    first = story["problem_statement"]["claims"][0]
    assert first["status"] == "DOCUMENTATION_ONLY"
    assert first["evidence_type"] == "author_stated_problem"
    assert first["evidence_refs"][0]["permalink"].startswith("https://github.com/")
    assert str(strong.root) not in response.text and "secret" not in response.text.lower()


def test_the_story_route_is_owner_scoped_and_authenticated(strong: Shape) -> None:
    record = stored_record(strong)
    route = f"/v1/video-jobs/{record['job_id']}/videos/{record['id']}/story"
    other = story_app(strong, record, OTHER).get(route)
    assert other.status_code == 404 and other.json()["error"]["code"] == "not_found"
    assert str(strong.story.repository) not in other.text
    anonymous = story_app(strong, record, None).get(route)
    assert anonymous.status_code == 401
    missing = story_app(strong, None, OWNER).get(route)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    explainer = story_app(strong, {**record, "story": None, "category": "architecture"}, OWNER)
    response = explainer.get(route)
    assert response.status_code == 404 and response.json()["error"]["code"] == "story_not_available"
    corrupt = story_app(strong, {**record, "story": {"view_version": "x"}}, OWNER).get(route)
    assert corrupt.status_code == 503 and corrupt.json()["error"]["code"] == "story_corrupt"
    bad = story_app(strong, record, OWNER).get("/v1/video-jobs/not-a-uuid/videos/x/story")
    assert bad.status_code == 422


def contract_app() -> Any:
    return create_app(
        Settings(
            environment="test",
            dev_auth=True,
            fixtures=True,
            database_url="postgresql+psycopg://rv_app@localhost/repovox",
            session_secret="synthetic-contract-secret-never-used-for-sessions",
            storage_access_key="unused",
            storage_secret_key="unused",
        )
    )


def test_the_frozen_openapi_contract_matches_the_application() -> None:
    app = contract_app()
    try:
        live = app.openapi()
    finally:
        app.state.engine.dispose()
    frozen = json.loads((ROOT / "packages/contracts/openapi.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(live)) == frozen, "run: uv run python tools/phase1_contracts.py"
    route = frozen["paths"]["/v1/video-jobs/{job_id}/videos/{video_id}/story"]
    assert set(route) == {"get"}
    ok = route["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/VideoStoryView"}
    schemas = frozen["components"]["schemas"]
    claim = schemas["Claim"]["properties"]
    assert set(claim["status"]["enum"]) == set(STATUS_LABELS)
    assert "author_stated_problem" in claim["evidence_type"]["enum"]
    story = schemas["StoryView"]["properties"]
    assert {"mismatches", "status_labels", "evidence_trimmed", "problem_statement"} <= set(story)
    narration = schemas["NarrationView"]["properties"]
    assert {
        "provider",
        "model",
        "scenes_refined",
        "scenes_fallback",
        "tts_provider",
        "tts_voice",
    } <= set(narration)


def test_listings_leave_the_story_to_its_route() -> None:
    """The job listing selects video metadata without the story, so responses stay small."""
    settings = Settings(
        environment="test",
        dev_auth=True,
        analysis=True,
        video=True,
        database_url="postgresql+psycopg://u:p@localhost/core",
        media_database_url="postgresql+psycopg://u:p@localhost/media",
        session_secret="s" * 32,
        storage_access_key="a",
        storage_secret_key="s",
    )
    app = create_app(settings)
    seen: list[str] = []

    job = {"id": uuid4(), "state": "succeeded"}

    def answer(sql: str, params: dict[str, Any]) -> Any:
        seen.append(sql)
        return [dict(job)] if "FROM media_jobs WHERE" in sql else []

    app.state.media.engine = Database(answer)
    (found,) = app.state.media._load(OWNER, job["id"], None)
    assert found["videos"] == []
    (listing,) = [sql for sql in seen if "FROM media_videos" in sql]
    assert "metadata - 'story' AS metadata" in listing
    assert all("metadata->'story'" not in sql for sql in seen)

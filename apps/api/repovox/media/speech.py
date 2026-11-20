"""Spoken narration: what is said, and the local voice that says it.

Text. The caption keeps the exact identifiers and code; this layer only changes how they are
said. Rules are fixed and ordered. They may rename an identifier to the role the Architecture
IR already assigned to it, expand a small set of code idioms, and split identifiers into
words. They never add a fact: every spoken sentence is a function of its caption and the IR.

Audio. `audio_text` gives every voice the technical pronunciation of an approved sentence
(`pronunciation.pronounce`). Only the synthesis input changes: captions, storyboards and Stage 11
citations are never rewritten. `SpeechCache` keeps synthesized sentences in memory, bounded, so
work done within one stage's lease is not repeated by the next.

Voice. `KokoroOnnxSynthesizer` is an optional local neural voice on the `narration.Synthesizer`
seam. Its package (`neural-tts` extra) is imported only when it first speaks, and its model and
voice files are supplied by the operator; nothing is downloaded. Its PCM is converted to one
fixed rate and passes the same format, duration and silence checks as the operating-system
voices. `voice_from_settings` selects it, and `voice_record` names the voice for the video
metadata without any file path.
"""

import importlib
import math
import os
import re
import struct
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repovox.core.config import Settings
from repovox.media.architecture import Architecture
from repovox.media.narration import (
    Engine,
    NarrationError,
    Speech,
    Voice,
    audible,
    detect,
    synthesize,
)
from repovox.media.pronunciation import LIMIT, pronounce
from repovox.media.storyboard import speakable

# Spoken names for roles the IR assigns from evidence. Tensors keep their variable names,
# which are ordinary words and must not be rewritten wherever they appear.
ROLE_NAMES = {
    "generator": "the generator",
    "discriminator": "the discriminator",
    "loss_d": "the discriminator loss",
    "loss_g": "the generator loss",
    "opt_d": "the discriminator optimizer",
    "opt_g": "the generator optimizer",
    "model": "the model",
    "loss": "the loss",
    "optimizer": "the optimizer",
}
IDIOMS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(\w+)\.backward\(\) then (\w+)\.step\(\) update (\w+)\."),
        r"\1 is backpropagated, followed by an optimizer step that updates \3.",
    ),
    (re.compile(r"under torch\.no_grad\(\)"), "with gradient tracking disabled"),
    (re.compile(r"\blr=([0-9.e-]+)"), r"learning rate \1"),
    (re.compile(r"\bbetas=\(([0-9.]+), ([0-9.]+)\)"), r"betas \1 and \2"),
    (re.compile(r"\bmomentum=([0-9.]+)"), r"momentum \1"),
    (re.compile(r"(\w+) (\w+) -> (\w+)((?: [ksp]\d+)*)"), r"\1 from \2 to \3"),
    (re.compile(r"\b(\w+)\(\)"), r"\1"),
    (re.compile(r"\bnn\.(\w+)"), r"\1"),
    (re.compile(r"\bself\.(\w+)"), r"\1"),
]
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def humanize(identifier: str) -> str:
    """`build_prompt` -> `build prompt`, `VectorStore` -> `Vector Store`."""
    words = CAMEL.sub(" ", identifier.replace("_", " ").replace(".", " "))
    return re.sub(r"\s+", " ", words).strip()


def vocabulary(architecture: Architecture) -> dict[str, str]:
    """Label -> spoken name. A role name is used only when the label is a plain identifier."""
    names: dict[str, str] = {}
    for component in architecture.components:
        spoken = ROLE_NAMES.get(component.role) if not architecture.views else None
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", component.label):
            names.setdefault(component.label, spoken or humanize(component.label))
    return names


def natural(text: str, names: dict[str, str]) -> str:
    for pattern, replacement in IDIOMS:
        text = pattern.sub(replacement, text)
    for label in sorted(names, key=len, reverse=True):
        text = re.sub(rf"(?<![\w.]){re.escape(label)}(?![\w(])", names[label], text)
    text = re.sub(r"\b([a-z]+(?:_[a-z0-9]+)+)\b", lambda m: m.group(1).replace("_", " "), text)
    text = re.sub(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b", lambda m: humanize(m.group(0)), text)
    spoken = speakable(text)
    # A sentence that starts with a role phrase starts with a capital letter when captioned.
    return (spoken[:1].upper() + spoken[1:])[:600]


# --------------------------------------------------------------------- what a voice is given


def audio_text(text: str, spoken: str) -> str:
    """The synthesis input for one approved sentence: its technical pronunciation.

    When the approved spoken form is the caption's plain spoken rewrite (`speakable`), the
    caption is pronounced, so a path is read from the whole path. Otherwise the spoken form
    carries the IR's role names and is pronounced itself. Falls back to the approved spoken
    form unchanged if a pronunciation would not be printable ASCII within the length bound.
    """
    for source in [text, spoken] if spoken == speakable(text) else [spoken]:
        said = pronounce(source)
        if said and len(said) <= LIMIT and all(32 <= ord(c) < 127 for c in said):
            return said
    return spoken


class SpeechCache:
    """Synthesized sentences by voice and exact text, least recently used first out.

    A voice says the same text the same way, so a cached sentence is what the voice would
    produce again. The cache is in memory only, never persisted, and bounded in bytes.
    """

    def __init__(self, limit_bytes: int = 96 * 1024**2) -> None:
        self.limit = limit_bytes
        self.size = 0
        self.items: OrderedDict[tuple[str, ...], Speech] = OrderedDict()
        self.lock = threading.Lock()

    @staticmethod
    def key(engine: Voice, text: str) -> tuple[str, ...]:
        if isinstance(engine, KokoroOnnxSynthesizer):
            identity: tuple[str, ...] = (
                "kokoro",
                str(engine.model_path),
                str(engine.voices_path),
                engine.voice,
                repr(engine.speed),
            )
        elif isinstance(engine, Engine):
            identity = ("engine", engine.name, str(engine.executable))
        else:
            identity = ("voice", type(engine).__qualname__, str(id(engine)))
        return (*identity, text)

    def get(self, engine: Voice, text: str) -> Speech | None:
        key = self.key(engine, text)
        with self.lock:
            found = self.items.get(key)
            if found is not None:
                self.items.move_to_end(key)
            return found

    def put(self, engine: Voice, text: str, speech: Speech) -> None:
        cost = len(speech.samples)
        if cost > self.limit:
            return
        key = self.key(engine, text)
        with self.lock:
            if key in self.items:
                return
            self.items[key] = speech
            self.size += cost
            while self.size > self.limit:
                _, dropped = self.items.popitem(last=False)
                self.size -= len(dropped.samples)


def speak(
    engine: Voice, text: str, scratch: Path, stem: str, cache: SpeechCache | None = None
) -> Speech:
    """One sentence through `narration.synthesize`, reusing a cached result when there is one."""
    found = cache.get(engine, text) if cache is not None else None
    if found is not None:
        return found
    speech = synthesize(engine, text, scratch, stem)
    if cache is not None:
        cache.put(engine, text, speech)
    return speech


# ----------------------------------------------------------------------- local neural voice

NEURAL_RATE = 24000  # Every neural segment is delivered at exactly this rate, mono, 16-bit.
MAX_SEGMENT_SECONDS = 120.0
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class SpeechError(NarrationError):
    """The configured neural voice could not speak. Fixed code only; never a path or text."""


def mono(samples: Any) -> list[float]:
    """Float samples as one channel: a 1-D sequence, or a 2-D array with channels averaged."""
    data = samples.tolist() if hasattr(samples, "tolist") else list(samples)
    if data and isinstance(data[0], (list, tuple)):
        frames = data if len(data) > 2 else [list(frame) for frame in zip(*data, strict=True)]
        data = [sum(frame) / len(frame) for frame in frames if frame]
    return [float(value) for value in data]


def resample(values: list[float], rate: int, target: int) -> list[float]:
    """Deterministic linear interpolation to the target rate."""
    if rate == target or len(values) < 2:
        return values
    count = max(2, round(len(values) * target / rate))
    step = (len(values) - 1) / (count - 1)
    found = []
    for i in range(count):
        position = i * step
        low = int(position)
        high = min(low + 1, len(values) - 1)
        found.append(values[low] + (values[high] - values[low]) * (position - low))
    return found


def neural_speech(samples: Any, rate: Any) -> Speech:
    """Validated 16-bit mono PCM at NEURAL_RATE from a neural voice's float samples."""
    try:
        source_rate = int(rate)
        values = mono(samples)
    except (TypeError, ValueError, AttributeError):
        raise SpeechError("speech_corrupt") from None
    if not 8000 <= source_rate <= 48000:
        raise SpeechError("speech_format_unsupported")
    if not values or not all(math.isfinite(v) for v in values):
        raise SpeechError("speech_corrupt")
    if len(values) / source_rate > MAX_SEGMENT_SECONDS:
        raise SpeechError("speech_too_long")
    values = resample(values, source_rate, NEURAL_RATE)
    pcm = struct.pack(f"<{len(values)}h", *(round(max(-1.0, min(1.0, v)) * 32767) for v in values))
    return audible(Speech(NEURAL_RATE, pcm))  # The same silence and duration checks.


def kokoro_module() -> Any:
    return importlib.import_module("kokoro_onnx")


def onnxruntime_module() -> Any:
    return importlib.import_module("onnxruntime")


LIBRARY_LOCK = threading.Lock()


@contextmanager
def library_scratch(directory: Path | None) -> Iterator[None]:
    """Where the phonemizer copies and loads its espeak-ng library while Kokoro runs.

    The phonemizer copies the shared library into `tempfile.mkdtemp()` before loading it. The
    hardened `/tmp` is `noexec`, so that load fails there; a deployment that sets
    `REPOVOX_TTS_LIBRARY_DIR` gives it a separate executable scratch instead, and `/tmp` stays
    `noexec`. The process-wide temporary directory is changed only inside this block, under a
    lock, and is always restored.
    """
    if directory is None:
        yield
        return
    with LIBRARY_LOCK:
        previous = tempfile.tempdir
        tempfile.tempdir = str(directory)
        try:
            yield
        finally:
            tempfile.tempdir = previous


@dataclass(frozen=True, repr=False)
class KokoroOnnxSynthesizer:
    """A local Kokoro ONNX voice. Approved printable-ASCII text in, validated PCM out."""

    model_path: Path
    voices_path: Path
    voice: str = "af_heart"
    speed: float = 1.0
    loader: Callable[[], Any] = kokoro_module  # Replaced only by tests.
    # Inference threads. None keeps the runtime's default, which counts every host core even
    # when the container is given fewer; set it to the container's CPU allocation.
    threads: int | None = None
    runtime: Callable[[], Any] = onnxruntime_module  # Replaced only by tests.
    # Executable scratch for the phonemizer's library copy; see `library_scratch`.
    library_dir: Path | None = None
    _loaded: dict[str, Any] = field(default_factory=dict, compare=False)

    name = "kokoro-onnx"

    def __repr__(self) -> str:
        return f"KokoroOnnxSynthesizer(voice={self.voice!r})"  # Never a host path.

    def engine(self) -> Any:
        """The loaded model, created once. Fails with a fixed code when anything is missing."""
        if "engine" not in self._loaded:
            if not (self.model_path.is_file() and self.voices_path.is_file()):
                raise SpeechError("neural_tts_files_missing")
            try:
                module = self.loader()
            except ImportError:
                raise SpeechError("neural_tts_unavailable") from None
            try:
                if self.threads is None:
                    with library_scratch(self.library_dir):
                        found = module.Kokoro(str(self.model_path), str(self.voices_path))
                else:
                    runtime = self.runtime()
                    options = runtime.SessionOptions()
                    options.intra_op_num_threads = self.threads
                    options.inter_op_num_threads = 1
                    session = runtime.InferenceSession(
                        str(self.model_path), options, providers=["CPUExecutionProvider"]
                    )
                    with library_scratch(self.library_dir):
                        found = module.Kokoro.from_session(session, str(self.voices_path))
                self._loaded["engine"] = found
            except Exception:
                raise SpeechError("neural_tts_load_failed") from None
        return self._loaded["engine"]

    def available(self) -> bool:
        """Whether this voice can speak here: package importable and both files loadable."""
        try:
            self.engine()
        except SpeechError:
            return False
        return True

    def speak(self, text: str, scratch: Path, stem: str) -> Speech:
        engine = self.engine()
        try:
            with library_scratch(self.library_dir):
                samples, rate = engine.create(
                    text, voice=self.voice, speed=self.speed, lang="en-us"
                )
        except Exception:
            raise SpeechError("neural_speech_failed") from None
        return neural_speech(samples, rate)


def voice_from_settings(
    settings: Settings,
    loader: Callable[[], Any] = kokoro_module,
    fallback: Callable[[], Voice] = detect,
) -> Voice:
    """The configured narration voice.

    `deterministic` is the operating-system voice. `kokoro_onnx` is the neural voice or a
    `SpeechError`; it never quietly becomes another voice. `auto` is the neural voice when it
    can load here, and the operating-system voice otherwise.
    """
    if settings.tts_provider == "deterministic":
        return fallback()
    neural = None
    if settings.tts_model_path and settings.tts_voices_path:
        neural = KokoroOnnxSynthesizer(
            Path(settings.tts_model_path),
            Path(settings.tts_voices_path),
            settings.tts_voice,
            settings.tts_speed,
            loader,
            settings.tts_threads,
            library_dir=Path(settings.tts_library_dir) if settings.tts_library_dir else None,
        )
    if settings.tts_provider == "kokoro_onnx":
        if neural is None:
            raise SpeechError("neural_tts_not_configured")  # Settings already refuse this.
        neural.engine()
        return neural
    return neural if neural is not None and neural.available() else fallback()


def safe_name(value: object) -> str:
    text = str(value)
    return text if SAFE_NAME.fullmatch(text) and os.sep not in text else "unnamed"


def voice_record(engine: Voice) -> dict[str, str]:
    """Which voice spoke, for the video metadata: provider, engine and voice names only."""
    if isinstance(engine, KokoroOnnxSynthesizer):
        return {"tts_provider": "kokoro_onnx", "tts_engine": engine.name, "tts_voice": engine.voice}
    name = safe_name(engine.name)
    provider = "deterministic" if isinstance(engine, Engine) else "local"
    return {"tts_provider": provider, "tts_engine": name, "tts_voice": name}

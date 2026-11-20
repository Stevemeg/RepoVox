"""Spoken narration: what is said, and the local voice that says it.

Text. The caption keeps the exact identifiers and code; this layer only changes how they are
said. Rules are fixed and ordered. They may rename an identifier to the role the Architecture
IR already assigned to it, expand a small set of code idioms, and split identifiers into
words. They never add a fact: every spoken sentence is a function of its caption and the IR.

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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repovox.core.config import Settings
from repovox.media.architecture import Architecture
from repovox.media.narration import Engine, NarrationError, Speech, Voice, audible, detect
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


@dataclass(frozen=True, repr=False)
class KokoroOnnxSynthesizer:
    """A local Kokoro ONNX voice. Approved printable-ASCII text in, validated PCM out."""

    model_path: Path
    voices_path: Path
    voice: str = "af_heart"
    speed: float = 1.0
    loader: Callable[[], Any] = kokoro_module  # Replaced only by tests.
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
                self._loaded["engine"] = module.Kokoro(str(self.model_path), str(self.voices_path))
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
            samples, rate = engine.create(text, voice=self.voice, speed=self.speed, lang="en-us")
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

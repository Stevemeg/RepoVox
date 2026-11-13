"""Local speech synthesis and sample-exact narration assembly.

Narration text reaches the engine through a file; it is never part of a command line. There is
no hosted speech API and no fallback tone: without a local engine, narration fails.
"""

import io
import math
import os
import shutil
import struct
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

FPS = 30
PAUSE_SECONDS = 0.35
# Fixed script: input/output paths come from the environment, never from interpolated text.
SAPI_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "try{$s.SetOutputToWaveFile($env:REPOVOX_TTS_OUT);"
    "$s.Speak([IO.File]::ReadAllText($env:REPOVOX_TTS_IN,[Text.Encoding]::UTF8))}"
    "finally{$s.Dispose()}"
)


class NarrationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Engine:
    name: str
    executable: Path


@dataclass(frozen=True)
class Speech:
    rate: int
    samples: bytes  # 16-bit little-endian mono PCM

    @property
    def seconds(self) -> float:
        return len(self.samples) / 2 / self.rate


@dataclass(frozen=True)
class Timing:
    start_frame: int
    frames: int
    speech_seconds: float


def detect() -> Engine:
    """Operating-system voice on Windows, espeak-ng elsewhere. Nothing is downloaded."""
    name, binary = (
        ("windows-sapi", "powershell")
        if sys.platform == "win32"
        else (
            "espeak-ng",
            "espeak-ng",
        )
    )
    found = shutil.which(binary)
    if found is None:
        raise NarrationError("narration_engine_unavailable")
    return Engine(name, Path(found).resolve(strict=True))


def read_wave(body: bytes) -> Speech:
    try:
        with wave.open(io.BytesIO(body), "rb") as source:
            channels, width, rate = (
                source.getnchannels(),
                source.getsampwidth(),
                source.getframerate(),
            )
            frames = source.readframes(source.getnframes())
    except (wave.Error, EOFError):
        raise NarrationError("speech_format_unsupported") from None
    if width != 2 or channels not in {1, 2} or not 8000 <= rate <= 48000:
        raise NarrationError("speech_format_unsupported")
    if channels == 2:
        pairs = struct.unpack(f"<{len(frames) // 2}h", frames)
        frames = struct.pack(
            f"<{len(pairs) // 2}h",
            *((pairs[i] + pairs[i + 1]) // 2 for i in range(0, len(pairs) - 1, 2)),
        )
    return Speech(rate, frames)


def synthesize(engine: Engine, text: str, scratch: Path, stem: str) -> Speech:
    if not text or len(text) > 600 or any(ord(c) < 32 or ord(c) > 126 for c in text):
        raise NarrationError("narration_text_rejected")
    source, target = scratch / f"{stem}.txt", scratch / f"{stem}.wav"
    source.write_text(text, encoding="utf-8", newline="\n")
    if engine.name == "windows-sapi":
        command = [
            str(engine.executable),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            SAPI_SCRIPT,
        ]
        env = {**os.environ, "REPOVOX_TTS_IN": str(source), "REPOVOX_TTS_OUT": str(target)}
    elif engine.name == "espeak-ng":
        command = [str(engine.executable), "-s", "155", "-w", str(target), "-f", str(source)]
        env = dict(os.environ)
    else:
        raise NarrationError("narration_engine_unavailable")
    try:
        result = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=120,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise NarrationError("speech_synthesis_failed") from None
    if result.returncode != 0 or not target.is_file():
        raise NarrationError("speech_synthesis_failed")
    speech = read_wave(target.read_bytes())
    count = len(speech.samples) // 2
    peak = max(map(abs, struct.unpack(f"<{count}h", speech.samples)), default=0)
    if speech.seconds < 0.2 or peak < 500:
        raise NarrationError("speech_silent")  # A silent or empty file is not narration.
    source.unlink()
    target.unlink()
    return speech


def assemble(parts: list[Speech]) -> tuple[bytes, list[Timing]]:
    """Concatenate speech with pauses so every sentence ends exactly on a video frame."""
    if not parts or len({p.rate for p in parts}) != 1:
        raise NarrationError("speech_format_unsupported")
    rate = parts[0].rate
    pcm = bytearray()
    timings: list[Timing] = []
    frame = 0
    for part in parts:
        frames = math.ceil((part.seconds + PAUSE_SECONDS) * FPS)
        pcm += part.samples
        end = round((frame + frames) * rate / FPS)
        pcm += b"\0\0" * (end - len(pcm) // 2)
        timings.append(Timing(frame, frames, part.seconds))
        frame += frames
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        target.writeframes(bytes(pcm))
    return buffer.getvalue(), timings

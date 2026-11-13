"""Stage transforms for reserved pipeline Stages 10-14: verified artifact bytes in, bytes out.

Each function re-validates its upstream artifacts instead of trusting them, so a worker can run
one stage per lease from stored objects. Nothing here touches the database or object storage.

  10 storyboard  verified analysis payload            -> storyboard JSON
  11 narration   payload + storyboard (re-verified)   -> narration script JSON
  12 tts         storyboard + script                  -> bundle {narration.wav, timings.json}
  13 render      storyboard + script + speech bundle  -> bundle {frameNNN.png..., captions.vtt}
  14 encode      speech bundle + frame bundle         -> validated video.mp4 + probe summary
"""

import io
import json
import re
import shutil
import subprocess
import tarfile
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from repovox.media import raster
from repovox.media.narration import FPS, Engine, Timing, assemble, synthesize
from repovox.media.storyboard import GroundingError, Storyboard, build, validate

Checkpoint = Callable[[], None]
MEMBER = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
BUNDLE_LIMIT = 96 * 1024**2
MAX_FRAMES = FPS * 600  # Ten minutes; a resource bound, not a duration target.


class RenderError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def noop() -> None:
    return None


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def bundle(files: dict[str, bytes]) -> bytes:
    """Deterministic uncompressed tar: sorted names, fixed metadata, regular files only."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name in sorted(files):
            if not MEMBER.fullmatch(name):
                raise RenderError("media_bundle_invalid")
            member = tarfile.TarInfo(name)
            member.size, member.mode, member.mtime = len(files[name]), 0o600, 0
            tar.addfile(member, io.BytesIO(files[name]))
    body = buffer.getvalue()
    if len(body) > BUNDLE_LIMIT:
        raise RenderError("media_bundle_invalid")
    return body


def unbundle(body: bytes) -> dict[str, bytes]:
    """Strict reader: flat safe names, regular files, no duplicates, bounded size."""
    if len(body) > BUNDLE_LIMIT:
        raise RenderError("media_bundle_invalid")
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:") as tar:
            for member in tar:
                if not member.isreg() or not MEMBER.fullmatch(member.name) or member.name in files:
                    raise RenderError("media_bundle_invalid")
                source = tar.extractfile(member)
                if source is None:
                    raise RenderError("media_bundle_invalid")
                files[member.name] = source.read()
    except (tarfile.TarError, OSError, EOFError):
        raise RenderError("media_bundle_invalid") from None
    return files


def load_board(body: bytes) -> Storyboard:
    try:
        return Storyboard.model_validate_json(body)
    except ValidationError:
        raise GroundingError("invalid_storyboard") from None


def script_for(board: Storyboard) -> list[dict[str, Any]]:
    return [
        {
            "sentence_id": sentence.id,
            "scene_id": scene.id,
            "text": sentence.text,
            "spoken": sentence.spoken,
            "technical": sentence.technical,
            "uncertainty": sentence.uncertainty,
            "claim_ids": list(sentence.claim_ids),
            "evidence_ids": list(sentence.evidence_ids),
        }
        for scene in board.scenes
        for sentence in scene.sentences
    ]


def checked_script(board: Storyboard, script: bytes) -> list[dict[str, Any]]:
    expected = script_for(board)
    if script != encoded(expected):
        raise GroundingError("speech_text_mismatch")  # Only approved narration is ever spoken.
    return expected


def storyboard_stage(payload: dict[str, Any]) -> bytes:
    return encoded(build(payload).model_dump(mode="json"))


def narration_stage(payload: dict[str, Any], storyboard: bytes) -> bytes:
    """Independent gate before speech: grounding and exact reproducibility from the payload."""
    board = load_board(storyboard)
    validate(board, payload)
    return encoded(script_for(board))


def timings_of(speech: dict[str, bytes], sentences: int) -> list[Timing]:
    try:
        raw = json.loads(speech["timings.json"])
        timings = [
            Timing(int(t["start_frame"]), int(t["frames"]), float(t["speech_seconds"])) for t in raw
        ]
        with wave.open(io.BytesIO(speech["narration.wav"]), "rb") as source:
            samples, rate = source.getnframes(), source.getframerate()
    except (KeyError, TypeError, ValueError, wave.Error, EOFError):
        raise RenderError("media_bundle_invalid") from None
    frame = 0
    for timing in timings:
        if timing.start_frame != frame or timing.frames <= 0:
            raise RenderError("media_bundle_invalid")
        frame += timing.frames
    if (
        set(speech) != {"narration.wav", "timings.json"}
        or len(timings) != sentences
        or not 0 < frame <= MAX_FRAMES
        or samples != round(frame * rate / FPS)
    ):
        raise RenderError("media_bundle_invalid")
    return timings


def tts_stage(
    storyboard: bytes,
    script: bytes,
    engine: Engine,
    scratch: Path,
    checkpoint: Checkpoint = noop,
) -> bytes:
    sentences = checked_script(load_board(storyboard), script)
    parts = []
    for i, sentence in enumerate(sentences):
        checkpoint()
        parts.append(synthesize(engine, sentence["spoken"], scratch, f"speech{i:03d}"))
    audio, timings = assemble(parts)
    checkpoint()
    return bundle(
        {
            "narration.wav": audio,
            "timings.json": encoded(
                [
                    {
                        "sentence_id": sentence["sentence_id"],
                        "start_frame": timing.start_frame,
                        "frames": timing.frames,
                        "speech_seconds": round(timing.speech_seconds, 6),
                    }
                    for sentence, timing in zip(sentences, timings, strict=True)
                ]
            ),
        }
    )


def timestamp(frame: int) -> str:
    milliseconds = round(frame * 1000 / FPS)
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    return f"{hours:02d}:{minutes:02d}:{rest // 1000:02d}.{rest % 1000:03d}"


def render_stage(
    storyboard: bytes, script: bytes, speech: bytes, checkpoint: Checkpoint = noop
) -> bytes:
    board = load_board(storyboard)
    sentences = checked_script(board, script)
    timings = timings_of(unbundle(speech), len(sentences))
    files: dict[str, bytes] = {}
    cues = ["WEBVTT", ""]
    index = 0
    for position, scene in enumerate(board.scenes):
        canvas = raster.base(board, scene, position)
        for sentence in scene.sentences:
            checkpoint()
            timing = timings[index]
            files[f"frame{index:03d}.png"] = raster.frame(canvas, sentence)
            end = timing.start_frame + timing.frames
            cues += [f"{timestamp(timing.start_frame)} --> {timestamp(end)}", sentence.text, ""]
            index += 1
    files["captions.vtt"] = "\n".join(cues).encode()
    return bundle(files)


def tool(name: str) -> Path:
    found = shutil.which(name)
    if found is None:
        raise RenderError(f"missing_installed_{name}")
    return Path(found).resolve(strict=True)


def command(args: list[str], cwd: Path, checkpoint: Checkpoint = noop, timeout: float = 170) -> str:
    """Fixed argument lists only; polls so a lost lease stops the encoder."""
    deadline = time.monotonic() + timeout
    with (cwd / "command.out").open("w+b") as output:
        try:
            process = subprocess.Popen(
                args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL
            )
        except OSError:
            raise RenderError("media_command_failed") from None
        try:
            while process.poll() is None:
                checkpoint()
                if time.monotonic() >= deadline:
                    raise RenderError("media_timeout")
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        if process.returncode != 0:
            raise RenderError("media_command_failed")
        output.seek(0)
        text = output.read().decode("utf-8", errors="replace")
    (cwd / "command.out").unlink()
    return text


def probe(
    work: Path, ffmpeg: Path, ffprobe: Path, frames: int, checkpoint: Checkpoint
) -> dict[str, Any]:
    """Check the encoded file itself: streams, exact frame count, duration and full decode."""
    try:
        data = json.loads(
            command(
                [
                    str(ffprobe),
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file",
                    "-count_frames",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    "video.mp4",
                ],
                work,
                checkpoint,
            )
        )
        streams = {s["codec_type"]: s for s in data["streams"]}
        video, audio = streams["video"], streams["audio"]
        if len(data["streams"]) != 2:
            raise RenderError("media_streams")
        if (
            (video["codec_name"], video["pix_fmt"], video["width"], video["height"])
            != ("h264", "yuv420p", raster.WIDTH, raster.HEIGHT)
            or video["avg_frame_rate"] != f"{FPS}/1"
            or int(video["nb_read_frames"]) != frames
        ):
            raise RenderError("media_video")
        if (audio["codec_name"], audio["sample_rate"], audio["channels"]) != ("aac", "48000", 1):
            raise RenderError("media_audio")
        duration, audio_duration = float(data["format"]["duration"]), float(audio["duration"])
    except (KeyError, TypeError, ValueError):
        raise RenderError("media_streams") from None
    if abs(duration - frames / FPS) > 0.1 or abs(audio_duration - frames / FPS) > 0.1:
        raise RenderError("media_duration")
    command(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-xerror",
            "-protocol_whitelist",
            "file",
            "-i",
            "video.mp4",
            "-f",
            "null",
            "-",
        ],
        work,
        checkpoint,
    )
    return {
        "video_codec": "h264",
        "audio_codec": "aac",
        "width": raster.WIDTH,
        "height": raster.HEIGHT,
        "fps": FPS,
        "video_frames": frames,
        "duration_seconds": duration,
        "audio_duration_seconds": audio_duration,
        "full_decode": "passed",
    }


def encode_stage(
    speech: bytes, frames: bytes, scratch: Path, checkpoint: Checkpoint = noop
) -> tuple[bytes, dict[str, Any]]:
    """Encode from re-validated bundles; return the MP4 only after it probes and fully decodes."""
    ffmpeg, ffprobe = tool("ffmpeg"), tool("ffprobe")
    audio, images = unbundle(speech), unbundle(frames)
    captions = images.pop("captions.vtt", None)
    timings = timings_of(audio, len(images))
    if captions is None or set(images) != {f"frame{i:03d}.png" for i in range(len(timings))}:
        raise RenderError("media_bundle_invalid")
    if any(not image.startswith(b"\x89PNG\r\n\x1a\n") for image in images.values()):
        raise RenderError("media_bundle_invalid")
    if any(scratch.iterdir()):
        raise RenderError("media_bundle_invalid")
    total = timings[-1].start_frame + timings[-1].frames
    # The concat list is regenerated from validated timings and fixed names, never stored input.
    concat = ["ffconcat version 1.0"]
    for i, timing in enumerate(timings):
        (scratch / f"frame{i:03d}.png").write_bytes(images[f"frame{i:03d}.png"])
        concat += [f"file frame{i:03d}.png", f"duration {timing.frames / FPS:.6f}"]
    concat.append(f"file frame{len(timings) - 1:03d}.png")
    (scratch / "frames.ffconcat").write_bytes(("\n".join(concat) + "\n").encode())
    (scratch / "narration.wav").write_bytes(audio["narration.wav"])
    command(
        [
            str(ffmpeg),
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-protocol_whitelist",
            "file",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            "frames.ffconcat",
            "-protocol_whitelist",
            "file",
            "-i",
            "narration.wav",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            f"fps={FPS},format=yuv420p",
            "-frames:v",
            str(total),
            "-t",
            f"{total / FPS:.6f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            "video.mp4",
        ],
        scratch,
        checkpoint,
    )
    summary = probe(scratch, ffmpeg, ffprobe, total, checkpoint)
    summary["sentences"] = len(timings)
    summary["captions"] = captions.decode("utf-8")
    summary["ffmpeg_version"] = command([str(ffmpeg), "-version"], scratch).splitlines()[0]
    return (scratch / "video.mp4").read_bytes(), summary

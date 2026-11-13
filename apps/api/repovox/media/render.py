"""Analysis payload -> grounded storyboard -> narrated H.264/AAC video bundle.

Only trusted FFmpeg argument lists and generated file names are used. Storyboard text never
becomes a shell command, filter expression, template or executable renderer input.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from repovox.analysis.common import digest
from repovox.media import raster
from repovox.media.narration import FPS, Engine, NarrationError, assemble, detect, synthesize
from repovox.media.storyboard import Storyboard, build

VERSION = "grounded-media-run-1.0"


class RenderError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def exclusive(path: Path, body: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def tool(name: str) -> Path:
    found = shutil.which(name)
    if found is None:
        raise RenderError(f"missing_installed_{name}")
    return Path(found).resolve(strict=True)


def command(args: list[str], cwd: Path, timeout: float = 600) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RenderError("media_command_failed") from None
    if result.returncode != 0:
        raise RenderError("media_command_failed")
    return result.stdout.decode("utf-8", errors="replace")


def timestamp(frame: int) -> str:
    milliseconds = round(frame * 1000 / FPS)
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    return f"{hours:02d}:{minutes:02d}:{rest // 1000:02d}.{rest % 1000:03d}"


def probe(work: Path, ffmpeg: Path, ffprobe: Path, frames: int) -> dict[str, Any]:
    """Check the encoded file itself: streams, exact frame count, duration and full decode."""
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
        )
    )
    streams = {s["codec_type"]: s for s in data["streams"]}
    video, audio = streams.get("video"), streams.get("audio")
    if len(data["streams"]) != 2 or video is None or audio is None:
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
    expected = frames / FPS
    if (
        abs(float(data["format"]["duration"]) - expected) > 0.1
        or abs(float(audio["duration"]) - expected) > 0.1
    ):
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
    )
    return {
        "video_codec": video["codec_name"],
        "audio_codec": audio["codec_name"],
        "width": video["width"],
        "height": video["height"],
        "fps": FPS,
        "video_frames": frames,
        "duration_seconds": float(data["format"]["duration"]),
        "audio_duration_seconds": float(audio["duration"]),
        "full_decode": "passed",
    }


def produce(
    payload: dict[str, Any],
    output: Path,
    *,
    engine: Engine | None = None,
    source_note: str = "analysis-payload",
) -> Path:
    """Render into a new directory; publish the whole bundle only after media validation."""
    started = time.perf_counter()
    board: Storyboard = build(payload)  # Raises before any output if grounding fails.
    ffmpeg, ffprobe = tool("ffmpeg"), tool("ffprobe")
    engine = engine or detect()
    if not output.is_absolute() or not output.parent.is_dir() or output.exists():
        raise RenderError("output_must_be_new_absolute_directory")
    output.mkdir(mode=0o700)
    work = output / "work"
    work.mkdir(mode=0o700)

    sentences = [(scene, sentence) for scene in board.scenes for sentence in scene.sentences]
    speech = [
        synthesize(engine, sentence.spoken, work, f"speech{i:03d}")
        for i, (_, sentence) in enumerate(sentences)
    ]
    audio, timings = assemble(speech)
    exclusive(work / "narration.wav", audio)

    canvases = {
        scene.id: raster.base(board, scene, position) for position, scene in enumerate(board.scenes)
    }
    concat = ["ffconcat version 1.0"]
    cues = ["WEBVTT", ""]
    narration: list[dict[str, Any]] = []
    for i, ((scene, sentence), timing) in enumerate(zip(sentences, timings, strict=True)):
        name = f"frame{i:03d}.png"
        exclusive(work / name, raster.frame(canvases[scene.id], sentence))
        concat += [f"file {name}", f"duration {timing.frames / FPS:.6f}"]
        end = timing.start_frame + timing.frames
        cues += [f"{timestamp(timing.start_frame)} --> {timestamp(end)}", sentence.text, ""]
        narration.append(
            {
                "sentence_id": sentence.id,
                "scene_id": scene.id,
                "text": sentence.text,
                "spoken": sentence.spoken,
                "uncertainty": sentence.uncertainty,
                "claim_ids": list(sentence.claim_ids),
                "evidence_ids": list(sentence.evidence_ids),
                "start_frame": timing.start_frame,
                "frames": timing.frames,
                "speech_seconds": round(timing.speech_seconds, 6),
            }
        )
    concat.append(f"file frame{len(sentences) - 1:03d}.png")
    total = timings[-1].start_frame + timings[-1].frames
    exclusive(work / "frames.ffconcat", ("\n".join(concat) + "\n").encode())
    exclusive(work / "captions.vtt", "\n".join(cues).encode())
    exclusive(work / "storyboard.json", encoded(board.model_dump(mode="json")))
    exclusive(work / "narration.json", encoded(narration))

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
        work,
    )
    validation = probe(work, ffmpeg, ffprobe, total)
    counts = payload["verification"]["counts"]
    manifest = {
        "version": VERSION,
        "status": "implementation output; not independently reviewed or accepted",
        "repository": board.repository,
        "commit_sha": board.commit_sha,
        "source": source_note,
        "analysis_sha256": board.analysis_sha256,
        "pipeline_version": board.pipeline_version,
        "verification_counts": counts,
        "storyboard_version": board.version,
        "scenes": len(board.scenes),
        "sentences": len(sentences),
        "technical_sentences": sum(s.technical for _, s in sentences),
        "cited_claims": len({c for scene in board.scenes for c in scene.claim_ids}),
        "narration_engine": engine.name,
        "model_inference": "none",
        "paid_services": "none",
        "ffmpeg_version": command([str(ffmpeg), "-version"], work).splitlines()[0],
        "platform": sys.platform,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "media": validation,
        "artifacts": {
            p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
            for p in sorted(work.iterdir())
        },
    }
    exclusive(work / "manifest.json", encoded(manifest))
    published = output / "published"
    os.rename(work, published)  # Unvalidated partial output is never published.
    return published / "video.mp4"


__all__ = ["NarrationError", "RenderError", "produce"]

"""Stage transforms for reserved pipeline Stages 10-14: verified artifact bytes in, bytes out.

Each function re-validates its upstream artifacts instead of trusting them, so a worker can run
one stage per lease from stored objects. Nothing here touches the database or object storage.

  10 storyboard  verified payload (+ verified story)  -> storyboard JSON, optionally worded
                 by the grounded narration model (refiner.GroundedLLMRefiner)
  11 narration   payload + storyboard (re-verified)   -> narration script JSON
  12 tts         storyboard + script                  -> bundle {narration.wav, timings.json,
                                                          voice.json}
  13 render      storyboard + script + speech bundle  -> bundle {frameNNN[-MMM].png, captions.vtt}
  14 encode      speech bundle + frame bundle         -> validated video.mp4 + probe summary

A problem-to-solution storyboard also needs the pinned source files at Stage 11, where the
story's citations are re-verified. Its diagram scenes are animated: a sentence is then drawn as
frameNNN-MMM.png, one image per ANIMATION_STEP video frames, instead of one frameNNN.png. The
last image of a sequence holds until the sentence ends, so a short intro (the overview's
tier-by-tier reveal, a component's spotlight) costs a few images while a workflow step moves
for its whole sentence.

Speech. Every voice is given `speech.audio_text`, the technical pronunciation of the approved
sentence; the storyboard, script, captions and citations are unchanged. A `speech.SpeechCache`
lets the narration stage speak ahead within its own lease (`prewarm`) for the speech stage.

Encoding. Each unique image is converted to the video's pixel format once, before frame-rate
duplication, and the encoded file is decoded once to verify its exact frame count. The time
limit scales with the video's length (`encode_timeout`); a stage's own deadline still bounds it.
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
from repovox.media.architecture import Citation, Report
from repovox.media.diagram import Diagram
from repovox.media.narration import FPS, NarrationError, Timing, Voice, assemble
from repovox.media.refiner import DETERMINISTIC, NarrativeRefiner
from repovox.media.speech import SpeechCache, audio_text, speak, voice_record
from repovox.media.story import EngineeringStory
from repovox.media.story_board import build_story_board, check_story_board
from repovox.media.story_view import NarrationView, story_view
from repovox.media.storyboard import (
    STORY_VERSION,
    GroundingError,
    Sentence,
    Storyboard,
    build,
    validate,
)

Checkpoint = Callable[[], None]
MEMBER = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
BUNDLE_LIMIT = 96 * 1024**2
MAX_FRAMES = FPS * 600  # Ten minutes; a resource bound, not a duration target.
ANIMATION_STEP = 6  # Video frames per animation image: five diagram updates per second.
PULSE_SECONDS = 1.6
ANIMATION_LIMIT = 240  # Animation images per video; later workflow sentences are drawn still.
REVEAL_STEPS = 2  # Images per tier while the architecture overview is revealed.
SPOTLIGHT = (0.3, 0.55, 0.8)  # Glow strengths before a spotlit sentence holds at full glow.
ENCODE_BASE_SECONDS, ENCODE_PER_MINUTE, ENCODE_MAX_SECONDS = 170.0, 30.0, 900.0
BADGES = {
    "verified": "VERIFIED",
    "inferred": "INFERRED",
    "documentation": "AUTHOR-STATED",
    "unverified": "UNVERIFIED",
    "none": "CONTEXT",
}


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


def storyboard_stage(
    payload: dict[str, Any],
    story: EngineeringStory | None = None,
    report: Report | None = None,
    refiner: NarrativeRefiner = DETERMINISTIC,
) -> bytes:
    """The walkthrough from the payload alone, or the engineering story for a verified story.

    Only the story is ever reworded, and only by a refiner whose wording Stage 11 re-checks.
    """
    if story is None:
        return encoded(build(payload).model_dump(mode="json"))
    return encoded(build_story_board(payload, story, report, refiner).model_dump(mode="json"))


def narration_record(storyboard: bytes) -> dict[str, Any] | None:
    """The grounded narrator's provenance, for a stage summary or manifest; fixed codes only."""
    board = load_board(storyboard)
    if board.story is None or board.story.narration is None:
        return None
    record: dict[str, Any] = board.story.narration.model_dump(mode="json")
    return record


UNNAMED_VOICE = {"tts_provider": None, "tts_engine": None, "tts_voice": None}


def voice_of(speech: bytes) -> dict[str, Any]:
    """The voice a Stage 12 bundle names; bundles made before voice.json name none."""
    raw = unbundle(speech).get("voice.json")
    if raw is None:
        return dict(UNNAMED_VOICE)
    try:
        found = json.loads(raw)
    except ValueError:
        raise RenderError("media_bundle_invalid") from None
    if not isinstance(found, dict) or set(found) != set(UNNAMED_VOICE):
        raise RenderError("media_bundle_invalid")
    return found


def video_narration(storyboard: bytes, speech: bytes) -> dict[str, Any]:
    """How the published walkthrough was worded and voiced, as stored in its metadata."""
    board = load_board(storyboard)
    record = narration_record(storyboard) or {
        "refiner": DETERMINISTIC.name,
        "provider": "deterministic",
        "model": None,
        "blueprint_sha256": None,
        "scenes_total": len(board.scenes),
        "scenes_refined": 0,
        "scenes_fallback": 0,
        "refined_scene_ids": [],
        "fallback_reason": None,
        "rejection_reasons": {},
    }
    try:
        view = NarrationView.model_validate({**record, **voice_of(speech)})
    except ValidationError:
        raise RenderError("media_bundle_invalid") from None
    found: dict[str, Any] = view.model_dump(mode="json")
    return found


def video_story(storyboard: bytes) -> dict[str, Any] | None:
    """The bounded public story view of a story storyboard; None for the walkthrough."""
    board = load_board(storyboard)
    view = story_view(board.story.story) if board.story is not None else None
    return None if view is None else view.model_dump(mode="json")


def is_story(storyboard: bytes) -> bool:
    return load_board(storyboard).version == STORY_VERSION


def narration_stage(
    payload: dict[str, Any], storyboard: bytes, sources: dict[str, bytes] | None = None
) -> bytes:
    """Independent gate before speech: grounding and exact reproducibility from the inputs."""
    board = load_board(storyboard)
    if board.version == STORY_VERSION:
        if sources is None:
            raise GroundingError("story_sources_required")
        check_story_board(board, payload, sources)
    else:
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
        set(speech) - {"voice.json"} != {"narration.wav", "timings.json"}
        or len(timings) != sentences
        or not 0 < frame <= MAX_FRAMES
        or samples != round(frame * rate / FPS)
    ):
        raise RenderError("media_bundle_invalid")
    return timings


def tts_stage(
    storyboard: bytes,
    script: bytes,
    engine: Voice,
    scratch: Path,
    checkpoint: Checkpoint = noop,
    cache: SpeechCache | None = None,
) -> bytes:
    sentences = checked_script(load_board(storyboard), script)
    parts = []
    for i, sentence in enumerate(sentences):
        checkpoint()
        said = audio_text(sentence["text"], sentence["spoken"])
        parts.append(speak(engine, said, scratch, f"speech{i:03d}", cache))
    audio, timings = assemble(parts)
    checkpoint()
    return bundle(
        {
            "narration.wav": audio,
            "voice.json": encoded(voice_record(engine)),  # Names only; never a file path.
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


def prewarm(
    storyboard: bytes,
    script: bytes,
    engine: Voice,
    scratch: Path,
    cache: SpeechCache,
    seconds: float,
    checkpoint: Checkpoint = noop,
) -> int:
    """Speak the approved script ahead into `cache` for at most `seconds`; never fails.

    Run by the narration stage after its own checks, inside its own lease. The speech stage
    then speaks the same approved sentences and finds them cached. A voice error stops the
    warm-up; the speech stage reports it with its own code.
    """
    started = time.monotonic()
    sentences = checked_script(load_board(storyboard), script)
    spoken = 0
    for i, sentence in enumerate(sentences):
        if time.monotonic() - started >= seconds:
            break
        checkpoint()
        try:
            speak(
                engine,
                audio_text(sentence["text"], sentence["spoken"]),
                scratch,
                f"warm{i:03d}",
                cache,
            )
        except NarrationError:
            break
        spoken += 1
    return spoken


def encode_timeout(
    seconds: float,
    base: float = ENCODE_BASE_SECONDS,
    per_minute: float = ENCODE_PER_MINUTE,
    cap: float = ENCODE_MAX_SECONDS,
) -> float:
    """Time allowed to encode, or to verify, a video of `seconds`: base plus a share per
    minute, never more than `cap`. A media stage's deadline still bounds the whole stage."""
    return min(cap, base + per_minute * max(0.0, seconds) / 60)


def timestamp(frame: int) -> str:
    milliseconds = round(frame * 1000 / FPS)
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    return f"{hours:02d}:{minutes:02d}:{rest // 1000:02d}.{rest % 1000:03d}"


def story_diagram(board: Storyboard) -> Diagram | None:
    """The diagram of a story's primary architecture, in the view its claims were drawn from."""
    attachment = board.story
    if attachment is None or attachment.architecture is None:
        return None
    description = attachment.story.architecture
    primary = next(
        (a for a in attachment.architecture.architectures if a.id == description.primary), None
    )
    if primary is None:
        return None
    view = next((v for v in primary.views if v.id == description.view), None)
    return Diagram(primary, board.repository, board.commit_sha, view)


def citation_for(diagram: Diagram, sentence: Sentence) -> Citation | None:
    connections = {c.id: c for c in diagram.architecture.connections}
    components = {c.id: c for c in diagram.architecture.components}
    for identity in sentence.connection_ids:
        if identity in connections:
            return connections[identity].citations[0]
    for identity in sentence.component_ids:
        if identity in components:
            return components[identity].citations[0]
    return None


def animation_count(frames: int) -> int:
    return -(-frames // ANIMATION_STEP)


def diagram_frames(
    drawn: Diagram,
    components: tuple[str, ...],
    connections: tuple[str, ...],
    badge: str,
    text: str,
    citation: Citation | None,
    position: int,
    total: int,
    frames: int,
    *,
    mode: str,
    step: tuple[int, int] | None = None,
    budget: int = ANIMATION_LIMIT,
    checkpoint: Checkpoint = noop,
) -> list[bytes]:
    """The images of one narrated diagram sentence; the last one holds until it ends.

    `flow`: the step's relationships are drawn from source to target, then a packet travels
    along them for the whole sentence. `reveal`: tier bands appear one by one. `spotlight`:
    the narrated components' glow rises to full. `still`: one image. Never more than `budget`
    images; a sentence that would exceed it is drawn as its final still image.
    """
    count = animation_count(frames)

    def frame(**options: Any) -> raster.Canvas:
        return drawn.base(
            components, connections, badge, text, citation, position, total, **options
        )

    final = frame(step=step)
    if mode == "flow" and connections and count <= budget:
        pending = frame(step=step, pending=True, glow=0)
        images = []
        for j in range(count):
            checkpoint()
            phase = (j * ANIMATION_STEP / FPS) / PULSE_SECONDS
            images.append(drawn.animate(pending, connections, phase, j / max(1, count - 1)))
        return images
    if mode == "reveal" and len(drawn.bands) > 1:
        shown = [r for r in range(1, len(drawn.bands)) for _ in range(REVEAL_STEPS)]
        if len(shown) + 1 <= min(count, budget):
            images = [frame(reveal=r, glow=0).png(1) for r in shown]
            return [*images, final.png()]
    if mode == "spotlight" and components and len(SPOTLIGHT) + 1 <= min(count, budget):
        images = [frame(step=step, glow=strength).png(1) for strength in SPOTLIGHT]
        return [*images, final.png()]
    return [final.png()]


def render_stage(
    storyboard: bytes, script: bytes, speech: bytes, checkpoint: Checkpoint = noop
) -> bytes:
    board = load_board(storyboard)
    sentences = checked_script(board, script)
    timings = timings_of(unbundle(speech), len(sentences))
    diagram = story_diagram(board) if any(scene.diagram for scene in board.scenes) else None
    files: dict[str, bytes] = {}
    cues = ["WEBVTT", ""]
    index = animated = 0
    for position, scene in enumerate(board.scenes):
        drawn = diagram if scene.diagram else None
        canvas = raster.base(board, scene, position) if drawn is None else None
        steps = [s.id for s in scene.sentences if s.connection_ids]
        for order, sentence in enumerate(scene.sentences):
            checkpoint()
            timing = timings[index]
            if drawn is not None:
                if scene.type == "workflow" and sentence.connection_ids:
                    mode = "flow"
                elif scene.type == "architecture" and order == 0:
                    mode = "reveal"
                else:
                    mode = "spotlight"
                step = (
                    (steps.index(sentence.id) + 1, len(steps))
                    if scene.type == "workflow" and sentence.id in steps
                    else None
                )
                images = diagram_frames(
                    drawn,
                    sentence.component_ids,
                    sentence.connection_ids,
                    BADGES[sentence.uncertainty],
                    sentence.text,
                    citation_for(drawn, sentence),
                    index,
                    len(sentences),
                    timing.frames,
                    mode=mode,
                    step=step,
                    budget=ANIMATION_LIMIT - animated,
                    checkpoint=checkpoint,
                )
                if len(images) == 1:
                    files[f"frame{index:03d}.png"] = images[0]
                else:
                    for j, image in enumerate(images):
                        files[f"frame{index:03d}-{j:03d}.png"] = image
                    animated += len(images)
            elif canvas is not None:
                files[f"frame{index:03d}.png"] = raster.frame(canvas, sentence)
            else:
                raise GroundingError("invalid_storyboard")
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


def decoded_frames(progress: str) -> int:
    """The final decoded video frame count reported by `ffmpeg -progress`."""
    found = re.findall(r"^frame=(\d+)$", progress, re.MULTILINE)
    if not found or "progress=end" not in progress:
        raise RenderError("media_video")
    return int(found[-1])


def probe(
    work: Path,
    ffmpeg: Path,
    ffprobe: Path,
    frames: int,
    checkpoint: Checkpoint,
    timeout: float = ENCODE_BASE_SECONDS,
) -> dict[str, Any]:
    """Check the encoded file itself: streams, exact frame count, duration and full decode.

    The streams are read without decoding; one complete decode then both proves the file
    decodes without error and counts its frames exactly.
    """
    try:
        data = json.loads(
            command(
                [
                    str(ffprobe),
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file",
                    "-count_packets",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    "video.mp4",
                ],
                work,
                checkpoint,
                timeout,
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
            or int(video["nb_read_packets"]) != frames
        ):
            raise RenderError("media_video")
        if (audio["codec_name"], audio["sample_rate"], audio["channels"]) != ("aac", "48000", 1):
            raise RenderError("media_audio")
        duration, audio_duration = float(data["format"]["duration"]), float(audio["duration"])
    except (KeyError, TypeError, ValueError):
        raise RenderError("media_streams") from None
    if abs(duration - frames / FPS) > 0.1 or abs(audio_duration - frames / FPS) > 0.1:
        raise RenderError("media_duration")
    progress = command(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-xerror",
            "-nostats",
            "-protocol_whitelist",
            "file",
            "-i",
            "video.mp4",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-progress",
            "pipe:1",
            "-f",
            "null",
            "-",
        ],
        work,
        checkpoint,
        timeout,
    )
    if decoded_frames(progress) != frames:
        raise RenderError("media_video")
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


def encode_sequence(
    scratch: Path,
    entries: list[tuple[str, int]],
    wav: bytes,
    checkpoint: Checkpoint = noop,
    timeout: float | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Encode image files already in scratch, each shown for a whole number of video frames.

    The concat list is generated here from fixed names and integer durations, never stored input.
    Each image is converted to the output pixel format once, before frame-rate duplication.
    `timeout` limits each encoder and probe command; by default it scales with the video length.
    """
    ffmpeg, ffprobe = tool("ffmpeg"), tool("ffprobe")
    total = sum(frames for _, frames in entries)
    if (
        not entries
        or not 0 < total <= MAX_FRAMES
        or any(frames <= 0 or not MEMBER.fullmatch(name) for name, frames in entries)
    ):
        raise RenderError("media_bundle_invalid")
    concat = ["ffconcat version 1.0"]
    for name, frames in entries:
        concat += [f"file {name}", f"duration {frames / FPS:.6f}"]
    concat.append(f"file {entries[-1][0]}")
    (scratch / "frames.ffconcat").write_bytes(("\n".join(concat) + "\n").encode())
    (scratch / "narration.wav").write_bytes(wav)
    limit = encode_timeout(total / FPS) if timeout is None else timeout
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
            f"format=yuv420p,fps={FPS}",
            "-frames:v",
            str(total),
            "-t",
            f"{total / FPS:.6f}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",  # Measured: about 2x veryfast on one CPU; graphics stay sharp at CRF 20.
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
        limit,
    )
    summary = probe(scratch, ffmpeg, ffprobe, total, checkpoint, limit)
    summary["ffmpeg_version"] = command([str(ffmpeg), "-version"], scratch).splitlines()[0]
    return (scratch / "video.mp4").read_bytes(), summary


def sequence_entries(images: dict[str, bytes], timings: list[Timing]) -> list[tuple[str, int]]:
    """(image name, video frames) for every sentence, in order. Refuses anything else.

    A sentence is one still image (frameNNN.png) shown for all its frames, or a sequence
    (frameNNN-MMM.png) whose images each last ANIMATION_STEP frames and whose last image holds
    until the sentence ends. A gap, an extra image or a sequence longer than the sentence is
    refused.
    """
    entries: list[tuple[str, int]] = []
    for i, timing in enumerate(timings):
        still = f"frame{i:03d}.png"
        if still in images:
            entries.append((still, timing.frames))
            continue
        count = 0
        while f"frame{i:03d}-{count:03d}.png" in images:
            count += 1
        if not 0 < count <= animation_count(timing.frames):
            raise RenderError("media_bundle_invalid")
        for j in range(count):
            last = j == count - 1
            entries.append(
                (
                    f"frame{i:03d}-{j:03d}.png",
                    timing.frames - ANIMATION_STEP * j if last else ANIMATION_STEP,
                )
            )
    if set(images) != {name for name, _ in entries} or len(entries) != len(images):
        raise RenderError("media_bundle_invalid")
    return entries


def encode_stage(
    speech: bytes,
    frames: bytes,
    scratch: Path,
    checkpoint: Checkpoint = noop,
    timeout: Callable[[float], float] = encode_timeout,
) -> tuple[bytes, dict[str, Any]]:
    """Encode from re-validated bundles; return the MP4 only after it probes and fully decodes."""
    tool("ffmpeg"), tool("ffprobe")
    audio, images = unbundle(speech), unbundle(frames)
    captions = images.pop("captions.vtt", None)
    sentences = len({name.split("-")[0].removesuffix(".png") for name in images})
    timings = timings_of(audio, sentences)
    entries = sequence_entries(images, timings)
    if captions is None:
        raise RenderError("media_bundle_invalid")
    if any(not image.startswith(b"\x89PNG\r\n\x1a\n") for image in images.values()):
        raise RenderError("media_bundle_invalid")
    if any(scratch.iterdir()):
        raise RenderError("media_bundle_invalid")
    for name, _ in entries:
        (scratch / name).write_bytes(images[name])
    seconds = sum(frames for _, frames in entries) / FPS
    video, summary = encode_sequence(
        scratch, entries, audio["narration.wav"], checkpoint, timeout(seconds)
    )
    summary["sentences"] = len(timings)
    summary["captions"] = captions.decode("utf-8")
    return video, summary

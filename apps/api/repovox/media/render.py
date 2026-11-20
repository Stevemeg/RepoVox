"""Analysis payload -> narrated video bundle on local disk, by chaining the stage transforms.

This is the same code path a worker runs one stage at a time; here it runs in one process and
publishes the whole bundle only after the encoded file has been validated. Given the pinned
story sources, the video is the problem-to-solution engineering story; without them it is the
grounded walkthrough. Like `repovox.media.local`, this path parses in-process and is for the
operator's own repositories only.
"""

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from repovox.analysis.common import digest
from repovox.media.architecture import ArchitectureError, Report, discover
from repovox.media.narration import NarrationError, Voice, detect
from repovox.media.refiner import DETERMINISTIC, NarrativeRefiner
from repovox.media.stages import (
    RenderError,
    encode_stage,
    encoded,
    narration_record,
    narration_stage,
    render_stage,
    storyboard_stage,
    tool,
    tts_stage,
    unbundle,
)
from repovox.media.story import EngineeringStory
from repovox.media.story_extract import extract_story

VERSION = "grounded-media-run-1.0"


def engineering_story(
    payload: dict[str, Any], sources: dict[str, bytes]
) -> tuple[EngineeringStory, Report | None]:
    """Architecture IR and the verified story from exactly the inventoried story sources."""
    manifest = {f["path"]: f for f in payload["knowledge"]["coverage"]["files"]}
    parsed = {p: b for p, b in sources.items() if manifest[p]["status"] in {"parsed", "context"}}
    report: Report | None
    try:
        report, missing = discover(payload, parsed), None
    except ArchitectureError as error:
        report, missing = None, error.code
    return extract_story(payload, sources, report, missing), report


def exclusive(path: Path, body: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def produce(
    payload: dict[str, Any],
    output: Path,
    *,
    engine: Voice | None = None,
    source_note: str = "analysis-payload",
    sources: dict[str, bytes] | None = None,
    refiner: NarrativeRefiner = DETERMINISTIC,
) -> Path:
    """Render into a new directory; publish the whole bundle only after media validation."""
    started = time.perf_counter()
    story: EngineeringStory | None = None
    if sources is not None:
        story, report = engineering_story(payload, sources)
        storyboard = storyboard_stage(payload, story, report, refiner)
    else:
        storyboard = storyboard_stage(payload)  # Raises before any output if grounding fails.
    script = narration_stage(payload, storyboard, sources)
    narration = narration_record(storyboard)
    tool("ffmpeg"), tool("ffprobe")
    engine = engine or detect()
    if not output.is_absolute() or not output.parent.is_dir() or output.exists():
        raise RenderError("output_must_be_new_absolute_directory")
    output.mkdir(mode=0o700)
    work, speech_scratch, encode_scratch = output / "work", output / "speech", output / "encode"
    for directory in (work, speech_scratch, encode_scratch):
        directory.mkdir(mode=0o700)

    speech = tts_stage(storyboard, script, engine, speech_scratch)
    frames = render_stage(storyboard, script, speech)
    video, media = encode_stage(speech, frames, encode_scratch)

    audio, images = unbundle(speech), unbundle(frames)
    timings = {t["sentence_id"]: t for t in json.loads(audio["timings.json"])}
    sentences = json.loads(script)
    timed = [{**sentence, **timings[sentence["sentence_id"]]} for sentence in sentences]
    board = json.loads(storyboard)
    exclusive(work / "storyboard.json", storyboard)
    exclusive(work / "narration.json", encoded(timed))
    exclusive(work / "narration.wav", audio["narration.wav"])
    for name, body in images.items():
        exclusive(work / name, body)
    exclusive(work / "video.mp4", video)
    captions = media.pop("captions")
    manifest = {
        "version": VERSION,
        "status": "implementation output; not independently reviewed or accepted",
        "repository": board["repository"],
        "commit_sha": board["commit_sha"],
        "source": source_note,
        "analysis_sha256": board["analysis_sha256"],
        "pipeline_version": board["pipeline_version"],
        "verification_counts": payload["verification"]["counts"],
        "storyboard_version": board["version"],
        "scenes": len(board["scenes"]),
        "sentences": len(sentences),
        "technical_sentences": sum(s["technical"] for s in sentences),
        "cited_claims": len({c for scene in board["scenes"] for c in scene["claim_ids"]}),
        "scene_types": [scene["type"] for scene in board["scenes"]],
        "story": None
        if story is None
        else {
            "schema_version": story.schema_version,
            "problem_statement": story.problem_statement.sufficiency,
            "architecture": story.architecture.explanation,
            "claims": dict(sorted(Counter(c.status for c in story.claims().values()).items())),
            "mismatches": sorted(m.kind for m in story.mismatches),
            "instruction_like_lines": story.instruction_like_lines,
        },
        "uncertainty_labels": dict(sorted(Counter(s["uncertainty"] for s in sentences).items())),
        "narration_engine": engine.name,
        # A grounded narration model only rewords the verified plan; see `narration`.
        "model_inference": "none" if narration is None else "grounded-narration-refinement",
        "paid_services": "none"
        if narration is None or narration["provider"] == "ollama"
        else "operator-configured hosted narration model",
        "narration": narration,
        "ffmpeg_version": media.pop("ffmpeg_version"),
        "platform": sys.platform,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "media": media,
        "captions_sha256": digest(captions.encode()),
        "artifacts": {
            p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
            for p in sorted(work.iterdir())
        },
    }
    exclusive(work / "manifest.json", encoded(manifest))
    for directory in (speech_scratch, encode_scratch):
        for leftover in directory.iterdir():
            leftover.unlink()
        directory.rmdir()
    os.rename(work, output / "published")  # Unvalidated partial output is never published.
    return output / "published" / "video.mp4"


__all__ = ["NarrationError", "RenderError", "produce"]

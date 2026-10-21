"""Synthetic-only contracts, actual media decoding and process-kill recovery."""

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from experiments.offline_media import runner
from experiments.offline_media.contracts import (
    FIXTURES,
    Grounding,
    original_sources,
    sha,
    storyboard,
    validate_grounding,
)
from experiments.offline_media.raster import Canvas, render
from pydantic import ValidationError


def raw():
    return json.loads((FIXTURES / "facts.json").read_bytes())


def checked(value):
    g = Grounding.model_validate_json(json.dumps(value))
    validate_grounding(g, original_sources())
    return g


def test_closed_deterministic_storyboard_and_raster():
    sources = original_sources()
    g = checked(raw())
    board = storyboard(g, sources)
    assert board == storyboard(g, sources)
    assert [s.start_frame for s in board.scenes] == [0, 90, 180, 270, 360, 450]
    assert sum(s.frames for s in board.scenes) == 540
    assert set(f.id for f in g.facts) == set(board.scenes[-1].fact_ids)
    assert len([f for f in g.facts if f.kind == "static_call"]) == 3
    for scene in board.scenes:
        first = render(scene, g, sources)
        assert first == render(scene, g, sources)
        assert first.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("sha256", "0" * 64, "citation_hash"),
        ("start_byte", 9000, "citation_range"),
        ("start_line", 99, "citation_start_line"),
        ("end_line", 99, "citation_end_line"),
        ("quote", "def invented(", "citation_original_bytes"),
        ("path", "../../private.key", "source_not_fictional_allowlist"),
        ("path", "https://example.invalid/source.py", "source_not_fictional_allowlist"),
        ("quote", "\x1b[31m", "unsafe_text"),
        ("quote", "<script>bad()</script>", "unsafe_text"),
        ("quote", "$(unsafe)", "unsafe_text"),
    ],
)
def test_malformed_or_unsafe_citations(field, value, reason):
    data = raw()
    data["facts"][0]["citation"][field] = value
    with pytest.raises((ValueError, ValidationError), match=reason):
        checked(data)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda d: d["facts"][0].update(status="verified_runtime"), "observed_syntax"),
        (lambda d: d["facts"][0].update(kind="documentation_only"), "declaration"),
        (lambda d: d["facts"][0].update(subject="not_in_source"), "declaration_binding"),
        (lambda d: d["facts"][2].update(target="missing"), "unbound_static_relationship"),
        (lambda d: d["facts"][2].update(subject="brighten"), "caller_scope"),
        (lambda d: d["facts"][0].update(language="typescript"), "source_language"),
        (lambda d: d["facts"][1].update(id=d["facts"][0]["id"]), "duplicate_fact"),
        (lambda d: d["sources"][0].update(sha256="f" * 64), "source_commitment"),
        (lambda d: d.update(synthetic=False), "True"),
        (lambda d: d.update(scene_code="exec(...)"), "Extra inputs"),
    ],
)
def test_unsupported_forged_or_duplicate_facts(mutation, reason):
    data = raw()
    mutation(data)
    with pytest.raises((ValueError, ValidationError), match=reason):
        checked(data)


def test_empty_evidence_and_changed_original_source():
    data = raw()
    data["facts"][2]["citation"]["end_byte"] = data["facts"][2]["citation"]["start_byte"]
    with pytest.raises(ValueError, match="citation_range"):
        checked(data)
    sources = original_sources()
    sources["ripple.py"] += b"# altered\n"
    with pytest.raises(ValueError, match="source_commitment"):
        validate_grounding(checked(raw()), sources)


def test_overflow_is_rejected_not_clipped():
    c = Canvas()
    for action in [
        lambda: c.text(64, 200, "x" * 1000),
        lambda: c.rect(-1, 0, 20, 20, (0, 0, 0)),
        lambda: c.text(64, 719, "overflow"),
        lambda: c.text(64, 200, "unsafe\ntext"),
    ]:
        with pytest.raises(ValueError, match="visual|overflow"):
            action()


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    # Missing FFmpeg is a failure, not a skip; the experiment requires it.
    parent = tmp_path_factory.mktemp("synthetic_media")
    root = parent / "run"
    video = runner.run(root)
    return root, video


def test_real_media_properties_pixels_hashes_and_no_network(rendered, tmp_path, monkeypatch):
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket, "socket", refuse)
    root, video = rendered
    v = json.loads((video.parent / "validation.json").read_bytes())
    assert v["video"]["codec_name"] == "h264" and v["audio"]["codec_name"] == "aac"
    assert v["video_frames"] == 540 and v["duration_seconds"] == 18
    assert len(v["boundary_mean_absolute_rgb_errors"]) == 12
    assert max(v["boundary_mean_absolute_rgb_errors"]) < 4
    m = json.loads((video.parent / "metrics.json").read_bytes())
    assert m["artifacts"]["video.mp4"]["sha256"] == sha(video.read_bytes())
    assert m["encoding"]["exit_code"] == 0
    assert json.loads((root / "journal.json").read_bytes())["state"] == "PUBLISHED"
    # Repeat under the same installed binaries: storyboard, pixels and MP4 bytes
    # must agree; clocks/run IDs/metrics are intentionally not byte-identical.
    other = runner.run(tmp_path / "repeat")
    assert sha(other.read_bytes()) == sha(video.read_bytes())
    assert (other.parent / "storyboard.json").read_bytes() == (
        video.parent / "storyboard.json"
    ).read_bytes()


def test_bad_encoder_does_not_publish_partial_media(tmp_path, monkeypatch):
    def fail(args, cwd, *a, **kw):
        (cwd / "video.mp4").write_bytes(b"partial not a video")
        raise RuntimeError("synthetic_encoder_failure")

    monkeypatch.setattr(runner, "command", fail)
    root = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="synthetic_encoder_failure"):
        runner.run(root)
    assert not (root / "published").exists()
    runner.cleanup(root)
    assert not runner.inventory(root)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("width", 640, "media_geometry"),
        ("codec_name", "mpeg4", "media_video_codec"),
        ("nb_read_frames", "539", "media_frame_count"),
    ],
)
def test_probe_validation_rejects_wrong_media(rendered, monkeypatch, field, value, reason):
    root, video = rendered
    stored = json.loads((video.parent / "validation.json").read_bytes())
    data = json.loads(stored["original_ffprobe_stdout"])
    next(s for s in data["streams"] if s["codec_type"] == "video")[field] = value
    monkeypatch.setattr(runner, "command", lambda *a, **k: dict(stdout=json.dumps(data)))
    with runner.locked(root) as lock, pytest.raises(ValueError, match=reason):
        runner.validate_media(video.parent, Path("not-invoked"), Path("not-invoked"), lock)


@pytest.mark.parametrize(
    "mutation,reason", [("changed_frame", "raster_changed"), ("extra_file", "unexpected_file")]
)
def test_encoding_side_effect_cannot_publish_unbound_bundle(
    tmp_path, monkeypatch, mutation, reason
):
    actual_command = runner.command

    def altered(args, cwd, *a, **kw):
        result = actual_command(args, cwd, *a, **kw)
        if "-benchmark" in args:
            target = "scene00.png" if mutation == "changed_frame" else "extra.txt"
            (cwd / target).write_bytes(b"unbound synthetic bytes")
        return result

    monkeypatch.setattr(runner, "command", altered)
    root = tmp_path / mutation
    with pytest.raises(ValueError, match=reason):
        runner.run(root)
    assert not (root / "published").exists()


def test_cleanup_unexpected_files_and_links_never_delete_sentinel(rendered, tmp_path):
    root, _ = rendered
    clone = tmp_path / "clone"
    shutil.copytree(root, clone)
    # A copied provisioning identity cannot authorize cleanup of a different path.
    with pytest.raises(ValueError, match="wrong_namespace"):
        runner.cleanup(clone)
    sentinel = tmp_path / "unrelated.txt"
    sentinel.write_bytes(b"KEEP UNCHANGED")
    own = tmp_path / "own"
    runner.run(own)
    unexpected = own / "work-unregistered"
    unexpected.write_bytes(b"unexpected")
    before = (own / "published" / "video.mp4").read_bytes()
    with pytest.raises(ValueError, match="unexpected_file"):
        runner.cleanup(own)
    assert (own / "published" / "video.mp4").read_bytes() == before
    unexpected.unlink()
    link = own / "published" / "audio.wav"
    link.unlink()
    os.link(sentinel, link)
    with pytest.raises(ValueError, match="unexpected_file"):
        runner.cleanup(own)
    assert sentinel.read_bytes() == b"KEEP UNCHANGED"
    link.unlink()
    runner.cleanup(own)
    runner.cleanup(own)
    assert not runner.inventory(own)
    with pytest.raises(ValueError, match="output_already_exists"):
        runner.run(own)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows symlink privilege not assumed; real Linux case mandatory",
)
def test_symlink_escape_refused(tmp_path, rendered):
    sentinel = tmp_path / "outside"
    sentinel.write_bytes(b"UNRELATED")
    root = tmp_path / "symlink"
    runner.run(root)
    path = root / "published" / "audio.wav"
    path.unlink()
    path.symlink_to(sentinel)
    with pytest.raises(ValueError, match="path_link"):
        runner.cleanup(root)
    assert sentinel.read_bytes() == b"UNRELATED"


def killed_at(root: Path, operation: str, point: str) -> None:
    p = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "experiments.offline_media",
            operation,
            "--output",
            str(root),
            "--pause-at",
            point,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lines = []
    ready = threading.Event()

    def read():
        assert p.stdout is not None
        lines.append(p.stdout.readline())
        ready.set()

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    try:
        assert ready.wait(20), "fault point not reached"
        assert lines == ["PAUSED:" + point + "\n"]
        if operation == "render":
            with pytest.raises(OSError):
                runner.cleanup(root)  # A live writer's lock must exclude cleanup.
    finally:
        p.kill()
        p.communicate(timeout=10)
        thread.join(timeout=2)
    assert p.returncode != 0


@pytest.mark.parametrize("point", ["before_frame", "during_frame", "before_validate"])
def test_forced_termination_no_false_publication_and_recoverable_cleanup(tmp_path, point):
    root = tmp_path / point
    sentinel = tmp_path / "unrelated"
    sentinel.write_bytes(b"KEEP")
    killed_at(root, "render", point)
    assert not (root / "published").exists()
    assert json.loads((root / "journal.json").read_bytes())["state"] != "PUBLISHED"
    runner.cleanup(root)
    assert not runner.inventory(root)
    assert sentinel.read_bytes() == b"KEEP"


def test_killed_cleanup_recovers_idempotently_without_reopening(tmp_path):
    root = tmp_path / "cleanup"
    runner.run(root)
    killed_at(root, "cleanup", "during_cleanup")
    assert json.loads((root / "journal.json").read_bytes())["state"] == "CLEANING"
    runner.cleanup(root)
    runner.cleanup(root)
    assert json.loads((root / "journal.json").read_bytes())["state"] == "CLEANED"
    assert not runner.inventory(root)


def test_relative_and_parent_paths_are_rejected(tmp_path):
    for p in [Path("relative"), tmp_path / ".." / "escape"]:
        with pytest.raises(ValueError, match="unsafe_output_path"):
            runner.run(p)

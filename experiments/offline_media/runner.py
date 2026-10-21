"""Local synthetic-only renderer, explicit managed output, atomic bundle publish."""

import argparse
import contextlib
import io
import json
import math
import os
import shutil
import stat
import struct
import subprocess
import sys
import time
import uuid
import wave
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from .contracts import FIXTURES, Grounding, original_sources, require, sha, storyboard
from .raster import render

VERSION = "offline-media-run-1.0"
FILES = {
    *(f"scene{i:02d}.png" for i in range(6)),
    "audio.wav",
    "scenes.ffconcat",
    "storyboard.json",
    "video.mp4",
    "validation.json",
    "metrics.json",
}
META = {"identity.json", "journal.json", "journal.next", "lock"}


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def ancestry(path: Path) -> None:
    require(path.is_absolute() and ".." not in path.parts, "unsafe_output_path")
    for p in (path, *path.parents):
        if p.exists() or p.is_symlink():
            s = p.lstat()
            require(
                not stat.S_ISLNK(s.st_mode) and not getattr(s, "st_reparse_tag", 0), "path_link"
            )


def exclusive(path: Path, body: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def journal(root: Path, state: str) -> None:
    value = encoded(dict(version=VERSION, state=state))
    exclusive(root / "journal.next", value)
    os.replace(root / "journal.next", root / "journal.json")


def identify(root: Path) -> dict[str, Any]:
    ancestry(root)
    require(root.is_dir(), "missing_managed_root")
    path = root / "identity.json"
    require(
        path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1, "invalid_identity"
    )
    require(path.stat().st_size < 4096, "invalid_identity")
    identity: dict[str, Any] = json.loads(path.read_bytes())
    require(identity["version"] == VERSION and identity["root"] == str(root), "wrong_namespace")
    require(str(uuid.UUID(identity["run_id"])) == identity["run_id"], "invalid_identity")
    require(
        identity["synthetic"] is True and identity["files"] == sorted(FILES), "invalid_identity"
    )
    return identity


@contextlib.contextmanager
def locked(root: Path) -> Iterator[BinaryIO]:
    identify(root)
    path = root / "lock"
    require(path.is_file() and path.stat().st_nlink == 1 and not path.is_symlink(), "lock_link")
    with path.open("r+b") as handle:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield handle
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def pause(point: str, requested: str | None) -> None:
    if point == requested:
        print("PAUSED:" + point, flush=True)
        time.sleep(30)  # Bounded synthetic fault hook; tests forcibly terminate here.
        raise RuntimeError("fault_pause_elapsed")


def inventory(root: Path) -> list[Path]:
    identify(root)
    found = []
    for child in root.iterdir():
        ancestry(child)
        if child.name in {"work", "published"}:
            require(child.is_dir(), "unexpected_file")
            for p in child.iterdir():
                ancestry(p)
                require(
                    p.name in FILES and p.is_file() and p.stat().st_nlink == 1, "unexpected_file"
                )
                found.append(p)
        else:
            require(
                child.name in META and child.is_file() and child.stat().st_nlink == 1,
                "unexpected_file",
            )
    require(not ((root / "work").exists() and (root / "published").exists()), "ambiguous_publish")
    return found


def cleanup(root: Path, fault: str | None = None) -> None:
    with locked(root):
        files = inventory(root)  # Validate entire target inventory before any deletion.
        pending = root / "journal.next"
        if pending.exists():
            pending.unlink()  # Registered metadata intent left by a killed journal writer.
        journal(root, "CLEANING")
        for i, path in enumerate(sorted(files)):
            path.unlink()  # Never recursive deletion or following links.
            if i == 0:
                pause("during_cleanup", fault)
        for name in ("work", "published"):
            if (root / name).exists():
                (root / name).rmdir()
        journal(root, "CLEANED")
        require(not inventory(root), "incomplete_cleanup")


def tool(name: str) -> Path:
    value = shutil.which(name)
    require(value is not None, "missing_installed_" + name)
    assert value is not None
    result = Path(value).resolve(strict=True)
    require(result.is_file(), "tool_not_file")
    return result


def memory_bytes() -> int | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in [
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                ]
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        query = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        query.restype = wintypes.BOOL
        ok = query(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return int(counters.PeakWorkingSetSize) if ok else None
    import resource

    return int(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024)
    )


def command(args: list[str], cwd: Path, lock: BinaryIO, *, binary: bool = False) -> dict[str, Any]:
    start = time.perf_counter()
    inherited = (lock.fileno(),) if sys.platform != "win32" else ()
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        timeout=120,
        shell=False,
        pass_fds=inherited,
        umask=0o077 if sys.platform != "win32" else -1,
    )
    record: dict[str, Any] = dict(
        command=args,
        exit_code=result.returncode,
        elapsed_seconds=time.perf_counter() - start,
        stderr=result.stderr.decode("utf-8", errors="replace"),
    )
    require(result.returncode == 0, "media_command_failed: " + record["stderr"][-1000:])
    record["stdout"] = result.stdout if binary else result.stdout.decode("utf-8")
    return record


def validate_media(work: Path, ffmpeg: Path, ffprobe: Path, lock: BinaryIO) -> dict[str, Any]:
    result = command(
        [
            str(ffprobe),
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-show_frames",
            "-of",
            "json",
            "video.mp4",
        ],
        work,
        lock,
    )
    data = json.loads(result["stdout"])
    streams = data["streams"]
    require(len(streams) == 2, "media_streams")
    video = next(s for s in streams if s["codec_type"] == "video")
    audio = next(s for s in streams if s["codec_type"] == "audio")
    require(
        (video["width"], video["height"], video["r_frame_rate"], video["avg_frame_rate"])
        == (1280, 720, "30/1", "30/1"),
        "media_geometry",
    )
    require(video["codec_name"] == "h264" and video["pix_fmt"] == "yuv420p", "media_video_codec")
    require(
        audio["codec_name"] == "aac" and audio["sample_rate"] == "48000" and audio["channels"] == 1,
        "media_audio_codec",
    )
    frames = [f for f in data["frames"] if f["media_type"] == "video"]
    require(len(frames) == int(video["nb_read_frames"]) == 540, "media_frame_count")
    for i, frame in enumerate(frames):
        require(
            abs(float(frame["best_effort_timestamp_time"]) - i / 30) <= 0.000002,
            "media_frame_timing",
        )
    require(abs(float(data["format"]["duration"]) - 18) < 0.05, "media_duration")
    require(abs(float(audio["duration"]) - 18) < 0.05, "media_audio_duration")
    decode = command(
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
        lock,
    )
    # Decode each scene's first/last frame and compare against the original raster. This
    # proves scene ordering/durations in actual encoded pixels, not just metadata.
    pixels = command(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-i",
            "video.mp4",
            "-vf",
            "select=not(mod(n\\,90))+eq(mod(n\\,90)\\,89)",
            "-vsync",
            "0",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        work,
        lock,
        binary=True,
    )
    size = 1280 * 720 * 3
    require(len(pixels["stdout"]) == 12 * size, "scene_boundary_frames")
    errors = []
    for i in range(6):
        png = (work / f"scene{i:02d}.png").read_bytes()
        position, compressed = 8, bytearray()
        while position < len(png):
            length = struct.unpack(">I", png[position : position + 4])[0]
            if png[position + 4 : position + 8] == b"IDAT":
                compressed += png[position + 8 : position + 8 + length]
            position += length + 12
        raw = zlib.decompress(compressed)
        require(
            len(raw) == 720 * 3841 and all(raw[y * 3841] == 0 for y in range(720)),
            "original_raster_format",
        )
        expected = b"".join(raw[y * 3841 + 1 : (y + 1) * 3841] for y in range(720))
        for n in (2 * i, 2 * i + 1):
            actual = pixels["stdout"][n * size : (n + 1) * size]
            error = sum(abs(a - b) for a, b in zip(expected, actual, strict=True)) / size
            require(error < 4, "encoded_scene_pixel_binding")
            errors.append(error)
    return dict(
        version="fictional-media-validation-1.0",
        synthetic=True,
        original_ffprobe_stdout=result["stdout"],
        original_ffprobe_stdout_sha256=sha(result["stdout"].encode()),
        video=video,
        audio=audio,
        video_frames=540,
        duration_seconds=18,
        scene_start_frames=[0, 90, 180, 270, 360, 450],
        boundary_mean_absolute_rgb_errors=errors,
        decode_exit_code=decode["exit_code"],
        probe_command=result["command"],
        decode_command=decode["command"],
        boundary_decode_command=pixels["command"],
    )


def tone() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        samples = bytearray()
        for i in range(18 * 48000):
            t = i % (3 * 48000)
            amplitude = min(t / 480, (7200 - t) / 480, 1) if t < 7200 else 0
            value = int(900 * max(amplitude, 0) * math.sin(2 * math.pi * 220 * i / 48000))
            samples += struct.pack("<h", value)
        wav.writeframes(samples)
    return buffer.getvalue()


def run(root: Path, fault: str | None = None) -> Path:
    start, cpu = time.perf_counter(), time.process_time()
    sources = original_sources()
    fact_file = FIXTURES / "facts.json"
    ancestry(fact_file)
    require(fact_file.stat().st_nlink == 1 and fact_file.stat().st_size <= 16384, "fact_file")
    grounding = Grounding.model_validate_json(fact_file.read_bytes())
    board = storyboard(grounding, sources)
    # Preflight all scenes before creating output; any overflow rejects the run.
    images = [render(s, grounding, sources) for s in board.scenes]
    ffmpeg, ffprobe = tool("ffmpeg"), tool("ffprobe")
    ancestry(root)
    require(not root.exists(), "output_already_exists")
    root.mkdir(mode=0o700)  # Parent must already exist; never creates arbitrary ancestry.
    exclusive(
        root / "identity.json",
        encoded(
            dict(
                version=VERSION,
                synthetic=True,
                root=str(root),
                run_id=str(uuid.uuid4()),
                created_at=datetime.now(UTC).isoformat(),
                files=sorted(FILES),
                grounding_sha256=board.grounding_sha256,
            )
        ),
    )
    exclusive(root / "lock", b"0")
    with locked(root) as lock:
        journal(root, "WRITING")
        work = root / "work"
        work.mkdir(mode=0o700)
        pause("before_frame", fault)
        for i, image in enumerate(images):
            path = work / f"scene{i:02d}.png"
            if i == 0 and fault == "during_frame":
                exclusive(path, image[: len(image) // 2])
                pause("during_frame", fault)
            exclusive(path, image)
        exclusive(work / "storyboard.json", encoded(board.model_dump()))
        exclusive(work / "audio.wav", tone())
        concat = (
            "ffconcat version 1.0\n"
            + "".join(f"file scene{i:02d}.png\nduration 3\n" for i in range(6))
            + "file scene05.png\n"
        )
        exclusive(work / "scenes.ffconcat", concat.encode())
        journal(root, "ENCODING")
        args = [
            str(ffmpeg),
            "-hide_banner",
            "-nostdin",
            "-v",
            "info",
            "-benchmark",
            "-n",
            "-protocol_whitelist",
            "file",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            "scenes.ffconcat",
            "-protocol_whitelist",
            "file",
            "-i",
            "audio.wav",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            "fps=30,format=yuv420p",
            "-frames:v",
            "540",
            "-t",
            "18",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-threads",
            "2",
            "-filter_threads",
            "1",
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
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-flags:a",
            "+bitexact",
            "-movflags",
            "+faststart",
            "video.mp4",
        ]
        encoding = command(args, work, lock)
        pause("before_validate", fault)
        journal(root, "VALIDATING")
        inventory(root)
        for i, original in enumerate(images):
            require(
                sha((work / f"scene{i:02d}.png").read_bytes()) == sha(original), "raster_changed"
            )
        validation = validate_media(work, ffmpeg, ffprobe, lock)
        exclusive(work / "validation.json", encoded(validation))
        metrics = dict(
            version=VERSION,
            synthetic=True,
            python=sys.version,
            platform=sys.platform,
            wall_seconds=time.perf_counter() - start,
            python_cpu_seconds=time.process_time() - cpu,
            python_peak_memory_bytes=memory_bytes(),
            encoding=encoding,
            ffmpeg_sha256=sha(ffmpeg.read_bytes()),
            ffprobe_sha256=sha(ffprobe.read_bytes()),
            ffmpeg_version=command([str(ffmpeg), "-version"], work, lock)["stdout"],
            source_hashes={n: sha(b) for n, b in sources.items()},
            artifacts={
                p.name: dict(sha256=sha(p.read_bytes()), bytes=p.stat().st_size)
                for p in work.iterdir()
            },
        )
        exclusive(work / "metrics.json", encoded(metrics))
        journal(root, "VALIDATED")
        os.rename(work, root / "published")  # Single same-filesystem bundle publication.
        journal(root, "PUBLISHED")
    return root / "published" / "video.mp4"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=["render", "cleanup"])
    p.add_argument("--output", required=True, type=Path, help="absolute new managed run directory")
    p.add_argument(
        "--pause-at", choices=["before_frame", "during_frame", "before_validate", "during_cleanup"]
    )
    args = p.parse_args()
    try:
        if args.operation == "cleanup":
            cleanup(args.output, args.pause_at)
            print("CLEANED: synthetic bytes removed; identity/journal/lock receipts remain")
        else:
            print(run(args.output, args.pause_at))
    except Exception as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1) from error

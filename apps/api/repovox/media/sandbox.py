"""Contained architecture discovery. Submitted source is parsed only inside this subprocess.

Uses the same Linux controls as the analysis parser (resource limits, no-new-privileges,
Landlock read-only access to the assigned source, seccomp denial of network, exec and fork).
The worker never parses submitted source in its own process.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from repovox.analysis.common import AnalysisError, canonical, digest
from repovox.media.architecture import ArchitectureError, Report, discover

LIMIT = 16 * 1024**2


def sources_from(root: Path, payload: dict[str, Any]) -> dict[str, bytes]:
    """Parsed and context files named by the verified manifest, each checked against its hash."""
    found: dict[str, bytes] = {}
    base = root.resolve()
    for entry in payload["knowledge"]["coverage"]["files"]:
        if entry["status"] not in {"parsed", "context"}:
            continue
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(base) or not path.is_file() or path.is_symlink():
            raise ArchitectureError("source_mismatch")
        body = path.read_bytes()
        if digest(body) != entry["file_sha256"]:
            raise ArchitectureError("source_mismatch")
        found[entry["path"]] = body
    return found


def discover_isolated(
    root: Path, payload: dict[str, Any], checkpoint: Callable[[], None], timeout: float = 150
) -> Report:
    """Run discovery in the contained subprocess and return its (still untrusted) report."""
    if sys.platform != "linux":
        raise ArchitectureError("parser_isolation_unavailable")
    request = root.parent / "architecture-request.json"
    request.write_bytes(canonical({"payload": payload}))
    env = {
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "LANG": "C.UTF-8",
    }
    with tempfile.TemporaryFile(dir=root.parent) as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "repovox.media.sandbox", str(root), str(request)],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                checkpoint()
                if time.monotonic() >= deadline:
                    raise ArchitectureError("architecture_timeout")
                time.sleep(0.05)
            output.seek(0)
            body = output.read(LIMIT + 1)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            request.unlink(missing_ok=True)
    try:
        value = json.loads(body) if len(body) <= LIMIT else {"error": "architecture_too_large"}
    except ValueError:
        raise ArchitectureError("parser_isolation_unavailable") from None
    if process.returncode != 0 or (isinstance(value, dict) and "error" in value):
        code = value.get("error") if isinstance(value, dict) else None
        if not isinstance(code, str) or not code.replace("_", "").isalnum():
            code = "architecture_failure"
        raise ArchitectureError(code)
    try:
        return Report.model_validate(value)
    except ValueError:
        raise ArchitectureError("architecture_failure") from None


def main() -> None:
    from repovox.analysis.sandbox import contain

    root, request_path = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        contain(root, request_path)
        payload = json.loads(request_path.read_bytes())["payload"]
        report = discover(payload, sources_from(root, payload))
        print(report.model_dump_json())
    except (AnalysisError, ArchitectureError) as error:
        print(canonical({"error": error.code}).decode())
        raise SystemExit(2) from None
    except (OSError, ValueError, KeyError, TypeError):
        # No tracebacks, paths or source text leave the hostile-data boundary.
        print('{"error":"architecture_failure"}')
        raise SystemExit(2) from None


if __name__ == "__main__":
    os.environ.pop("PYTHONSTARTUP", None)
    main()

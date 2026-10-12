"""Disposable Linux DAC demonstration, no official source/gold and no infrastructure spend."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

if os.name != "posix" or getattr(os, "geteuid", lambda: -1)() != 0:
    raise SystemExit("Run this disposable probe as root inside the trusted local test image.")

with tempfile.TemporaryDirectory(prefix="repovox-dac-") as temporary:
    root = Path(temporary)
    protected = root / "custodian"
    # Separate Unix identities; this process drops privilege before the custodian checks.
    protected.mkdir(mode=0o700)
    os.chown(protected, 10002, 10002)
    root.chmod(0o755)
    script = (
        "import json,os,sys; from pathlib import Path; "
        "from repovox.evaluation.corpus import CustodianStore; "
        "from repovox.evaluation.preparation import verify_boundary; "
        "os.setgroups([]); os.setgid(10002); os.setuid(10002); "
        "root=Path(sys.argv[1]); store=CustodianStore(root,Path('/workspace')); "
        "key=store.write('synthetic-probe',b'SYNTHETIC DAC PROBE ONLY'); "
        "verify_boundary(root,Path('/workspace'),10001); "
        "print(json.dumps({'key':key,'directory_mode':oct(root.stat().st_mode & 0o777),"
        "'file_mode':oct((root/key).stat().st_mode & 0o777)}))"
    )
    try:
        created = subprocess.run(
            [sys.executable, "-c", script, str(protected)], check=True, capture_output=True
        )
        modes = json.loads(created.stdout)
        artifact = protected / modes["key"]
        worker = (
            "import os,sys; from pathlib import Path; "
            "os.setgroups([]); os.setgid(10001); os.setuid(10001); "
            "Path(sys.argv[1]).read_bytes()"
        )
        denied = subprocess.run([sys.executable, "-c", worker, str(artifact)], capture_output=True)
        if denied.returncode == 0 or b"PermissionError" not in denied.stderr:
            raise SystemExit("Worker read was not demonstrably denied.")
        print(
            json.dumps(
                {
                    "schema_version": "protected-storage-probe-1.0",
                    "synthetic_only": True,
                    "custodian_uid": 10002,
                    "worker_uid": 10001,
                    "worker_read": "OS_DENIED",
                    "directory_mode": modes["directory_mode"],
                    "file_mode": modes["file_mode"],
                    "official_custodian_authorized": False,
                    "official_gold_stored": False,
                }
            )
        )
    finally:
        # Only this explicitly created disposable path; let the parent remove its files.
        os.chown(protected, 0, 0)

#!/usr/local/bin/python
"""Validate an immutable, explicitly UTF-8/LF executable bundle before startup."""

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path("/opt/rv-retention")


def verify():
    expected = json.loads((ROOT / "bundle.json").read_bytes())
    if set(expected) != {"launcher.sh", "watchdog.py", "verify_bundle.py"}:
        raise ValueError("bundle_inventory")
    for name, sha in expected.items():
        path = ROOT / name
        body = path.read_bytes()
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise ValueError("bundle_file_type")
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o555:
            raise ValueError("bundle_permissions")
        if hashlib.sha256(body).hexdigest() != sha:
            raise ValueError("bundle_hash")
        body.decode("utf-8", errors="strict")
        shebang = b"#!/bin/sh\n" if name.endswith(".sh") else b"#!/usr/local/bin/python\n"
        if not body.startswith(shebang) or b"\r" in body or body.startswith(b"\xef\xbb\xbf"):
            raise ValueError("bundle_encoding_or_shebang")
        if name.endswith(".py"):
            compile(body, name, "exec")
    subprocess.run(["/bin/sh", "-n", str(ROOT / "launcher.sh")], check=True)
    if os.geteuid() != 10002 or os.getegid() != 10002:
        raise ValueError("bundle_runtime_identity")


if __name__ == "__main__":
    verify()

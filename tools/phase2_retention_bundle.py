"""Canonical bytes and deterministic transfer; never reinterpret host text encodings."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

NAMES = ("launcher.sh", "verify_bundle.py", "watchdog.py")


def check(body, name, expected_sha256=None):
    if expected_sha256 is not None and hashlib.sha256(body).hexdigest() != expected_sha256:
        raise ValueError("source_hash_mismatch")
    body.decode("utf-8", errors="strict")
    first = b"#!/bin/sh\n" if name == "launcher.sh" else b"#!/usr/local/bin/python\n"
    if not body.startswith(first) or b"\r" in body or not body.endswith(b"\n"):
        raise ValueError("canonical_encoding_or_shebang")
    if name.endswith(".py"):
        compile(body, name, "exec")
    return hashlib.sha256(body).hexdigest()


def create(source, target):
    source, target = Path(source), Path(target)
    bodies = {name: (source / name).read_bytes() for name in NAMES}
    hashes = {name: check(body, name) for name, body in bodies.items()}
    bodies["bundle.json"] = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    bodies["Dockerfile"] = (
        b"""ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER 0:0
COPY --chown=0:0 --chmod=0555 launcher.sh verify_bundle.py watchdog.py /opt/rv-retention/
COPY --chown=0:0 --chmod=0444 bundle.json /opt/rv-retention/bundle.json
USER 10002:10002
"""
        + (
            b"RUN /bin/sh -n /opt/rv-retention/launcher.sh && /usr/local/bin/python -I "
            b"/opt/rv-retention/verify_bundle.py\n"
        )
        + b"""\
ENTRYPOINT ["/opt/rv-retention/launcher.sh"]
CMD []
"""
    )
    with target.open("xb") as stream:
        with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, body in sorted(bodies.items()):
                member = tarfile.TarInfo(name)
                member.size, member.mtime, member.uid, member.gid = len(body), 0, 0, 0
                member.mode = 0o555 if name in NAMES else 0o444
                archive.addfile(member, io.BytesIO(body))
    with tarfile.open(target, "r:") as archive:
        if set(archive.getnames()) != set(bodies):
            raise ValueError("transfer_inventory")
        for member in archive:
            if (
                not member.isfile()
                or member.name not in bodies
                or archive.extractfile(member).read() != bodies[member.name]
            ):
                raise ValueError("transfer_bytes")
    return {
        "files": hashes,
        "transfer_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "representation": (
            "UTF-8 without BOM; LF; shebang at byte offset zero; image scripts root:root mode0555"
        ),
        "target_shell_syntax_checked": False,
        "container_transfer_verified": False,
    }

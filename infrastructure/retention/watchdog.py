#!/usr/local/bin/python
"""Retention ops 1.0: exact inventory, directory-FD containment, durable expiry intent.

No acquisition, database, prediction, gold or scoring interfaces. Host administrators
and the sole custodian remain trusted. Deploying this contract to real custody needs
separate approval; the supplied rehearsal authorizes only synthetic namespaces.
"""

import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = "/custody"
STATUS = Path("/status/heartbeat.json")
SHA = re.compile(r"^[a-f0-9]{64}$")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def require(condition, code):
    if not condition:
        raise ValueError(code)


def utc(value):
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0, "utc_deadline")
    return parsed


def path_parts(name):
    require(isinstance(name, str) and 0 < len(name) <= 1024, "inventory_path")
    require("\\" not in name and ":" not in name and not name.startswith("/"), "inventory_path")
    parts = name.split("/")
    require(all(p not in {"", ".", ".."} for p in parts), "inventory_path")
    require(str(PurePosixPath(name)) == name, "inventory_path")
    return parts


def identity():
    fields = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    caps = {k: fields[k].strip() for k in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"]}
    require(
        os.getuid() == os.geteuid() == 10002 and os.getgid() == os.getegid() == 10002,
        "custodian_identity",
    )
    require(
        set(os.getgroups()) <= {10002} and all(int(v, 16) == 0 for v in caps.values()),
        "custodian_capabilities",
    )
    require(fields["NoNewPrivs"].strip() == "1", "no_new_privileges")
    return {
        "uid": os.geteuid(),
        "gid": os.getegid(),
        "groups": os.getgroups(),
        "capabilities": caps,
        "no_new_privileges": 1,
    }


def checked_dir(parent, name, device=None):
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    info = os.fstat(fd)
    try:
        require(
            info.st_uid == info.st_gid == 10002 and stat.S_IMODE(info.st_mode) == 0o700,
            "directory_permissions",
        )
        require(device is None or info.st_dev == device, "cross_device_boundary")
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_file(parent, name, device, maximum=50_000_000):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "file_type_or_hardlink")
        require(
            info.st_uid == info.st_gid == 10002 and stat.S_IMODE(info.st_mode) == 0o600,
            "file_permissions",
        )
        require(info.st_dev == device and info.st_size <= maximum, "file_boundary_or_limit")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            body = stream.read(maximum + 1)
        require(len(body) == info.st_size and len(body) <= maximum, "file_size_changed")
        return body, (info.st_dev, info.st_ino)
    finally:
        os.close(fd)


def write_once(parent, name, body):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(parent)


def inventory(fd, device, prefix=""):
    found = {}
    directories = set()
    for name in sorted(os.listdir(fd)):
        path = prefix + name
        path_parts(path)
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        require(info.st_dev == device, "inventory_device")
        if stat.S_ISDIR(info.st_mode):
            child = checked_dir(fd, name, device)
            try:
                nested, dirs = inventory(child, device, path + "/")
            finally:
                os.close(child)
            found.update(nested)
            directories |= dirs | {path}
        else:
            body, inode = read_file(fd, name, device)
            found[path] = {"sha256": digest(body), "size": len(body), "inode": inode}
        require(len(found) + len(directories) <= 10000, "inventory_count_limit")
    return found, directories


def remove_one(root, name, expected, device):
    parents = []
    current = root
    parts = path_parts(name)
    try:
        for part in parts[:-1]:
            current = checked_dir(current, part, device)
            parents.append(current)
        body, inode = read_file(current, parts[-1], device)
        require(
            digest(body) == expected["sha256"] and len(body) == expected["size"],
            "deletion_bytes_changed",
        )
        now = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
        require((now.st_dev, now.st_ino) == inode, "deletion_inode_changed")
        os.unlink(parts[-1], dir_fd=current)
        os.fsync(current)
    finally:
        for fd in reversed(parents):
            os.close(fd)


def run():
    os.umask(0o077)
    who = identity()
    raw = Path("/config/plan.json").read_bytes()
    plan_sha = digest(raw)
    require(plan_sha == os.environ.get("RV_RETENTION_PLAN_SHA256"), "plan_commitment")
    plan = json.loads(raw)
    require(
        set(plan)
        == {
            "version",
            "namespace",
            "volume",
            "nonce",
            "created_at",
            "expires_at",
            "interval_seconds",
            "files",
            "usage",
        },
        "plan_fields",
    )
    require(plan["version"] == "retention-ops-1.0", "plan_version")
    require(plan["usage"] == "SYNTHETIC_RETENTION_REHEARSAL", "real_activation_not_authorized")
    require(re.fullmatch(r"synthetic-[a-f0-9]{32}", plan["namespace"]) is not None, "namespace")
    require(re.fullmatch(r"[a-f0-9]{32}", plan["nonce"]) is not None, "nonce")
    created, deadline = utc(plan["created_at"]), utc(plan["expires_at"])
    require(0 < (deadline - created).total_seconds() <= 30 * 86400, "retention_ceiling")
    require(0.1 <= plan["interval_seconds"] <= 60, "interval")
    require(isinstance(plan["files"], dict) and 0 < len(plan["files"]) <= 5000, "inventory_count")
    allowed_dirs = set()
    for name, entry in plan["files"].items():
        parts = path_parts(name)
        allowed_dirs |= {"/".join(parts[:i]) for i in range(1, len(parts))}
        require(
            set(entry) == {"sha256", "size"}
            and SHA.fullmatch(entry["sha256"])
            and isinstance(entry["size"], int)
            and 0 <= entry["size"] <= 50_000_000,
            "inventory_entry",
        )
    require(sum(e["size"] for e in plan["files"].values()) <= 50_000_000, "inventory_total")
    root = checked_dir(None, ROOT)
    device = os.fstat(root).st_dev
    require(set(os.listdir(root)) == {"control", "data"}, "custody_root_inventory")
    control = checked_dir(root, "control", device)
    data = checked_dir(root, "data", device)
    marker, _ = read_file(control, "identity.json", device)
    require(
        json.loads(marker)
        == {
            "namespace": plan["namespace"],
            "volume": plan["volume"],
            "nonce": plan["nonce"],
            "plan_sha256": plan_sha,
        },
        "namespace_marker",
    )
    lock = os.open("lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=control)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    read_file(control, "lock", device)
    boot, seq = uuid.uuid4().hex, 0
    previous_clock = datetime.now(timezone.utc)
    while True:
        now = datetime.now(timezone.utc)
        require((now - previous_clock).total_seconds() >= -2, "wall_clock_regressed")
        previous_clock = now
        require(
            set(os.listdir(control))
            <= {"identity.json", "lock", "expiry-intent.json", "expired.json"},
            "control_inventory",
        )
        intent = "expiry-intent.json" in os.listdir(control)
        receipt = "expired.json" in os.listdir(control)
        if intent:
            saved, _ = read_file(control, "expiry-intent.json", device)
            record = json.loads(saved)
            require(
                record["plan_sha256"] == plan_sha
                and record["namespace"] == plan["namespace"]
                and utc(record["observed_at"]) >= deadline,
                "expiry_intent_binding",
            )
        require(not receipt or intent, "receipt_without_intent")
        actual, directories = inventory(data, device)
        require(directories <= allowed_dirs, "unexpected_directory")
        require(
            set(actual) <= set(plan["files"]) and (intent or set(actual) == set(plan["files"])),
            "inventory_changed",
        )
        for name, entry in actual.items():
            require(
                {k: entry[k] for k in ["sha256", "size"]} == plan["files"][name], "inventory_hash"
            )
        require(not receipt or not actual, "data_after_expiry")
        phase = "MONITORING"
        if now >= deadline or intent:
            if not intent:
                write_once(
                    control,
                    "expiry-intent.json",
                    canonical(
                        {
                            "namespace": plan["namespace"],
                            "plan_sha256": plan_sha,
                            "observed_at": now.isoformat(),
                        }
                    ),
                )
            for name in sorted(actual):
                remove_one(data, name, plan["files"][name], device)
            remaining, _ = inventory(data, device)
            require(not remaining, "expiry_incomplete")
            if not receipt:
                write_once(
                    control,
                    "expired.json",
                    canonical(
                        {
                            "namespace": plan["namespace"],
                            "plan_sha256": plan_sha,
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                            "file_count": len(plan["files"]),
                        }
                    ),
                )
            saved, _ = read_file(control, "expired.json", device)
            record = json.loads(saved)
            require(
                record["namespace"] == plan["namespace"]
                and record["plan_sha256"] == plan_sha
                and utc(record["completed_at"]) >= deadline
                and record["file_count"] == len(plan["files"]),
                "receipt_binding",
            )
            phase = "EXPIRED"
        seq += 1
        heartbeat = {
            "version": "retention-heartbeat-1.0",
            "namespace": plan["namespace"],
            "plan_sha256": plan_sha,
            "boot": boot,
            "sequence": seq,
            "pid": os.getpid(),
            "phase": phase,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "monotonic_ns": time.monotonic_ns(),
            "deadline": deadline.isoformat(),
            "script_sha256": digest(Path(__file__).read_bytes()),
            "identity": who,
            "inventory_checked": True,
        }
        tmp = STATUS.with_suffix(".tmp")
        with tmp.open("wb") as stream:
            stream.write(canonical(heartbeat))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, STATUS)
        print(canonical(heartbeat).decode(), flush=True)
        time.sleep(plan["interval_seconds"])


if __name__ == "__main__":
    try:
        run()
    except BaseException as exc:
        print(
            json.dumps(
                {
                    "version": "retention-error-1.0",
                    "error": type(exc).__name__,
                    "detail": str(exc),
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            file=sys.stderr,
            flush=True,
        )
        raise

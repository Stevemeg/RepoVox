"""Trusted parser subprocess. Linux controls are mandatory for real job analysis."""

import ctypes
import errno
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from repovox.analysis.common import AnalysisError, canonical
from repovox.analysis.documentation import context_symbols
from repovox.analysis.filtering import filter_sources
from repovox.analysis.graph import configuration, entrypoints, infer
from repovox.analysis.grounding import catalog, knowledge, verify
from repovox.analysis.parser import structure


def contain(root: Path, request: Path) -> None:
    if sys.platform != "linux" or os.getuid() == 0:
        raise AnalysisError("parser_isolation_unavailable")
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (100, 100))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise AnalysisError("parser_isolation_unavailable")
    if os.uname().machine not in {"x86_64", "aarch64"}:
        raise AnalysisError("parser_isolation_unavailable")

    # Landlock denies filesystem access except assigned source and trusted runtime.
    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int)]

    handled = (1 << 13) - 1
    attr = Ruleset(handled)
    fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise AnalysisError("parser_isolation_unavailable")
    try:
        paths = [
            root,
            request,
            Path(sys.prefix),
            Path(__file__).resolve().parents[2],
            Path("/usr/local/lib"),
            Path("/usr/lib"),
            Path("/lib"),
            Path("/etc/ld.so.cache"),
        ]
        for path in paths:
            if not path.exists():
                continue
            parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                allowed = (1 << 2) | ((1 << 3) if path.is_dir() else 0)  # READ_FILE, READ_DIR
                rule = PathRule(allowed, parent)
                if libc.syscall(445, fd, 1, ctypes.byref(rule), 0) != 0:
                    raise AnalysisError("parser_isolation_unavailable")
            finally:
                os.close(parent)
        if libc.syscall(446, fd, 0) != 0:
            raise AnalysisError("parser_isolation_unavailable")
    finally:
        os.close(fd)
    seccomp = ctypes.CDLL("libseccomp.so.2")
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    context = seccomp.seccomp_init(0x7FFF0000)  # ALLOW except explicit denied operations
    if not context:
        raise AnalysisError("parser_isolation_unavailable")
    try:
        for name in [
            "socket",
            "socketpair",
            "connect",
            "execve",
            "execveat",
            "fork",
            "vfork",
            "clone",
            "clone3",
            "ptrace",
            "process_vm_readv",
            "process_vm_writev",
            "mount",
            "umount2",
            "unshare",
            "setns",
            "bpf",
            "keyctl",
            "io_uring_setup",
            "open_by_handle_at",
            "name_to_handle_at",
        ]:
            number = seccomp.seccomp_syscall_resolve_name(name.encode())
            if (
                number >= 0
                and seccomp.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0) != 0
            ):
                raise AnalysisError("parser_isolation_unavailable")
        if seccomp.seccomp_load(context) != 0:
            raise AnalysisError("parser_isolation_unavailable")
    finally:
        seccomp.seccomp_release(context)


def execute(stage: int, root: Path, request: dict[str, Any]) -> dict[str, Any]:
    snapshot = request["snapshot"]
    inputs = request["inputs"]
    if stage == 3:
        return filter_sources(
            root, snapshot["repository"], snapshot["commit_sha"], request["archive_hash"]
        )
    if stage == 4:
        manifest = inputs["3"]
        structural = structure(root, manifest)
        structural["symbols"].extend(context_symbols(root, manifest))
        if len(structural["symbols"]) > 10_000:
            raise AnalysisError("analysis_fact_limit")
        structural["symbols"].sort(key=lambda s: s["id"])
        return {
            "manifest": manifest,
            "structure": structural,
            "configuration": configuration(root, manifest),
        }
    if stage == 5:
        parsed = inputs["4"]
        return entrypoints(parsed["structure"], parsed["configuration"], parsed["manifest"])
    if stage == 6:
        return infer(inputs["4"]["structure"], inputs["5"])
    if stage == 7:
        parsed = inputs["4"]
        return knowledge(
            snapshot, parsed["manifest"], parsed["structure"], inputs["6"], parsed["configuration"]
        )
    if stage == 8:
        pkm = inputs["7"]
        evidence = catalog(root, snapshot, request["snapshot_id"], pkm)
        return {"knowledge": pkm, "evidence": evidence}
    if stage == 9:
        bundle = inputs["8"]
        ledger = verify(
            root,
            snapshot,
            request["snapshot_id"],
            inputs["4"]["manifest"],
            bundle["knowledge"],
            bundle["evidence"],
        )
        return {**bundle, "verification": ledger}
    raise AnalysisError("phase2_pipeline_boundary")


def main() -> None:
    root, request_path = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        contain(root, request_path)
        request = json.loads(request_path.read_bytes())
        if request["stage"] == 0:
            # Runtime isolation probe; trusted checks, never submitted code.
            import socket

            results = {}
            results["credentials_absent"] = not any(
                key.startswith("REPOVOX_") for key in os.environ
            )
            probes: dict[str, Callable[[], object]] = {
                "network_denied": lambda: socket.socket(),
                "unassigned_file_denied": lambda: Path("/etc/passwd").read_bytes(),
                "scratch_write_denied": lambda: (root / "tripwire").write_text("fail"),
            }
            for name, operation in probes.items():
                try:
                    operation()
                    results[name] = False
                except PermissionError:
                    results[name] = True
            print(canonical(results).decode())
            return
        print(canonical(execute(request["stage"], root, request)).decode())
    except AnalysisError as exc:
        print(canonical({"error": exc.code}).decode())
        raise SystemExit(2) from None
    except (OSError, ValueError, KeyError, TypeError):
        # No tracebacks/paths/input strings leave the hostile-data boundary.
        print('{"error":"parser_isolation_or_analysis_failed"}')
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()

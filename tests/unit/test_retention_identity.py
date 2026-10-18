"""Host-only negative controls. These cannot substitute for Linux execution proof."""

import copy
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools.phase2_retention_bundle import NAMES, check, create
from tools.phase2_retention_identity import (
    PREFIX,
    canonical,
    explicit_labels,
    host_path,
    readiness,
    sha,
    unavailable,
    validate_container,
    validate_inventory,
)

PACKAGE = Path(__file__).resolve().parents[2] / "infrastructure" / "retention"


@pytest.fixture
def setup():
    plan = {
        "namespace": "synthetic-" + "a" * 32,
        "nonce": "b" * 32,
        "role": "retention",
        "purpose": "synthetic-retention",
        "name": "synthetic-retention-host-fixture",
        "kind": "standalone",
        "image_id": "sha256:" + "c" * 64,
        "command": [],
        "entrypoint": ["/opt/rv-retention/launcher.sh"],
        "user": "10002:10002",
        "environment": ["RV_RETENTION_PLAN_SHA256=" + "d" * 64],
        "mounts": [
            {
                "type": "volume",
                "source": "synthetic-custody-fixture",
                "target": "/custody",
                "rw": True,
            }
        ],
        "security": {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "SecurityOpt": ["no-new-privileges:true"],
        },
        "networks": ["none"],
        "tmpfs": {"/status": "rw,nosuid,nodev,noexec,size=1048576,mode=0700,uid=10002,gid=10002"},
        "retention_plan_sha256": "d" * 64,
        "script_sha256": "e" * 64,
        "deadline": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    }
    image = {
        "Id": plan["image_id"],
        "Config": {
            "Labels": {
                "com.docker.compose.project": "unrelated-inherited",
                "com.docker.compose.service": "tests",
                "com.docker.compose.version": "5.1.4",
            }
        },
    }
    labels = dict(image["Config"]["Labels"], **explicit_labels(plan))
    volume = {
        "Name": "synthetic-custody-fixture",
        "Driver": "local",
        "CreatedAt": "2026-10-18T00:00:00Z",
        "Mountpoint": "/synthetic-only-volume",
        "Options": None,
        "Labels": {
            PREFIX + "namespace": plan["namespace"],
            PREFIX + "nonce": plan["nonce"],
            PREFIX + "purpose": "synthetic-custody",
        },
    }
    volumes = {volume["Name"]: volume}
    receipt = {
        "plan_sha256": sha(canonical(plan)),
        "container_id": "f" * 64,
        "created_at": "2026-10-18T00:00:01Z",
        "explicit_labels": explicit_labels(plan),
        "volumes": copy.deepcopy(volumes),
    }
    container = {
        "Id": receipt["container_id"],
        "Name": "/" + plan["name"],
        "Created": receipt["created_at"],
        "Image": image["Id"],
        "Config": {
            "Labels": labels,
            "Cmd": plan["command"],
            "Entrypoint": plan["entrypoint"],
            "User": plan["user"],
            "Env": plan["environment"],
        },
        "Mounts": [
            {"Type": "volume", "Name": volume["Name"], "Destination": "/custody", "RW": True}
        ],
        "HostConfig": dict(
            plan["security"], Tmpfs=plan["tmpfs"], Mounts=[{"Type": "volume", "VolumeOptions": {}}]
        ),
        "NetworkSettings": {"Networks": {"none": {}}},
        "State": {
            "Running": True,
            "Restarting": False,
            "Paused": False,
            "OOMKilled": False,
            "Pid": 1234,
        },
    }
    return plan, receipt, container, image, volumes


def test_explicit_identity_overrides_no_inherited_classification(setup):
    assert validate_container(*setup) == "retention"


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("missing_label", "runtime_identity_labels"),
        ("wrong_image", "container_image"),
        ("wrong_mount", "mount_identity"),
        ("wrong_volume", "volume_identity"),
        ("new_id", "container_identity"),
        ("subpath", "unexpected_volume_subpath"),
        ("ambiguous", "conflicting_compose_identity"),
        ("caps", "runtime_security_CapAdd"),
        ("env", "runtime_environment"),
        ("cmd", "invoked_command"),
        ("image_nonce", "runtime_labels_in_image"),
    ],
)
def test_identity_rejections(setup, fault, reason):
    p, r, c, i, v = setup
    if fault == "missing_label":
        del c["Config"]["Labels"][PREFIX + "nonce"]
    if fault == "wrong_image":
        c["Image"] = "unexpected"
    if fault == "wrong_mount":
        c["Mounts"][0]["Name"] = "unapproved-real-volume"
    if fault == "wrong_volume":
        v[next(iter(v))]["CreatedAt"] = "replacement"
    if fault == "new_id":
        c["Id"] = "unregistered"
    if fault == "subpath":
        c["HostConfig"]["Mounts"][0]["VolumeOptions"]["Subpath"] = "other"
    if fault == "ambiguous":
        c["Config"]["Labels"]["com.docker.compose.project.working_dir"] = "/other"
    if fault == "caps":
        c["HostConfig"]["CapAdd"] = ["DAC_OVERRIDE"]
    if fault == "env":
        c["Config"]["Env"] = ["RV_RETENTION_PLAN_SHA256=wrong"]
    if fault == "cmd":
        c["Config"]["Cmd"] = ["sh"]
    if fault == "image_nonce":
        i["Config"]["Labels"][PREFIX + "nonce"] = p["nonce"]
    with pytest.raises(ValueError, match=reason):
        validate_container(*setup)


def test_unknown_namespace_claim_and_duplicate_receipt(setup):
    p, r, c, _, _ = setup
    validate_inventory([p], [r], [c])
    c["Id"] = "unknown"
    with pytest.raises(ValueError, match="unregistered_namespace"):
        validate_inventory([p], [r], [c])
    with pytest.raises(ValueError, match="duplicate_provisioning"):
        validate_inventory([p, p], [r, r], [])


@pytest.mark.parametrize("role", ["application", "worker", "database"])
def test_compose_working_directory_remains_mandatory(setup, role):
    p, r, c, _, _ = setup
    p.update(
        kind="compose",
        role=role,
        purpose="synthetic-service",
        compose_project="synthetic-test",
        compose_service=role,
        working_directory="C:/Synthetic/Test",
        mounts=[],
    )
    r.update(plan_sha256=sha(canonical(p)), explicit_labels=explicit_labels(p))
    c["Config"]["Labels"] = explicit_labels(p) | {
        "com.docker.compose.project": p["compose_project"],
        "com.docker.compose.service": role,
        "com.docker.compose.project.working_dir": "c:\\synthetic\\test",
    }
    c["Mounts"] = []
    assert validate_container(*setup) == role
    del c["Config"]["Labels"]["com.docker.compose.project.working_dir"]
    with pytest.raises(ValueError, match="compose_working_directory"):
        validate_container(*setup)


def test_linux_paths_do_not_casefold():
    assert host_path("/Sensitive") != host_path("/sensitive")


def test_volume_cannot_alias_a_host_directory_even_with_matching_receipt(setup):
    _, receipt, _, _, volumes = setup
    volume = volumes[next(iter(volumes))]
    volume["Options"] = {"type": "none", "o": "bind", "device": "/unapproved-host-directory"}
    receipt["volumes"] = copy.deepcopy(volumes)
    with pytest.raises(ValueError, match="volume_driver_or_options"):
        validate_container(*setup)


def heartbeats(plan):
    now = datetime.now(UTC)
    who = {
        "uid": 10002,
        "gid": 10002,
        "groups": [10002],
        "capabilities": {"CapEff": "0", "CapBnd": "0"},
        "no_new_privileges": 1,
    }
    first = {
        "version": "retention-heartbeat-1.0",
        "namespace": plan["namespace"],
        "plan_sha256": plan["retention_plan_sha256"],
        "script_sha256": plan["script_sha256"],
        "pid": 1,
        "inventory_checked": True,
        "phase": "MONITORING",
        "identity": who,
        "checked_at": now.isoformat(),
        "deadline": plan["deadline"],
        "boot": "one-boot",
        "sequence": 2,
        "monotonic_ns": 100,
    }
    second = dict(first, sequence=3, monotonic_ns=200)
    process = {
        "cmdline": ["/usr/local/bin/python", "-I", "/opt/rv-retention/watchdog.py"],
        "uid": [10002] * 4,
        "gid": [10002] * 4,
        "state": "S",
        "caps": {"CapEff": "0", "CapBnd": "0"},
        "no_new_privs": 1,
    }
    return first, second, process


def test_two_completed_check_iterations_required(setup):
    assert readiness(*setup, *heartbeats(setup[0]))["ready"]


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("running_only", "watchdog_unavailable"),
        ("restart", "watchdog_unavailable"),
        ("no_progress", "watchdog_no_progress"),
        ("stale", "heartbeat_stale"),
        ("expired", "retention_expired"),
        ("cross_namespace", "heartbeat_binding"),
        ("different_boot", "watchdog_no_progress"),
        ("wrong_process", "unexpected_process"),
        ("stopped_process", "process_identity"),
        ("capability", "process_capabilities"),
    ],
)
def test_running_state_cannot_establish_readiness(setup, fault, reason):
    a, b, process = heartbeats(setup[0])
    if fault == "running_only":
        setup[2]["State"]["Pid"] = 0
    if fault == "restart":
        setup[2]["State"]["Restarting"] = True
    if fault == "no_progress":
        b["sequence"] = a["sequence"]
    if fault == "stale":
        a["checked_at"] = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    if fault == "expired":
        b["phase"] = "EXPIRED"
    if fault == "cross_namespace":
        b["namespace"] = "other"
    if fault == "different_boot":
        b["boot"] = "restarted"
    if fault == "wrong_process":
        process["cmdline"] = ["sleep", "100"]
    if fault == "stopped_process":
        process["state"] = "T"
    if fault == "capability":
        process["caps"]["CapEff"] = "1"
    with pytest.raises(ValueError, match=reason):
        readiness(*setup, a, b, process)


def test_fallback_cannot_award_readiness_or_extend_deadline(setup):
    result = unavailable(setup[0], "heartbeat_missing")
    assert result["ready"] is False and result["deadline"] == setup[0]["deadline"]
    assert (
        result["extend_deadline"] is False
        and result["automatic_delete_authorized_by_this_record"] is False
    )


@pytest.mark.parametrize(
    "fault", ["bom", "mojibake_bom", "crlf", "no_shebang", "wrong_shebang", "non_utf8"]
)
def test_bad_executable_bytes_rejected(fault):
    body = (PACKAGE / "launcher.sh").read_bytes()
    if fault == "bom":
        body = b"\xef\xbb\xbf" + body
    if fault == "mojibake_bom":
        body = b"\xc3\xaf\xc2\xbb\xc2\xbf" + body
    if fault == "crlf":
        body = body.replace(b"\n", b"\r\n")
    if fault == "no_shebang":
        body = body.split(b"\n", 1)[1]
    if fault == "wrong_shebang":
        body = body.replace(b"#!/bin/sh", b"#!/not/a/shell")
    if fault == "non_utf8":
        body += b"\xff"
    with pytest.raises((ValueError, UnicodeDecodeError)):
        check(body, "launcher.sh")


def test_syntax_and_hash_mismatch_rejected():
    with pytest.raises(SyntaxError):
        check(b"#!/usr/local/bin/python\nif (\n", "watchdog.py")
    with pytest.raises(ValueError, match="source_hash"):
        check((PACKAGE / "watchdog.py").read_bytes() + b"#changed\n", "watchdog.py", "0" * 64)


def test_byte_preserving_transfer_and_permissions(tmp_path):
    a, b = tmp_path / "a.tar", tmp_path / "b.tar"
    first, second = create(PACKAGE, a), create(PACKAGE, b)
    assert a.read_bytes() == b.read_bytes() and first == second
    with tarfile.open(a) as archive:
        for name in NAMES:
            member = archive.getmember(name)
            assert member.mode == 0o555 and member.uid == member.gid == 0
            assert archive.extractfile(member).read() == (PACKAGE / name).read_bytes()
    assert (
        first["target_shell_syntax_checked"] is False
        and first["container_transfer_verified"] is False
    )

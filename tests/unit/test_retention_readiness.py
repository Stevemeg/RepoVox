"""Deterministic state-machine controls; real Linux proof lives in operational tests."""

import copy
from datetime import UTC, datetime, timedelta

import pytest
from test_retention_identity import setup as setup

from tools.phase2_retention_identity import canonical, explicit_labels, sha
from tools.phase2_retention_readiness import STARTUP_SECONDS, WATCHDOG, wait_ready


class Clock:
    def __init__(self):
        self.elapsed = 0.0
        self.epoch = datetime.now(UTC)

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds

    def utc(self):
        return self.epoch + timedelta(seconds=self.elapsed)


def source(fixture, clock, *, delay=0, mode="healthy"):
    plan, receipt, container, image, volumes = copy.deepcopy(fixture)
    container["RestartCount"] = 0
    cap = {k: "0000000000000000" for k in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"]}
    who = {
        "uid": 10002,
        "gid": 10002,
        "groups": [10002],
        "no_new_privileges": 1,
        "capabilities": cap,
    }
    seen = []

    def observe(remaining):
        assert 0 < remaining <= STARTUP_SECONDS
        seq = int((clock.elapsed - delay) / 0.2) + 1
        stamp = clock.utc()
        if mode == "repeated":
            seq, stamp = 1, clock.epoch + timedelta(seconds=delay)
        heartbeat = (
            None
            if clock.elapsed < delay
            else {
                "version": "retention-heartbeat-1.0",
                "namespace": plan["namespace"],
                "plan_sha256": plan["retention_plan_sha256"],
                "script_sha256": plan["script_sha256"],
                "pid": 1,
                "inventory_checked": True,
                "phase": "MONITORING",
                "identity": who,
                "checked_at": stamp.isoformat(),
                "deadline": plan["deadline"],
                "boot": "synthetic-boot",
                "sequence": seq,
                "monotonic_ns": int((stamp - clock.epoch).total_seconds() * 1e9),
            }
        )
        process = {
            "cmdline": WATCHDOG,
            "uid": [10002] * 4,
            "gid": [10002] * 4,
            "groups": [10002],
            "caps": cap,
            "no_new_privs": 1,
            "state": "R",
            "start_monotonic_ns": 0,
        }
        observed = {
            "container": copy.deepcopy(container),
            "image": image,
            "volumes": volumes,
            "heartbeat": heartbeat,
            "process": process,
            "script_sha256": plan["script_sha256"],
            "script_owner": [0, 0, 0o555],
            "monotonic_ns": int(clock.elapsed * 1e9),
        }
        if mode == "exit":
            observed["container"]["State"]["Running"] = False
        elif mode == "uid":
            process["uid"] = [10001] * 4
        elif mode == "stopped":
            process["state"] = "T"
        elif mode == "script":
            observed["script_sha256"] = "f" * 64
        elif mode == "capability":
            process["caps"] = dict(cap, CapEff="1")
        elif mode == "forged" and heartbeat:
            heartbeat["namespace"] = "other"
        elif mode == "late_observer":
            clock.sleep(STARTUP_SECONDS + 1)
        elif mode == "deadline" and heartbeat:
            heartbeat["deadline"] = (clock.utc() + timedelta(days=1)).isoformat()
        seen.append(observed)
        return observed

    return plan, receipt, observe, seen


@pytest.mark.parametrize("delay", [0, 0.6, 2.8, 4.4])
def test_bounded_startup_requires_two_completed_loops(setup, delay):
    clock = Clock()
    plan, receipt, observe, seen = source(setup, clock, delay=delay)
    deadline = plan["deadline"]
    result = wait_ready(
        plan, receipt, observe, monotonic=clock.monotonic, sleep=clock.sleep, utc=clock.utc
    )
    assert result["ready"] and result["progress"][0] < result["progress"][1]
    assert delay <= clock.elapsed <= STARTUP_SECONDS
    assert len(seen) >= 2 and plan["deadline"] == deadline


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("exit", "watchdog_unavailable"),
        ("uid", "process_identity"),
        ("stopped", "process_identity_or_stall"),
        ("script", "script_hash"),
        ("capability", "process_capabilities"),
        ("forged", "heartbeat_binding"),
        ("repeated", "heartbeat_stale"),
        ("late_observer", "startup_timeout"),
        ("deadline", "heartbeat_deadline"),
    ],
)
def test_invalid_or_nonprogressing_observation_never_becomes_ready(setup, mode, reason):
    clock = Clock()
    plan, receipt, observe, _ = source(setup, clock, mode=mode)
    with pytest.raises(ValueError, match=reason):
        wait_ready(
            plan, receipt, observe, monotonic=clock.monotonic, sleep=clock.sleep, utc=clock.utc
        )


def test_first_heartbeat_after_startup_budget_is_rejected(setup):
    clock = Clock()
    plan, receipt, observe, seen = source(setup, clock, delay=6.1)
    with pytest.raises(ValueError, match="startup_timeout"):
        wait_ready(
            plan, receipt, observe, monotonic=clock.monotonic, sleep=clock.sleep, utc=clock.utc
        )
    assert clock.elapsed == STARTUP_SECONDS
    assert all(row["heartbeat"] is None for row in seen)


def test_absent_docker_cmd_is_unset_but_not_explicit_command(setup):
    from tools.phase2_retention_identity import validate_container

    plan, receipt, container, image, volumes = copy.deepcopy(setup)
    plan["command"] = None
    container["Config"].pop("Cmd")
    labels = explicit_labels(plan)
    receipt.update(plan_sha256=sha(canonical(plan)), explicit_labels=labels)
    container["Config"]["Labels"].update(labels)
    assert validate_container(plan, receipt, container, image, volumes) == "retention"
    for value in [[], ["unexpected"], "invalid", {}]:
        container["Config"]["Cmd"] = value
        with pytest.raises(ValueError, match="invoked_command"):
            validate_container(plan, receipt, container, image, volumes)

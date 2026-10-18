"""Operational identity 1.0; caller supplies independently retained provisioning receipts.

Docker labels are corroboration, never discovery authority. No Docker mutation occurs.
The host/Docker administrator and receipt custody are trusted boundaries.
"""

import hashlib
import json
import re
from datetime import UTC, datetime

PREFIX = "io.repovox.retention."


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def explicit_labels(plan):
    return {PREFIX + key: str(plan[key]) for key in ["namespace", "nonce", "role", "purpose"]} | {
        PREFIX + "plan": sha(canonical(plan))
    }


def mount_identity(mount):
    kind = mount["Type"]
    require(kind in {"bind", "volume"}, "unexpected_mount_type")
    return {
        "type": kind,
        "source": mount["Name"] if kind == "volume" else host_path(mount["Source"]),
        "target": mount["Destination"],
        "rw": mount["RW"],
    }


def host_path(value):
    # Windows drive paths are case-insensitive; Linux bind paths are not.
    return value.replace("\\", "/").casefold() if re.match(r"^[A-Za-z]:[\\/]", value) else value


def validate_container(plan, receipt, container, image, volumes):
    require(receipt["plan_sha256"] == sha(canonical(plan)), "provisioning_plan_changed")
    require(
        container["Id"] == receipt["container_id"] and container["Name"] == "/" + plan["name"],
        "container_identity",
    )
    require(container["Created"] == receipt["created_at"], "container_creation_changed")
    require(container["Image"] == plan["image_id"] == image["Id"], "container_image")
    require(
        not any(k.startswith(PREFIX) for k in (image["Config"].get("Labels") or {})),
        "runtime_labels_in_image",
    )
    labels = container["Config"].get("Labels") or {}
    require(
        {k: v for k, v in labels.items() if k.startswith(PREFIX)} == explicit_labels(plan),
        "runtime_identity_labels",
    )
    require(receipt["explicit_labels"] == explicit_labels(plan), "provisioning_label_receipt")
    require(
        container["Config"].get("Cmd") == plan["command"]
        and container["Config"]["Entrypoint"] == plan["entrypoint"],
        "invoked_command",
    )
    require(container["Config"]["User"] == plan["user"], "configured_user")
    require(
        sorted(container["Config"]["Env"]) == sorted(plan["environment"]), "runtime_environment"
    )
    require(
        sorted((mount_identity(m) for m in container["Mounts"]), key=lambda m: m["target"])
        == sorted(plan["mounts"], key=lambda m: m["target"]),
        "mount_identity",
    )
    host = container["HostConfig"]
    for mount in host.get("Mounts") or []:
        if mount["Type"] == "volume":
            require(
                not (mount.get("VolumeOptions") or {}).get("Subpath"), "unexpected_volume_subpath"
            )
    for key, value in plan["security"].items():
        require(host[key] == value, "runtime_security_" + key)
    require(
        set(container["NetworkSettings"]["Networks"]) == set(plan["networks"]), "network_identity"
    )
    require(host["Tmpfs"] == plan["tmpfs"], "tmpfs_identity")
    for mount in plan["mounts"]:
        if mount["type"] == "volume":
            vol = volumes[mount["source"]]
            require(vol["Driver"] == "local" and not vol.get("Options"), "volume_driver_or_options")
            expected = receipt["volumes"][mount["source"]]
            require(
                {
                    k: vol.get(k)
                    for k in ["Name", "Driver", "CreatedAt", "Mountpoint", "Labels", "Options"]
                }
                == expected,
                "volume_identity",
            )
            require(
                vol["Labels"].get(PREFIX + "namespace") == plan["namespace"]
                and vol["Labels"].get(PREFIX + "nonce") == plan["nonce"],
                "volume_namespace",
            )
            require(vol["Labels"].get(PREFIX + "purpose") == "synthetic-custody", "volume_purpose")
    if plan["kind"] == "compose":
        require(plan["role"] in {"application", "worker", "database"}, "compose_role")
        require(
            labels.get("com.docker.compose.project") == plan["compose_project"], "compose_project"
        )
        require(
            labels.get("com.docker.compose.service") == plan["compose_service"], "compose_service"
        )
        require(
            host_path(labels.get("com.docker.compose.project.working_dir", ""))
            == host_path(plan["working_directory"]),
            "compose_working_directory",
        )
        require(
            not any(m["target"] == "/custody" for m in plan["mounts"]), "ordinary_custody_mount"
        )
    elif plan["kind"] == "standalone":
        require(plan["role"] == "retention", "standalone_role")
        require(plan["purpose"] == "synthetic-retention", "retention_purpose")
        require(
            plan["user"] == "10002:10002" and plan["networks"] == ["none"], "retention_isolation"
        )
        require(
            host["ReadonlyRootfs"]
            and not host["Privileged"]
            and host["CapDrop"] == ["ALL"]
            and not host["CapAdd"],
            "retention_capabilities",
        )
        require(host["SecurityOpt"] == ["no-new-privileges:true"], "retention_privilege_escalation")
        require(
            len(
                [
                    m
                    for m in plan["mounts"]
                    if m["target"] == "/custody" and m["type"] == "volume" and m["rw"]
                ]
            )
            == 1,
            "custody_mount_required",
        )
        require(
            "com.docker.compose.project.working_dir" not in labels, "conflicting_compose_identity"
        )
        # Familiar image-inherited Compose labels remain inert; they cannot select this role.
    else:
        raise ValueError("unrecognized_container_kind")
    return plan["role"]


def validate_inventory(plans, receipts, observed):
    """Any unregistered container claiming a controlled namespace blocks admission."""
    namespaces = {p["namespace"] for p in plans}
    registered = {r["container_id"] for r in receipts}
    require(len(registered) == len(receipts) == len(plans), "duplicate_provisioning_identity")
    for c in observed:
        if (c["Config"].get("Labels") or {}).get(PREFIX + "namespace") in namespaces:
            require(c["Id"] in registered, "unregistered_namespace_container")


def validate_heartbeat(plan, h, now):
    require(
        h["version"] == "retention-heartbeat-1.0"
        and h["namespace"] == plan["namespace"]
        and h["plan_sha256"] == plan["retention_plan_sha256"],
        "heartbeat_binding",
    )
    require(
        h["script_sha256"] == plan["script_sha256"]
        and h["pid"] == 1
        and h["inventory_checked"] is True,
        "heartbeat_execution",
    )
    require(h["phase"] == "MONITORING", "retention_expired_or_unavailable")
    identity = h["identity"]
    require(
        identity["uid"] == identity["gid"] == 10002
        and set(identity["groups"]) <= {10002}
        and identity["no_new_privileges"] == 1
        and all(int(v, 16) == 0 for v in identity["capabilities"].values()),
        "heartbeat_identity",
    )
    stamp = datetime.fromisoformat(h["checked_at"])
    require(
        stamp.utcoffset().total_seconds() == 0 and -1 <= (now - stamp).total_seconds() <= 3,
        "heartbeat_stale",
    )
    require(
        datetime.fromisoformat(h["deadline"]) > now and h["deadline"] == plan["deadline"],
        "heartbeat_deadline",
    )


def readiness(plan, receipt, container, image, volumes, first, second, process, now=None):
    validate_container(plan, receipt, container, image, volumes)
    state = container["State"]
    require(
        state["Running"]
        and not state["Restarting"]
        and not state["Paused"]
        and not state["OOMKilled"]
        and state["Pid"] > 0,
        "watchdog_unavailable",
    )
    now = now or datetime.now(UTC)
    for h in [first, second]:
        validate_heartbeat(plan, h, now)
    require(
        first["boot"] == second["boot"]
        and first["sequence"] < second["sequence"]
        and first["monotonic_ns"] < second["monotonic_ns"],
        "watchdog_no_progress",
    )
    require(
        process["cmdline"] == ["/usr/local/bin/python", "-I", "/opt/rv-retention/watchdog.py"],
        "unexpected_process",
    )
    require(
        process["uid"] == [10002] * 4
        and process["gid"] == [10002] * 4
        and process["state"] not in {"T", "t", "Z", "X"},
        "process_identity_or_stall",
    )
    require(
        all(int(v, 16) == 0 for v in process["caps"].values()) and process["no_new_privs"] == 1,
        "process_capabilities",
    )
    return {
        "ready": True,
        "namespace": plan["namespace"],
        "progress": [first["sequence"], second["sequence"]],
        "boot": second["boot"],
    }


def unavailable(plan, reason):
    """A fallback record is an escalation obligation, never a substitute ready result."""
    return {
        "ready": False,
        "action": "STOP_EXECUTION_OWNER_MANAGED_RETENTION_REQUIRED",
        "reason": reason,
        "namespace": plan["namespace"],
        "volume": next(m["source"] for m in plan["mounts"] if m["target"] == "/custody"),
        "deadline": plan["deadline"],
        "extend_deadline": False,
        "automatic_delete_authorized_by_this_record": False,
    }

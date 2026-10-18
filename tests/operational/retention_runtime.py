"""Actual isolated Linux/Docker synthetic retention proof. Stop at first unexpected result."""

import base64
import copy
import hashlib
import json
import os
import stat
import subprocess
import tarfile
import time
import traceback
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.phase2_retention_identity import (
    canonical,
    explicit_labels,
    readiness,
    unavailable,
    validate_container,
)
from tools.phase2_retention_observer import COLLECT, process_snapshot
from tools.phase2_retention_readiness import wait_ready

ROOT = Path(os.environ["RV_RETENTION_TEST_ROOT"])
EVIDENCE = ROOT / "runtime-evidence"
EXPECTED_DAEMON = os.environ["RV_TEST_DAEMON_ID"]
PREFIX = "io.repovox.retention."
RESULTS = []
COMMAND = 0
FIXTURES = []


def sha(body):
    return hashlib.sha256(body).hexdigest()


def now():
    return datetime.now(UTC)


def save(path, obj):
    with path.open("x", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def docker(*args, expected=0, input=None, timeout=45):
    global COMMAND
    COMMAND += 1
    command = ["docker", "--host", "unix:///var/run/docker.sock", *map(str, args)]
    start = now().isoformat()
    p = subprocess.run(command, input=input, capture_output=True, timeout=timeout)
    stem = EVIDENCE / f"command-{COMMAND:04d}"
    stem.with_suffix(".stdout").write_bytes(p.stdout)
    stem.with_suffix(".stderr").write_bytes(p.stderr)
    save(
        stem.with_suffix(".json"),
        dict(
            command=command,
            started=start,
            ended=now().isoformat(),
            exit_code=p.returncode,
            stdout_sha256=sha(p.stdout),
            stderr_sha256=sha(p.stderr),
        ),
    )
    if expected is not None:
        assert p.returncode == expected, (command, p.returncode, p.stderr.decode(errors="replace"))
    return p


def inspect(cid):
    return json.loads(docker("inspect", cid).stdout)[0]


def rejection(function, reason):
    try:
        function()
    except (ValueError, KeyError, TypeError) as e:
        assert reason in str(e), (reason, str(e))
        return str(e)
    raise AssertionError("Expected rejection: " + reason)


def case(name, function):
    started = now().isoformat()
    try:
        detail = function()
    except BaseException as e:
        result = dict(
            name=name,
            status="FAILED",
            started=started,
            ended=now().isoformat(),
            error=repr(e),
            traceback=traceback.format_exc(),
        )
        RESULTS.append(result)
        save(EVIDENCE / "results.json", RESULTS)
        raise
    RESULTS.append(
        dict(name=name, status="PASSED", started=started, ended=now().isoformat(), detail=detail)
    )
    print(name + ": PASSED", flush=True)


def helper(volume, code, uid="10002:10002", expected=0):
    return docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--user",
        uid,
        "--memory",
        "128m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "32",
        "--mount",
        f"type=volume,src={volume},dst=/custody",
        "--entrypoint",
        "/usr/local/bin/python",
        BASE,
        "-I",
        "-c",
        code,
        expected=expected,
    )


def fixture(seconds=90, image=None, label_changes=None, config_changes=None, name="positive"):
    image = image or IMAGE
    token = uuid.uuid4().hex
    namespace = "synthetic-" + token
    nonce = uuid.uuid4().hex
    volume = "synthetic-retention-" + token
    label_args = []
    for k, v in dict(namespace=namespace, nonce=nonce, purpose="synthetic-custody").items():
        label_args += ["--label", PREFIX + k + "=" + v]
    docker("volume", "create", *label_args, volume)
    vol = json.loads(docker("volume", "inspect", volume).stdout)[0]
    assert vol["Name"] == volume and vol["Driver"] == "local" and not vol["Options"]
    mount = Path(vol["Mountpoint"])
    assert mount.resolve() == Path("/var/lib/docker/volumes") / volume / "_data"
    assert not mount.is_symlink() and not list(mount.iterdir())
    os.chmod(mount, 0o700)
    assert stat.S_IMODE(mount.stat().st_mode) == 0o700
    os.chown(mount, 10002, 10002)
    info = mount.stat()
    assert info.st_uid == info.st_gid == 10002 and stat.S_IMODE(info.st_mode) == 0o700
    empty = helper(
        volume,
        "import os; assert os.geteuid()==os.getegid()==10002; "
        "assert os.listdir('/custody')==[]; print('custodian enumeration empty')",
    )
    bodies = {"nested/one.txt": b"synthetic retained bytes\n", "two.bin": b"\x00\x01synthetic\xff"}
    created = now()
    plan = dict(
        version="retention-ops-1.0",
        namespace=namespace,
        volume=volume,
        nonce=nonce,
        created_at=created.isoformat(),
        expires_at=(created + timedelta(seconds=seconds)).isoformat(),
        interval_seconds=0.2,
        usage="SYNTHETIC_RETENTION_REHEARSAL",
        files={k: dict(sha256=sha(v), size=len(v)) for k, v in bodies.items()},
    )
    if config_changes:
        plan.update(config_changes)
    body = canonical(plan)
    config = ROOT / ("config-" + token)
    config.mkdir(mode=0o755)
    os.chmod(config, 0o755)
    (config / "plan.json").write_bytes(body)
    os.chmod(config / "plan.json", 0o444)
    marker = canonical(dict(namespace=namespace, volume=volume, nonce=nonce, plan_sha256=sha(body)))
    payload = {k: base64.b64encode(v).decode() for k, v in bodies.items()}
    code = """import os,base64,json,hashlib
from pathlib import Path
os.umask(0o077)
r=Path('/custody')
(r/'control').mkdir(mode=0o700)
(r/'data').mkdir(mode=0o700)
(r/'data'/'nested').mkdir(mode=0o700)
for name,value in json.loads(PAYLOAD).items():
    p=r/'data'/name
    with p.open('xb') as f:f.write(base64.b64decode(value))
    assert (p.stat().st_mode & 0o777)==0o600
with (r/'control'/'identity.json').open('xb') as f:f.write(base64.b64decode(MARKER))
print(json.dumps({'uid':os.geteuid(),'gid':os.getegid(),'groups':os.getgroups(),
    'files':sorted(str(p.relative_to(r)) for p in r.rglob('*'))}))
""".replace("PAYLOAD", repr(json.dumps(payload))).replace(
        "MARKER", repr(base64.b64encode(marker).decode())
    )
    helper(volume, code)
    image_info = json.loads(docker("image", "inspect", image).stdout)[0]
    env = list(image_info["Config"]["Env"]) + ["RV_RETENTION_PLAN_SHA256=" + sha(body)]
    tmpfs = {"/status": "rw,nosuid,nodev,noexec,size=1048576,mode=0700,uid=10002,gid=10002"}
    provision = dict(
        namespace=namespace,
        nonce=nonce,
        role="retention",
        purpose="synthetic-retention",
        name="synthetic-watchdog-" + token,
        kind="standalone",
        image_id=image_info["Id"],
        command=image_info["Config"].get("Cmd"),
        entrypoint=image_info["Config"]["Entrypoint"],
        user="10002:10002",
        environment=env,
        mounts=[
            dict(type="volume", source=volume, target="/custody", rw=True),
            dict(type="bind", source=str(config), target="/config", rw=False),
        ],
        security=dict(
            ReadonlyRootfs=True,
            Privileged=False,
            CapDrop=["ALL"],
            CapAdd=None,
            SecurityOpt=["no-new-privileges:true"],
        ),
        networks=["none"],
        tmpfs=tmpfs,
        retention_plan_sha256=sha(body),
        script_sha256=WATCHDOG_SHA,
        deadline=plan["expires_at"],
    )
    labels = explicit_labels(provision)
    if label_changes:
        for k, v in label_changes.items():
            if v is None:
                labels.pop(k, None)
            else:
                labels[k] = v
    label_args = []
    for k, v in labels.items():
        label_args += ["--label", k + "=" + v]
    cid = (
        docker(
            "create",
            "--name",
            provision["name"],
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "10002:10002",
            "--memory",
            "128m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "32",
            "--restart",
            "no",
            "--tmpfs",
            "/status:" + tmpfs["/status"],
            "--mount",
            f"type=volume,src={volume},dst=/custody",
            "--mount",
            f"type=bind,src={config},dst=/config,readonly",
            "-e",
            "RV_RETENTION_PLAN_SHA256=" + sha(body),
            *label_args,
            image,
        )
        .stdout.decode()
        .strip()
    )
    observed = inspect(cid)
    vol_receipt = {
        k: vol.get(k) for k in ["Name", "Driver", "CreatedAt", "Mountpoint", "Labels", "Options"]
    }
    receipt = dict(
        plan_sha256=sha(canonical(provision)),
        container_id=cid,
        created_at=observed["Created"],
        explicit_labels=explicit_labels(provision),
        volumes={volume: vol_receipt},
    )
    f = dict(
        name=name,
        plan=plan,
        provision=provision,
        receipt=receipt,
        cid=cid,
        image=image_info,
        volumes={volume: vol},
        mount=mount,
        bodies=bodies,
        config=config,
    )
    FIXTURES.append(f)
    save(
        EVIDENCE / (token + "-provision.json"),
        dict(
            plan=plan,
            provision=provision,
            receipt=receipt,
            actual_container=observed,
            actual_volume=vol,
            empty_probe=empty.stdout.decode(),
        ),
    )
    return f


def validate(f):
    return validate_container(
        f["provision"], f["receipt"], inspect(f["cid"]), f["image"], f["volumes"]
    )


def readback(f):
    return {
        str(p.relative_to(f["mount"] / "data")): sha(p.read_bytes())
        for p in (f["mount"] / "data").rglob("*")
        if p.is_file()
    }


def start(f):
    assert validate(f) == "retention"
    docker("start", f["cid"])


def heart(f):
    return json.loads(
        docker(
            "exec",
            f["cid"],
            "/usr/local/bin/python",
            "-I",
            "-c",
            "from pathlib import Path;print(Path('/status/heartbeat.json').read_text())",
        ).stdout
    )


def process(f):
    return json.loads(
        docker("exec", f["cid"], "/usr/local/bin/python", "-I", "-c", COLLECT).stdout
    )["process"]


def observed(f, remaining):
    started = time.monotonic()
    container = json.loads(docker("inspect", f["cid"], timeout=remaining).stdout)[0]
    if not container["State"]["Running"]:
        raise ValueError("watchdog_unavailable")
    remaining -= time.monotonic() - started
    if remaining <= 0:
        raise ValueError("startup_timeout")
    snapshot = process_snapshot(container)
    return dict(snapshot, container=container, image=f["image"], volumes=f["volumes"])


def healthy(f):
    observations = []

    def collect(remaining):
        value = observed(f, remaining)
        observations.append(value)
        return value

    result = wait_ready(f["provision"], f["receipt"], collect)
    save(
        EVIDENCE / (f["cid"][:12] + "-readiness-" + uuid.uuid4().hex + ".json"),
        dict(observations=observations, result=result),
    )
    return result


def await_heartbeat(f, phase=None, min_sequence=0):
    until = time.monotonic() + 6
    while time.monotonic() < until:
        value = observed(f, until - time.monotonic())
        h = value["heartbeat"]
        if (
            h is not None
            and h["sequence"] > min_sequence
            and (phase is None or h["phase"] == phase)
        ):
            return h
        time.sleep(0.2)
    raise ValueError("startup_timeout")


def wait_exit(f):
    state = inspect(f["cid"])["State"]
    until = time.monotonic() + 8
    while state["Running"] and time.monotonic() < until:
        time.sleep(0.2)
        state = inspect(f["cid"])["State"]
    docker("logs", f["cid"])
    assert not state["Running"] and state["ExitCode"] != 0, state
    return state


def adversarial():
    def compose_identity():
        token = uuid.uuid4().hex
        folder = ROOT / ("compose-" + token)
        folder.mkdir(mode=0o700)
        image_info = json.loads(docker("image", "inspect", BASE).stdout)[0]
        plan = dict(
            namespace="synthetic-" + token,
            nonce=uuid.uuid4().hex,
            role="application",
            purpose="synthetic-compose",
            name="synthetic-compose-" + token,
            kind="compose",
            image_id=BASE,
            command=["-c", "import time; time.sleep(600)"],
            entrypoint=["/usr/local/bin/python"],
            user="10001:10001",
            environment=image_info["Config"]["Env"],
            mounts=[],
            security=dict(
                ReadonlyRootfs=True,
                Privileged=False,
                CapDrop=["ALL"],
                CapAdd=None,
                SecurityOpt=["no-new-privileges:true"],
            ),
            networks=["none"],
            tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=1048576"},
            compose_project="synthetic-" + token,
            compose_service="application",
            working_directory=str(folder),
        )
        labels = explicit_labels(plan)
        doc = dict(
            services=dict(
                application=dict(
                    image="python:3.12.12-slim",
                    container_name=plan["name"],
                    user=plan["user"],
                    read_only=True,
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
                    network_mode="none",
                    entrypoint=plan["entrypoint"],
                    command=plan["command"],
                    labels=labels,
                    tmpfs=["/tmp:" + plan["tmpfs"]["/tmp"]],
                    restart="no",
                )
            )
        )
        save(folder / "compose.json", doc)
        docker(
            "compose",
            "-p",
            plan["compose_project"],
            "-f",
            folder / "compose.json",
            "create",
            "--pull",
            "never",
        )
        actual = inspect(plan["name"])
        receipt = dict(
            plan_sha256=sha(canonical(plan)),
            container_id=actual["Id"],
            created_at=actual["Created"],
            explicit_labels=labels,
            volumes={},
        )
        assert validate_container(plan, receipt, actual, image_info, {}) == "application"
        wrong = copy.deepcopy(actual)
        wrong["Config"]["Labels"]["com.docker.compose.project.working_dir"] = "/unrelated"
        rejection(
            lambda: validate_container(plan, receipt, wrong, image_info, {}),
            "compose_working_directory",
        )
        save(
            EVIDENCE / "compose-identity.json",
            dict(plan=plan, receipt=receipt, actual_container=actual),
        )
        docker("rm", actual["Id"])
        return dict(container=actual["Id"], working_directory_preserved=True)

    case("ordinary_compose_identity_and_working_directory", compose_identity)
    for label_changes, reason, title in [
        ({PREFIX + "nonce": None}, "runtime_identity_labels", "missing_runtime_identity"),
        (
            {PREFIX + "namespace": "synthetic-" + ("0" * 32)},
            "runtime_identity_labels",
            "cross_namespace_runtime_identity",
        ),
        (
            {"com.docker.compose.project.working_dir": "/unrelated"},
            "conflicting_compose_identity",
            "conflicting_compose_identity",
        ),
    ]:

        def negative(labels=label_changes, expected=reason):
            f = fixture(label_changes=labels, name=expected)
            before = readback(f)
            result = rejection(lambda: validate(f), expected)
            assert inspect(f["cid"])["State"]["Status"] == "created" and readback(f) == before
            return result

        case(title, negative)

    def inherited():
        seed = (
            docker(
                "create",
                "--label",
                "com.docker.compose.project=inherited-unrelated",
                "--label",
                "com.docker.compose.service=tests",
                IMAGE,
            )
            .stdout.decode()
            .strip()
        )
        inherited_image = docker("commit", seed).stdout.decode().strip()
        f = fixture(image=inherited_image, name="inherited-compose")
        assert validate(f) == "retention"
        docker("rm", seed)
        return dict(image=inherited_image, container=f["cid"], role="retention")

    case("actual_image_inherited_compose_labels_are_inert", inherited)

    def image_identity():
        seed = (
            docker("create", "--label", PREFIX + "namespace=forged-image-identity", IMAGE)
            .stdout.decode()
            .strip()
        )
        malicious = docker("commit", seed).stdout.decode().strip()
        f = fixture(image=malicious, name="image-identity")
        result = rejection(lambda: validate(f), "runtime_labels_in_image")
        docker("rm", seed)
        return result

    case("actual_image_inherited_provisioning_identity_rejected", image_identity)
    f = fixture(name="substitution-controls")
    for field, reason in [
        ("container_id", "container_identity"),
        ("created_at", "container_creation_changed"),
        ("plan_sha256", "provisioning_plan_changed"),
    ]:

        def substitution(key=field, expected=reason):
            receipt = copy.deepcopy(f["receipt"])
            receipt[key] = "forged"
            return rejection(
                lambda: validate_container(
                    f["provision"], receipt, inspect(f["cid"]), f["image"], f["volumes"]
                ),
                expected,
            )

        case("forged_receipt_" + field, substitution)

    def wrong_image():
        actual = inspect(f["cid"])
        other = json.loads(docker("image", "inspect", BASE).stdout)[0]
        return rejection(
            lambda: validate_container(f["provision"], f["receipt"], actual, other, f["volumes"]),
            "container_image",
        )

    case("wrong_actual_image_inspection_rejected", wrong_image)
    for key, reason in [("Name", "volume_identity"), ("Options", "volume_driver_or_options")]:

        def wrong_volume(field=key, expected=reason):
            volumes = copy.deepcopy(f["volumes"])
            volumes[f["plan"]["volume"]][field] = "forged"
            return rejection(
                lambda: validate_container(
                    f["provision"], f["receipt"], inspect(f["cid"]), f["image"], volumes
                ),
                expected,
            )

        case("wrong_volume_" + key, wrong_volume)
    # Independently create actual containers with an incorrect mount or privilege
    # configuration; validate their observed properties before any start.
    for privileged, reason, title in [
        (True, "runtime_security_Privileged", "actual_unexpected_privileges"),
        (False, "mount_identity", "actual_wrong_mount_target"),
    ]:

        def bad_container(privilege=privileged, expected=reason):
            plan = copy.deepcopy(f["provision"])
            receipt = copy.deepcopy(f["receipt"])
            plan["name"] = "synthetic-mismatch-" + uuid.uuid4().hex
            labels = explicit_labels(plan)
            label_args = []
            for k, v in labels.items():
                label_args += ["--label", k + "=" + v]
            target = "/custody" if privilege else "/wrong"
            arguments = ["--privileged"] if privilege else []
            cid = (
                docker(
                    "create",
                    "--name",
                    plan["name"],
                    "--user",
                    "10002:10002",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--tmpfs",
                    "/status:" + plan["tmpfs"]["/status"],
                    "--mount",
                    f"type=volume,src={f['plan']['volume']},dst={target}",
                    "--mount",
                    f"type=bind,src={f['config']},dst=/config,readonly",
                    "-e",
                    "RV_RETENTION_PLAN_SHA256=" + plan["retention_plan_sha256"],
                    *label_args,
                    *arguments,
                    IMAGE,
                )
                .stdout.decode()
                .strip()
            )
            actual = inspect(cid)
            # Bind its creation identity, while retaining the independently expected
            # security/mount contract; copied receipt cannot hide the runtime mismatch.
            receipt.update(
                container_id=cid,
                created_at=actual["Created"],
                plan_sha256=sha(canonical(plan)),
                explicit_labels=labels,
            )
            result = rejection(
                lambda: validate_container(plan, receipt, actual, f["image"], f["volumes"]),
                expected,
            )
            assert actual["State"]["Status"] == "created"
            docker("rm", cid)
            return dict(
                rejection=result,
                observed_privileged=actual["HostConfig"]["Privileged"],
                observed_mounts=actual["Mounts"],
            )

        case(title, bad_container)
    for kind in ["extra_file", "extra_directory", "symlink", "hardlink", "changed_bytes"]:

        def path_attack(attack=kind):
            item = fixture(name=attack)
            root = item["mount"] / "data"
            original = readback(item)
            sentinel = ROOT / ("sentinel-" + uuid.uuid4().hex)
            sentinel.write_bytes(b"unrelated synthetic target")
            sentinel_hash = sha(sentinel.read_bytes())
            if attack == "extra_file":
                p = root / "unapproved.txt"
                p.write_bytes(b"unapproved")
                os.chmod(p, 0o600)
                os.chown(p, 10002, 10002)
            elif attack == "extra_directory":
                p = root / "unapproved"
                p.mkdir(mode=0o700)
                os.chown(p, 10002, 10002)
            elif attack == "symlink":
                os.symlink(sentinel, root / "escape")
            elif attack == "hardlink":
                os.link(root / "two.bin", root / "second-link")
            elif attack == "changed_bytes":
                (root / "two.bin").write_bytes(b"changed synthetic source")
            start(item)
            state = wait_exit(item)
            assert (root / "nested" / "one.txt").exists()
            assert sha(sentinel.read_bytes()) == sentinel_hash
            assert not (item["mount"] / "control" / "expiry-intent.json").exists()
            return dict(
                state=state,
                sentinel_unchanged=sentinel_hash,
                approved_file_preserved=original["nested/one.txt"],
            )

        case("path_inventory_" + kind, path_attack)
    for path in ["../escape", "/unrelated/target"]:

        def invalid_path(target=path):
            f = fixture(
                config_changes={"files": {target: dict(sha256="a" * 64, size=1)}},
                name="forged-path",
            )
            before = readback(f)
            start(f)
            state = wait_exit(f)
            assert readback(f) == before
            return state

        case("forged_path_" + path, invalid_path)

    def corrupt_image(kind):
        context = ROOT / ("corrupt-" + uuid.uuid4().hex)
        context.mkdir(mode=0o700)
        with tarfile.open(ROOT / "canonical-transfer.tar") as t:
            bodies = {m.name: t.extractfile(m).read() for m in t if m.isfile()}
        if kind == "checksum":
            bodies["watchdog.py"] += b"\n# deliberate synthetic corruption\n"
        elif kind == "bom":
            bodies["watchdog.py"] = b"\xef\xbb\xbf" + bodies["watchdog.py"]
            manifest = json.loads(bodies["bundle.json"])
            manifest["watchdog.py"] = sha(bodies["watchdog.py"])
            bodies["bundle.json"] = canonical(manifest)
        elif kind == "syntax":
            bodies["watchdog.py"] = b"#!/usr/local/bin/python\nif (\n"
            manifest = json.loads(bodies["bundle.json"])
            manifest["watchdog.py"] = sha(bodies["watchdog.py"])
            bodies["bundle.json"] = canonical(manifest)
        elif kind == "shebang":
            bodies["watchdog.py"] = b"\n" + bodies["watchdog.py"]
            manifest = json.loads(bodies["bundle.json"])
            manifest["watchdog.py"] = sha(bodies["watchdog.py"])
            bodies["bundle.json"] = canonical(manifest)
        for name in ["watchdog.py", "bundle.json"]:
            (context / name).write_bytes(bodies[name])
        (context / "Dockerfile").write_text(
            "FROM repovox-synthetic-retention:verified\nUSER 0:0\n"
            "COPY --chmod=0555 watchdog.py /opt/rv-retention/watchdog.py\n"
            "COPY --chmod=0444 bundle.json /opt/rv-retention/bundle.json\nUSER 10002:10002\n"
        )
        tag = "synthetic-corrupt-" + uuid.uuid4().hex
        docker("build", "--network", "none", "-t", tag, context)
        p = docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            tag,
            expected=None,
        )
        assert p.returncode != 0
        expected = {
            "checksum": b"bundle_hash",
            "bom": b"bundle_encoding_or_shebang",
            "syntax": b"SyntaxError",
            "shebang": b"bundle_encoding_or_shebang",
        }[kind]
        assert expected in p.stderr, (kind, p.stderr)
        return dict(exit=p.returncode, reason=expected.decode())

    for kind in ["checksum", "bom", "syntax", "shebang"]:
        case("executable_negative_" + kind, lambda k=kind: corrupt_image(k))


def main():
    global BASE, IMAGE, WATCHDOG_SHA
    os.umask(0o077)
    EVIDENCE.mkdir(mode=0o700, exist_ok=False)
    info = json.loads(docker("info", "--format", "{{json .}}").stdout)
    assert info["ID"] == EXPECTED_DAEMON and info["DockerRootDir"] == "/var/lib/docker"
    baseline = json.loads((ROOT / "baseline.json").read_bytes())
    assert set(docker("ps", "-aq").stdout.decode().splitlines()) == set(baseline["containers"])
    assert set(docker("volume", "ls", "-q").stdout.decode().splitlines()) == set(
        baseline["volumes"]
    )
    assert not docker("ps", "-q").stdout.strip()
    BASE = json.loads((ROOT / "base-image.json").read_text())[0]["Id"]
    IMAGE = json.loads((ROOT / "retention-image.json").read_text())[0]["Id"]
    WATCHDOG_SHA = "f037551ffc8eb8270e6fc228c02b6bc7a325757f23b463f0d3a480d08e78fd90"
    positive = fixture(seconds=45)
    case("valid_container_identity", lambda: validate(positive))

    def exact_scripts():
        p = docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "10002:10002",
            "--entrypoint",
            "/usr/local/bin/python",
            IMAGE,
            "-I",
            "/opt/rv-retention/verify_bundle.py",
        )
        return dict(exit=p.returncode)

    case("binary_checksum_target_shell_and_permissions", exact_scripts)
    start(positive)
    case("actual_process_capabilities_and_advancing_heartbeats", lambda: healthy(positive))
    case(
        "pre_expiry_original_bytes_preserved",
        lambda: (
            readback(positive) == {k: sha(v) for k, v in positive["bodies"].items()}
            or (_ for _ in ()).throw(AssertionError("pre-expiry bytes changed"))
        ),
    )

    def denied():
        code = """import os,json
from pathlib import Path
assert os.geteuid()==os.getegid()==10001
denied=[]
for operation in [lambda:os.listdir('/custody'),lambda:Path('/custody/data/two.bin').read_bytes()]:
    try:operation()
    except PermissionError:denied.append(True)
assert len(denied)==2
print(json.dumps({'uid':os.geteuid(),'gid':os.getegid(),'groups':os.getgroups(),'denied':len(denied),'status':Path('/proc/self/status').read_text()}))"""
        return json.loads(helper(positive["plan"]["volume"], code, uid="10001:10001").stdout)

    case("noncustodian_actual_read_and_enumeration_denial", denied)

    def stall():
        docker("kill", "--signal", "STOP", positive["cid"])
        h = heart(positive)
        error = rejection(
            lambda: readiness(
                positive["provision"],
                positive["receipt"],
                inspect(positive["cid"]),
                positive["image"],
                positive["volumes"],
                h,
                h,
                process(positive),
            ),
            "watchdog_no_progress",
        )
        time.sleep(3.1)
        rejection(
            lambda: readiness(
                positive["provision"],
                positive["receipt"],
                inspect(positive["cid"]),
                positive["image"],
                positive["volumes"],
                h,
                h,
                process(positive),
            ),
            "heartbeat_stale",
        )
        docker("kill", "--signal", "CONT", positive["cid"])
        await_heartbeat(positive, min_sequence=h["sequence"])
        healthy(positive)
        return error

    case("running_without_progress_and_stale_health_rejected", stall)

    def concurrent():
        p = docker(
            "exec",
            positive["cid"],
            "/usr/local/bin/python",
            "-I",
            "/opt/rv-retention/watchdog.py",
            expected=None,
        )
        assert p.returncode != 0 and b"BlockingIOError" in p.stderr
        return dict(exit=p.returncode)

    case("concurrent_retention_lock_denied", concurrent)

    def expiry():
        sentinel = ROOT / "unrelated-sentinel"
        sentinel.write_bytes(b"unrelated synthetic sentinel\n")
        before = sha(sentinel.read_bytes())
        deadline = datetime.fromisoformat(positive["plan"]["expires_at"])
        while now() <= deadline + timedelta(seconds=2):
            if not readback(positive):
                break
            time.sleep(0.2)
        assert not readback(positive), "expiry_failed_to_delete"
        receipt = (positive["mount"] / "control" / "expired.json").read_bytes()
        saved = json.loads(receipt)
        assert datetime.fromisoformat(saved["completed_at"]) >= deadline
        assert sha(sentinel.read_bytes()) == before
        assert heart(positive)["phase"] == "EXPIRED"
        docker("stop", "--time", "2", positive["cid"])
        docker("start", positive["cid"])
        await_heartbeat(positive, "EXPIRED")
        assert (positive["mount"] / "control" / "expired.json").read_bytes() == receipt
        assert not readback(positive) and heart(positive)["phase"] == "EXPIRED"
        docker("stop", "--time", "2", positive["cid"])
        return dict(
            receipt=saved,
            sentinel_sha256=before,
            remaining_files=[],
            idempotent_receipt_sha256=sha(receipt),
        )

    case("exact_expiry_deletion_duplicate_restart_idempotency", expiry)

    def missed():
        f = fixture(seconds=10, name="missed-expiry")
        start(f)
        first = await_heartbeat(f)
        docker("stop", "--time", "1", f["cid"])
        while now() < datetime.fromisoformat(f["plan"]["expires_at"]) + timedelta(seconds=0.3):
            time.sleep(0.2)
        assert len(readback(f)) == 2
        docker("start", f["cid"])
        second = await_heartbeat(f, "EXPIRED")
        assert second["boot"] != first["boot"] and second["phase"] == "EXPIRED"
        assert not readback(f) and second["deadline"] == first["deadline"]
        docker("stop", "--time", "1", f["cid"])
        return dict(before_boot=first["boot"], after_boot=second["boot"], remaining_files=[])

    case("missed_expiry_recovery_actual_filesystem", missed)

    def invalid_start():
        f = fixture(config_changes={"usage": "REAL_NOT_AUTHORIZED"}, name="immediate-exit")
        before = readback(f)
        start(f)
        state = wait_exit(f)
        assert readback(f) == before
        fallback = unavailable(f["provision"], "watchdog exited")
        assert fallback["ready"] is False and fallback["extend_deadline"] is False
        return dict(state=state, fallback=fallback)

    case("immediate_exit_absent_health_and_owner_fallback", invalid_start)
    adversarial()
    save(EVIDENCE / "results.json", RESULTS)
    save(
        EVIDENCE / "fixture-index.json",
        [
            dict(cid=f["cid"], volume=f["plan"]["volume"], namespace=f["plan"]["namespace"])
            for f in FIXTURES
        ],
    )
    print("Actual-runtime retention proof completed.", flush=True)


if __name__ == "__main__":
    main()

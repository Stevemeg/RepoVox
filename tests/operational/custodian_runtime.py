"""Root operator on an independently verified Linux Docker host; synthetic only.

Creates only new UUID resources. Retains stopped containers, volumes and command
evidence; never discovers or cleans up real custody. No Docker socket enters a
container. The caller must verify guest/storage/network isolation before invocation.
"""

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path


def run(source, image, expected_daemon, evidence):
    assert os.geteuid() == 0
    evidence.mkdir(mode=0o700, exist_ok=False)
    docker = ["docker", "--host", "unix:///var/run/docker.sock"]
    sequence = 0

    def command(*args, expected=0):
        nonlocal sequence
        sequence += 1
        before = datetime.now(UTC).isoformat()
        result = subprocess.run(docker + list(args), capture_output=True, timeout=180)
        stem = evidence / str(sequence)
        stem.with_suffix(".stdout").write_bytes(result.stdout)
        stem.with_suffix(".stderr").write_bytes(result.stderr)
        stem.with_suffix(".json").write_text(
            json.dumps(
                dict(
                    command=docker + list(args),
                    started=before,
                    ended=datetime.now(UTC).isoformat(),
                    exit_code=result.returncode,
                )
            )
        )
        assert result.returncode == expected, result.stderr
        return result.stdout

    assert command("info", "--format", "{{.ID}}").decode().strip() == expected_daemon
    tag = "synthetic-retention-lifecycle-" + uuid.uuid4().hex
    volume = tag + "-data"
    command("volume", "create", "--label", "io.repovox.purpose=synthetic-lifecycle", volume)
    record = json.loads(command("volume", "inspect", volume))[0]
    assert record["Name"] == volume and record["Driver"] == "local" and not record["Options"]
    assert record["Labels"] == {"io.repovox.purpose": "synthetic-lifecycle"}
    target = Path(record["Mountpoint"])
    assert target == Path("/var/lib/docker/volumes") / volume / "_data"
    assert target.is_dir() and not target.is_symlink() and not list(target.iterdir())
    target.chmod(0o700)
    os.chown(target, 10002, 10002)
    assert target.stat().st_uid == target.stat().st_gid == 10002
    sources = evidence / "source"
    sources.mkdir(mode=0o755)
    hashes = {}
    for name in [
        "tools/phase2_custodian_lifecycle.py",
        "tools/phase2_custodian_adapter.py",
        "tools/phase2_custodian_watchdog.py",
        "tools/phase2_custodian_review.py",
        "tools/phase2_custodian_source.py",
        "tests/unit/test_custodian_lifecycle.py",
        "tests/unit/test_custodian_review.py",
        "tests/unit/test_custodian_source.py",
    ]:
        destination = sources / name
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
        destination.chmod(0o644)
        hashes[name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    # Parent remains private; bind source is resolved by the trusted Docker daemon.
    actual_image = json.loads(command("image", "inspect", image))[0]["Id"]

    def container(user, args):
        name = tag + "-" + uuid.uuid4().hex[:12]
        cid = (
            command(
                "create",
                "--name",
                name,
                "--user",
                user,
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--read-only",
                "--network",
                "none",
                "--memory",
                "256m",
                "--cpus",
                "1",
                "--pids-limit",
                "64",
                "--tmpfs",
                "/tmp:rw,nosuid,noexec,size=64m",
                "-v",
                str(sources) + ":/overlay:ro",
                "-v",
                volume + ":/synthetic-custody:rw",
                "-e",
                "PYTHONPATH=/overlay:/workspace:/workspace/tests/unit",
                "-e",
                "RV_CUSTODIAN_TEST_EVIDENCE=/synthetic-custody/test-evidence",
                actual_image,
                *args,
            )
            .decode()
            .strip()
        )
        observed = json.loads(command("inspect", cid))[0]
        assert observed["Id"] == cid and observed["Image"] == actual_image
        assert observed["Config"]["User"] == user
        host = observed["HostConfig"]
        assert host["CapDrop"] == ["ALL"] and not host["CapAdd"] and not host["Privileged"]
        assert host["ReadonlyRootfs"] and host["SecurityOpt"] == ["no-new-privileges:true"]
        assert host["NetworkMode"] == "none" and host["RestartPolicy"]["Name"] == "no"
        mounts = {m["Destination"]: m for m in observed["Mounts"]}
        assert set(mounts) == {"/overlay", "/synthetic-custody"}
        assert mounts["/synthetic-custody"]["Name"] == volume
        assert mounts["/overlay"]["Source"] == str(sources) and not mounts["/overlay"]["RW"]
        command("start", "-a", cid)
        final = json.loads(command("inspect", cid))[0]
        assert not final["State"]["Running"] and final["State"]["ExitCode"] == 0

    container(
        "10002:10002",
        [
            "pytest",
            "-q",
            "--tb=short",
            "/overlay/tests/unit/test_custodian_lifecycle.py",
            "/overlay/tests/unit/test_custodian_review.py",
        ],
    )
    container(
        "10002:10002",
        ["pytest", "-q", "--tb=short", "/overlay/tests/unit/test_custodian_source.py"],
    )
    creation = """
import json
from pathlib import Path
from datetime import UTC,datetime,timedelta
from tools.phase2_custodian_lifecycle import Lifecycle,canonical,digest
parent=Path('/synthetic-custody');now=datetime.now(UTC)
plan=dict(version='custodian-lifecycle-1.0',namespace='synthetic-probe',tenant='tenantA',attempt='attemptA',manifest_sha256='a'*64,created_at=now.isoformat(),expires_at=(now+timedelta(seconds=120)).isoformat(),authorization_expires_at=(now+timedelta(seconds=120)).isoformat(),authorization_sha256=digest(b'synthetic-only-token'))
root=parent/'namespace';receipt=Lifecycle.create(root,plan)
life=Lifecycle(root,plan,receipt)
token=dict(tenant='tenantA',namespace='synthetic-probe',attempt='attemptA',generation=1,secret='synthetic-only-token')
life.activate(token,dict(namespace=plan['namespace'],plan_sha256=life.plan_sha,runtime_verified=True,observed_at=datetime.now(UTC).isoformat(),progress=[1,2]))
life.put(token,{'probe':b'synthetic access probe'})
(parent/'config.json').write_bytes(canonical(dict(plan=plan,receipt=receipt,token=token)))
(parent/'sentinel').write_bytes(b'unrelated synthetic sentinel')
assert (root/'data/probe').stat().st_mode&0o777==0o600
"""
    container("10002:10002", ["python", "-c", creation])
    denied = """
import os
actions=[lambda:os.listdir('/synthetic-custody'),
         lambda:open('/synthetic-custody/namespace/data/probe','rb').read()]
for action in actions:
    try:action()
    except PermissionError:pass
    else:raise AssertionError('UID10001 custody access was not denied')
print('UID10001 actual enumeration and read denied')
"""
    container("10001:10001", ["python", "-c", denied])
    completion = """
import json
from pathlib import Path
from tools.phase2_custodian_lifecycle import Lifecycle
parent=Path('/synthetic-custody');config=json.loads((parent/'config.json').read_bytes())
life=Lifecycle(parent/'namespace',config['plan'],config['receipt'])
assert life.read(config['token'],'probe')==b'synthetic access probe'
life.transition(config['token'],'WITHDRAWN')
assert life.tick()['state']=='EXPIRED'
assert not list(life.data.iterdir())
assert (parent/'sentinel').read_bytes()==b'unrelated synthetic sentinel'
print('UID10002 read passed; all registered bytes removed; unrelated sentinel unchanged')
"""
    container("10002:10002", ["python", "-c", completion])
    (evidence / "summary.json").write_text(
        json.dumps(
            dict(
                status="PASSED",
                namespace=tag,
                daemon=expected_daemon,
                image=actual_image,
                volume=record,
                source_sha256=hashes,
                real_custody_mounted=False,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    import sys

    run(Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]))

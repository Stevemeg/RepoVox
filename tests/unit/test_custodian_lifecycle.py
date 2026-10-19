"""Synthetic bytes only. Actual POSIX locks, SQLite durability, processes and expiry."""

import errno
import json
import multiprocessing
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("fcntl")

from test_evaluation_v2 import case as case

from tools.phase2_custodian_adapter import CustodianStore
from tools.phase2_custodian_lifecycle import Lifecycle, canonical, digest

pytestmark = pytest.mark.skipif(
    os.geteuid() != 10002, reason="requires actual restricted custodian UID"
)


def record(name, value):
    destination = os.environ.get("RV_CUSTODIAN_TEST_EVIDENCE")
    if destination:
        path = Path(destination)
        path.mkdir(mode=0o700, exist_ok=True)
        with (path / (name + "-" + uuid.uuid4().hex + ".json")).open("x") as stream:
            json.dump(value, stream, indent=2)


def fixture(
    parent,
    seconds=120,
    tenant="tenantA",
    active=True,
    authorization_seconds=None,
    version="custodian-lifecycle-1.0",
):
    now = datetime.now(UTC)
    namespace = "synthetic-" + uuid.uuid4().hex
    secret = "synthetic-authorization-" + uuid.uuid4().hex
    plan = dict(
        version=version,
        namespace=namespace,
        tenant=tenant,
        attempt="attemptA",
        manifest_sha256="a" * 64,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=seconds)).isoformat(),
        authorization_expires_at=(
            now + timedelta(seconds=authorization_seconds or seconds)
        ).isoformat(),
        authorization_sha256=digest(secret.encode()),
    )
    root = parent / namespace
    receipt = Lifecycle.create(root, plan)
    token = {
        "tenant": tenant,
        "namespace": namespace,
        "attempt": "attemptA",
        "generation": 1,
        "secret": secret,
    }
    life = Lifecycle(root, plan, receipt)
    # Unit fixtures use a synthetic receipt. The process test below obtains actual
    # advancing heartbeats and independent /proc identity evidence.
    if active:
        life.activate(
            token,
            dict(
                namespace=namespace,
                plan_sha256=life.plan_sha,
                runtime_verified=True,
                observed_at=datetime.now(UTC).isoformat(),
                progress=[1, 2],
            ),
        )
    return life, token


def saved(life):
    return json.loads(canonical(dict(root=str(life.root), plan=life.plan, receipt=life.receipt)))


def reopen(config):
    return Lifecycle(config["root"], config["plan"], config["receipt"])


def write_process(config, token, name, body, connection, mode="normal"):
    life = reopen(config)
    if mode in {"before", "during", "after", "expiry"}:
        original = os.fdopen

        def fault(fd, *args, **kwargs):
            stream = original(fd, *args, **kwargs)
            if args != ("wb",) or "/data/" not in os.readlink(f"/proc/self/fd/{fd}"):
                return stream
            if mode == "before":
                os._exit(71)
            if mode == "during":
                stream.write(body[:3])
                stream.flush()
                os.fsync(fd)
                os._exit(72)
            if mode == "after":
                stream.write(body)
                stream.flush()
                os.fsync(fd)
                os.fsync(life._df)
                os._exit(73)
            connection.send("writer_holds_lock")
            time.sleep(1.2)
            return stream

        os.fdopen = fault
    try:
        life.put(token, {name: body})
        connection.send("committed")
    except (ValueError, BlockingIOError) as exc:
        connection.send(type(exc).__name__ + ":" + str(exc))


def child(life, token, name, mode="normal", body=b"synthetic private evidence"):
    ctx = multiprocessing.get_context("fork")
    parent, remote = ctx.Pipe()
    process = ctx.Process(target=write_process, args=(saved(life), token, name, body, remote, mode))
    process.start()
    remote.close()
    return process, parent


def wait(process):
    process.join(10)
    assert not process.is_alive()


def test_growth_closure_and_real_expiry(tmp_path):
    life, token = fixture(tmp_path, 1.5)
    sentinel = tmp_path / "unrelated-sentinel"
    sentinel.write_bytes(b"unchanged")
    for i in range(3):
        life.put(token, {f"evidence-{i}": f"exact original {i}\r\n".encode()})
    assert life.read(token, "evidence-1") == b"exact original 1\r\n"
    life.transition(token, "SEALED")
    life.transition(token, "SEALED")
    with pytest.raises(ValueError, match="lifecycle_not_executable"):
        life.put(token, {"extra": b"no"})
    assert life.read(token, "evidence-0")
    time.sleep(1.6)
    assert life.tick()["state"] == "EXPIRED"
    assert list(life.data.iterdir()) == []
    assert sentinel.read_bytes() == b"unchanged"
    record(
        "expiry-filesystem",
        dict(
            plan=life.plan,
            receipt=life.receipt,
            state=life.tick(),
            remaining=list(os.listdir(life.data)),
            sentinel_sha256=digest(sentinel.read_bytes()),
        ),
    )
    assert life.tick()["state"] == "EXPIRED"
    with pytest.raises(ValueError):
        life.activate(token, True)


@pytest.mark.parametrize("mode,exitcode", [("before", 71), ("during", 72), ("after", 73)])
def test_crash_recovery(tmp_path, mode, exitcode):
    life, token = fixture(tmp_path)
    process, _ = child(life, token, "crashed", mode)
    wait(process)
    assert process.exitcode == exitcode
    record(
        "write-crash",
        dict(
            mode=mode, exit_code=process.exitcode, plan=life.plan, files=list(os.listdir(life.data))
        ),
    )
    life = reopen(saved(life))
    if mode == "after":
        assert life.read(token, "crashed") == b"synthetic private evidence"
        assert life.put(token, {"crashed": b"synthetic private evidence"})
    else:
        with pytest.raises(ValueError):
            life.read(token, "crashed")
        assert life.tick()["state"] == "EXPIRED"
        assert not list(life.data.iterdir())


def test_writer_expiry_race(tmp_path):
    life, token = fixture(tmp_path, 0.9)
    process, channel = child(life, token, "racing", "expiry")
    assert channel.poll(5) and channel.recv() == "writer_holds_lock"
    with pytest.raises(BlockingIOError):
        life.tick()
    wait(process)
    assert channel.poll(1)
    result = channel.recv()
    assert "stale_authorization" in result
    assert life.tick()["state"] == "EXPIRED"
    assert not list(life.data.iterdir())
    record(
        "writer-expiry-race",
        dict(result=result, state=life.tick(), remaining=list(os.listdir(life.data))),
    )


def test_simultaneous_writers_and_idempotency(tmp_path):
    life, token = fixture(tmp_path)
    processes = [child(life, token, "one"), child(life, token, "two")]
    for process, channel in processes:
        wait(process)
        assert channel.poll(1)
        assert channel.recv() in {
            "committed",
            "BlockingIOError:[Errno 11] Resource temporarily unavailable",
        }
    life.put(token, {"one": b"synthetic private evidence"})
    life.put(token, {"two": b"synthetic private evidence"})
    with pytest.raises(ValueError, match="exclusive_commitment_conflict"):
        life.put(token, {"one": b"replacement"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant", "tenantB"),
        ("namespace", "other"),
        ("attempt", "other"),
        ("generation", 0),
        ("secret", "forged"),
    ],
)
def test_authorization_denial(tmp_path, field, value):
    life, token = fixture(tmp_path)
    forged = dict(token, **{field: value})
    with pytest.raises(ValueError, match="authorization"):
        life.put(forged, {"denied": b"never"})
    assert not list(life.data.iterdir())


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/b", "..", "a\\b"])
def test_path_rejection(tmp_path, name):
    life, token = fixture(tmp_path)
    with pytest.raises(ValueError, match="evidence_path"):
        life.put(token, {name: b"no"})


@pytest.mark.parametrize(
    "damage", ["extra", "symlink", "hardlink", "corrupt", "missing", "directory"]
)
def test_inventory_attacks_fail_closed(tmp_path, damage):
    life, token = fixture(tmp_path)
    life.put(token, {"registered": b"protected"})
    path = life.data / "registered"
    if damage == "extra":
        (life.data / "extra").write_bytes(b"unexpected")
    elif damage == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / "outside")
    elif damage == "hardlink":
        os.link(path, tmp_path / "outside")
    elif damage == "corrupt":
        path.write_bytes(b"tampered")
    elif damage == "missing":
        path.unlink()
    else:
        path.unlink()
        path.mkdir(mode=0o700)
    with pytest.raises((ValueError, FileNotFoundError)):
        life.tick()


def test_immutable_plan_and_terminal_generation(tmp_path):
    life, token = fixture(tmp_path)
    changed = dict(life.plan, expires_at=(datetime.now(UTC) + timedelta(days=29)).isoformat())
    with pytest.raises(ValueError, match="lifecycle_plan_changed"):
        Lifecycle(life.root, changed, life.receipt)
    life.transition(token, "INVALIDATED")
    life.transition(token, "INVALIDATED")
    with pytest.raises(ValueError):
        life.put(token, {"new": b"denied"})
    assert life.tick()["state"] == "EXPIRED"
    with sqlite3.connect(life.control / "ledger.sqlite") as db:
        with pytest.raises(sqlite3.IntegrityError, match="irreversible_lifecycle"):
            db.execute("UPDATE lifecycle SET state='ACTIVE'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable_plan"):
            db.execute("UPDATE meta SET body='forged'")


def test_disk_full_and_partial_deletion_recovery(tmp_path, monkeypatch):
    life, token = fixture(tmp_path)
    original = os.open

    def full(name, *args, **kwargs):
        if name == "disk-full":
            raise OSError(errno.ENOSPC, "synthetic disk full")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(os, "open", full)
    with pytest.raises(OSError) as raised:
        life.put(token, {"disk-full": b"not committed"})
    assert raised.value.errno == errno.ENOSPC
    monkeypatch.setattr(os, "open", original)
    assert life.tick()["state"] == "INVALIDATED"
    assert life.tick()["state"] == "EXPIRED"


def test_withdrawal_and_failed_unlink(tmp_path, monkeypatch):
    life, token = fixture(tmp_path)
    life.put(token, {"source": b"delete on withdrawal", "response": b"original response"})
    life.transition(token, "WITHDRAWN")
    original = os.unlink
    monkeypatch.setattr(
        os,
        "unlink",
        lambda *a, **k: (_ for _ in ()).throw(PermissionError("synthetic unlink denied")),
    )
    with pytest.raises(PermissionError):
        life.tick()
    monkeypatch.setattr(os, "unlink", original)
    assert life.tick()["state"] == "EXPIRED"
    assert not list(life.data.iterdir())


def test_adapter_full_synthetic_chronology(tmp_path):
    from repovox.evaluation.v2 import digest as v2_digest

    life, token = fixture(tmp_path)
    store = CustodianStore(
        life, token, lambda plan: True, lambda plan: True, synthetic_fixture=True
    )
    records = []
    prediction = store.write("tenantA", b"synthetic prediction, never real")
    for sequence in range(1, 8):
        payload = (
            prediction
            if sequence in {2, 6}
            else store.write("tenantA", f"synthetic event payload {sequence}".encode())
        )
        records.append(
            store.append_event(
                records,
                tenant_id="tenantA",
                session_id="synthetic-session",
                scope_sha256="a" * 64,
                engineering_commit="1" * 40,
                scorer_commit="2" * 40,
                payload_sha256=payload,
                trusted_context="synthetic lifecycle test only",
                identity_basis="synthetic_fixture",
            )
        )
        assert v2_digest(records[-1][0]) == records[-1][1]
    assert len(store.validate_retained_chain(records)) == 7
    store.admission = lambda plan: False
    with pytest.raises(ValueError, match="pilot_admission_denied"):
        store.write("tenantA", b"no")
    store.admission = lambda plan: True
    store.retention_ready = lambda plan: False
    with pytest.raises(ValueError, match="retention_not_ready"):
        store.write("tenantA", b"no")


def test_withdrawal_before_activation(tmp_path):
    life, token = fixture(tmp_path, active=False)
    life.transition(token, "WITHDRAWN")
    assert life.tick()["state"] == "EXPIRED"
    with pytest.raises(ValueError):
        life.activate(token, True)


def test_expired_write_authorization_is_not_renewed_by_restart(tmp_path):
    life, token = fixture(tmp_path, authorization_seconds=0.25)
    life.put(token, {"retained": b"synthetic bytes"})
    original = canonical(life.plan)
    time.sleep(0.3)
    life = reopen(saved(life))
    with pytest.raises(ValueError, match="authorization_expired"):
        life.put(token, {"new": b"not permitted"})
    assert canonical(life.plan) == original
    life.transition(token, "WITHDRAWN")
    assert life.tick()["state"] == "EXPIRED"


def test_git_overlap_rejected_before_creation(tmp_path):
    (tmp_path / ".git").write_bytes(b"synthetic git boundary marker")
    with pytest.raises(ValueError, match="custody_overlaps_git"):
        fixture(tmp_path)


def test_actual_tmpfs_disk_full_preserves_intent(tmp_path):
    capacity = os.statvfs(tmp_path)
    if capacity.f_blocks * capacity.f_frsize > 80_000_000:
        pytest.skip("Actual bounded tmpfs is required; exercised by Docker runtime matrix")
    life, token = fixture(tmp_path)
    filler = tmp_path / "synthetic-only-space-filler"
    with filler.open("xb") as stream:
        stream.write(b"f" * 32_000_000)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        with pytest.raises(OSError) as error:
            life.put(token, {"disk-full-evidence": b"e" * 40_000_000})
        assert error.value.errno == errno.ENOSPC
        record(
            "actual-disk-full",
            dict(
                errno=error.value.errno,
                tmpfs_capacity=capacity.f_blocks * capacity.f_frsize,
                namespace=life.plan["namespace"],
            ),
        )
    finally:
        assert filler.name == "synthetic-only-space-filler" and filler.stat().st_uid == 10002
        filler.unlink()
    assert life.tick()["state"] == "INVALIDATED"
    assert life.tick()["state"] == "EXPIRED"
    assert not list(life.data.iterdir())


def test_watchdog_restart_after_expiry(tmp_path):
    life, token = fixture(tmp_path, 1.5, active=False)
    status = tmp_path / "status"
    status.mkdir(mode=0o700)
    config = tmp_path / "config.json"
    config.write_bytes(canonical(saved(life)))
    env = dict(os.environ, RV_CUSTODIAN_CONFIG_SHA256=digest(config.read_bytes()))
    command = [sys.executable, "-m", "tools.phase2_custodian_watchdog", str(config), str(status)]
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 5
    while not (status / "heartbeat.json").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    first = json.loads((status / "heartbeat.json").read_bytes())
    time.sleep(0.3)
    second = json.loads((status / "heartbeat.json").read_bytes())
    assert second["sequence"] > first["sequence"]
    duplicate = subprocess.run(command, env=env, capture_output=True, timeout=5)
    assert duplicate.returncode != 0 and b"BlockingIOError" in duplicate.stderr
    from tools import phase2_custodian_watchdog as watchdog

    fields = dict(
        line.split(":", 1) for line in Path(f"/proc/{process.pid}/status").read_text().splitlines()
    )
    birth = int(Path(f"/proc/{process.pid}/stat").read_text().rpartition(") ")[2].split()[19])
    source = digest(Path(watchdog.__file__).read_bytes())
    observed = dict(
        uid=list(map(int, fields["Uid"].split())),
        gid=list(map(int, fields["Gid"].split())),
        groups=list(map(int, fields["Groups"].split())),
        caps={k: fields[k].strip() for k in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"]},
        no_new_privs=int(fields["NoNewPrivs"]),
        state=fields["State"].split()[0],
        source_sha256=source,
        command_matches=Path(f"/proc/{process.pid}/cmdline").read_bytes().split(b"\0")[:-1]
        == [s.encode() for s in command],
        birth_ns=birth * 1_000_000_000 // os.sysconf("SC_CLK_TCK"),
    )
    proof = watchdog.validate_progress(first, second, life.plan, observed, source)
    record(
        "watchdog-process",
        dict(
            command=command,
            first=first,
            second=second,
            actual_process=observed,
            proof=proof,
            duplicate_exit=duplicate.returncode,
            duplicate_stderr=duplicate.stderr.decode(),
        ),
    )
    assert proof["runtime_verified"]
    life.activate(token, proof)
    life.put(token, {"source": b"synthetic protected source"})
    with pytest.raises(ValueError, match="watchdog_stalled"):
        watchdog.validate_progress(second, second, life.plan, observed, source)
    with pytest.raises(ValueError, match="heartbeat_absent"):
        watchdog.validate_progress(None, second, life.plan, observed, source)
    with pytest.raises(ValueError, match="heartbeat_stale"):
        watchdog.validate_progress(
            dict(first, checked_at=(datetime.now(UTC) - timedelta(seconds=4)).isoformat()),
            second,
            life.plan,
            observed,
            source,
        )
    process.kill()
    process.communicate(timeout=5)
    time.sleep(max(0, stamp_deadline(life) - time.time()) + 0.1)
    result = subprocess.run(command, env=env, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    record(
        "watchdog-recovery",
        dict(
            command=command,
            exit_code=result.returncode,
            stdout=result.stdout.decode(),
            stderr=result.stderr.decode(),
            remaining=list(os.listdir(life.data)),
        ),
    )
    assert json.loads((status / "heartbeat.json").read_bytes())["state"] == "EXPIRED"
    assert not list(life.data.iterdir())


def stamp_deadline(life):
    return datetime.fromisoformat(life.plan["expires_at"]).timestamp()


def test_wrong_hash_control_mutation_and_permission_failure(tmp_path):
    life, token = fixture(tmp_path)
    store = CustodianStore(life, token, lambda p: True, lambda p: True, synthetic_fixture=True)
    sha = store.write("tenantA", b"exact bytes")
    (life.data / ("tenantA-" + sha)).write_bytes(b"wrong bytes")
    with pytest.raises(ValueError, match="registered_evidence_corrupt"):
        store.read("tenantA", sha)
    (life.control / "unexpected-metadata").write_bytes(b"unknown")
    with pytest.raises(ValueError, match="unexpected_control_entry"):
        life.tick()


def test_directory_substitution_and_private_permissions(tmp_path):
    life, token = fixture(tmp_path)
    life.put(token, {"private": b"private bytes"})
    assert (life.data / "private").stat().st_mode & 0o777 == 0o600
    life.data.rename(life.root / "replaced-data")
    life.data.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="unexpected_namespace_entry|directory_inode_changed"):
        life.tick()


def test_incomplete_event_batch_cannot_commit(tmp_path):
    life, token = fixture(tmp_path)
    config = saved(life)
    ctx = multiprocessing.get_context("fork")

    def crash():
        worker = reopen(config)
        original = worker._file

        def stop(name, *args):
            result = original(name, *args)
            os._exit(75)  # First file is durable; second file/ack is not.
            return result

        worker._file = stop
        worker.put(token, {"first": b"original", "second": b"response"})

    process = ctx.Process(target=crash)
    process.start()
    wait(process)
    assert process.exitcode == 75
    with pytest.raises(ValueError):
        life.read(token, "first")
    assert life.tick()["state"] == "EXPIRED"
    assert not list(life.data.iterdir())


def test_cleanup_crash_between_unlinks(tmp_path):
    life, token = fixture(tmp_path)
    life.put(token, {"one": b"synthetic source", "two": b"synthetic prediction"})
    life.transition(token, "WITHDRAWN")
    config = saved(life)
    ctx = multiprocessing.get_context("fork")

    def crash():
        original = os.unlink

        def unlink(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(76)

        os.unlink = unlink
        reopen(config).tick()

    process = ctx.Process(target=crash)
    process.start()
    wait(process)
    assert process.exitcode == 76
    assert len(list(life.data.iterdir())) == 1
    assert life.tick()["state"] == "EXPIRED"
    assert not list(life.data.iterdir())


@pytest.mark.parametrize("damage", ["schema", "audit", "ledger", "lock"])
def test_durable_metadata_corruption_denied(tmp_path, damage):
    life, token = fixture(tmp_path)
    life.put(token, {"protected": b"preserved on uncertainty"})
    if damage in {"schema", "audit"}:
        with sqlite3.connect(life.control / "ledger.sqlite") as db:
            db.execute(
                "DROP TRIGGER terminal"
                if damage == "schema"
                else "UPDATE audit SET sha='tampered' WHERE sequence=1"
            )
    else:
        path = life.control / ("lock" if damage == "lock" else "ledger.sqlite")
        body = path.read_bytes()
        path.rename(path.with_suffix(".old"))
        path.write_bytes(body)
        path.chmod(0o600)
    with pytest.raises(ValueError):
        life.tick()
    assert (life.data / "protected").read_bytes() == b"preserved on uncertainty"


def test_watchdog_permission_failure(tmp_path):
    life, _ = fixture(tmp_path)
    config = tmp_path / "watchdog-config.json"
    config.write_bytes(canonical(saved(life)))
    status = tmp_path / "unwritable-status"
    status.mkdir(mode=0o500)
    result = subprocess.run(
        [sys.executable, "-m", "tools.phase2_custodian_watchdog", str(config), str(status)],
        env=dict(os.environ, RV_CUSTODIAN_CONFIG_SHA256=digest(config.read_bytes())),
        capture_output=True,
        timeout=10,
    )
    assert result.returncode != 0 and b"PermissionError" in result.stderr
    record(
        "watchdog-permission-failure",
        dict(
            exit_code=result.returncode,
            stdout=result.stdout.decode(),
            stderr=result.stderr.decode(),
        ),
    )
    assert not (status / "heartbeat.json").exists()
    status.chmod(0o700)


def test_two_cleanup_processes(tmp_path):
    life, token = fixture(tmp_path)
    life.put(token, {"source": b"no bytes remain after expiry"})
    life.transition(token, "WITHDRAWN")
    ctx = multiprocessing.get_context("fork")

    def cleanup():
        try:
            reopen(saved(life)).tick()
        except BlockingIOError:
            pass  # Explicit busy outcome; not reported as completed.

    workers = [ctx.Process(target=cleanup) for _ in range(2)]
    for process in workers:
        process.start()
    for process in workers:
        wait(process)
        assert process.exitcode == 0
    assert life.tick()["state"] == "EXPIRED"
    assert not list(life.data.iterdir())


def test_real_v2_contract_wrappers_with_synthetic_source_only(case, tmp_path):
    from repovox.evaluation.v2 import serialize

    root, scope, proofs, ref, pred = case
    life, token = fixture(tmp_path, tenant=scope.tenant_id)
    store = CustodianStore(
        life, token, lambda plan: True, lambda plan: True, synthetic_fixture=True
    )
    for body in [*proofs.values(), serialize(scope), serialize(pred), serialize(ref)]:
        store.write(scope.tenant_id, body)
    records = []
    for payload in [
        ref.blind_source_sha256,
        digest(serialize(pred)),
        ref.blind_source_sha256,
        ref.provenance.response_capture_sha256,
        digest(serialize(ref)),
    ]:
        records.append(
            store.append_event(
                records,
                tenant_id=scope.tenant_id,
                session_id="synthetic-session",
                scope_sha256=ref.scope_sha256,
                engineering_commit=pred.engineering_commit,
                scorer_commit="e" * 40,
                payload_sha256=payload,
                trusted_context="synthetic tests only",
                identity_basis="synthetic_fixture",
            )
        )
    for count in range(1, 5):
        with pytest.raises(ValueError, match="pre_reveal"):
            store.prereveal(records[:count], records[count - 1][1])
    observed, event = store.reveal(records, records[-1][1], root, proofs)
    assert observed == pred
    records.append(event)
    body, sha, event = store.compare_sealed(records, records[-1][1], root, proofs)
    assert store.read(scope.tenant_id, sha) == body
    records.append(event)
    assert len(store.validate_retained_chain(records)) == 7

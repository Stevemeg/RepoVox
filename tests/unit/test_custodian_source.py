"""RV-09-01: real restricted files/process kills; synthetic bytes and keys only."""

import ast
import io
import multiprocessing
import os
import signal
import stat
import tempfile
import time
from pathlib import Path

import pytest

pytest.importorskip("fcntl")

import resource

from repovox.evaluation import v2
from test_custodian_lifecycle import available_tick, fixture, record
from test_custodian_review import advance, grant_for
from test_custodian_review import review as review
from test_evaluation_v2 import case as case

from tools import phase2_custodian_review as review_module
from tools import phase2_custodian_source as source_module
from tools.phase2_custodian_lifecycle import canonical, digest
from tools.phase2_custodian_source import CustodySource

pytestmark = pytest.mark.skipif(os.geteuid() != 10002, reason="restricted custodian UID required")


def inventory(root):
    return {p.name: digest(p.read_bytes()) for p in root.iterdir()}


def test_unchanged_validators_read_actual_registered_bytes(review, case):
    original, scope, proofs, ref, _ = case
    view, retained_proofs = review.session._source()
    before = inventory(review.life.data)
    assert v2.source_bytes(view, scope, retained_proofs) == v2.source_bytes(original, scope, proofs)
    node = view / scope.files[0].path
    actual = (review.life.data / (scope.tenant_id + "-" + scope.files[0].file_sha256)).lstat()
    observed = node.stat()
    for key in ["st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size"]:
        assert getattr(observed, key) == getattr(actual, key)
    assert actual.st_uid == actual.st_gid == 10002 and actual.st_nlink == 1
    assert stat.S_IMODE(actual.st_mode) == 0o600
    with node.open("rb") as stream:
        assert not stream.writable()
        assert digest(stream.read()) == scope.files[0].file_sha256
        with pytest.raises(io.UnsupportedOperation):
            stream.write(b"cannot change original source")
    assert inventory(review.life.data) == before
    assert resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)
    for path in ["../escape.py", "/tmp/escape.py", "excluded.py"]:
        with pytest.raises(ValueError, match="source_path_outside_scope"):
            view / path
    with pytest.raises(ValueError, match="custody_source_read_only"):
        node.open("wb")
    assert not hasattr(node, "write_bytes")


@pytest.mark.parametrize("field", ["tenant", "namespace", "attempt", "generation"])
def test_source_token_substitution_rejected(review, field):
    token = dict(review.token)
    token[field] = 999 if field == "generation" else "wrong"
    with pytest.raises(ValueError, match="authorization_binding|stale_authorization"):
        CustodySource(
            review.life,
            token,
            review.session._read(review.session.binding["scope_sha256"]),
            review.session.binding["scope_sha256"],
        )


def test_scope_commitment_and_nested_original_paths(review):
    body = review.session._read(review.session.binding["scope_sha256"])
    with pytest.raises(ValueError, match="v2_commitment_mismatch"):
        CustodySource(review.life, review.token, body, "0" * 64)
    scope = v2.decode(body, digest(body), v2.Scope).model_copy(deep=True)
    for file in scope.files:
        file.path = "nested/" + file.path
        for window in file.windows:
            window.path = file.path
    scope = v2.Scope.model_validate(scope.model_dump())
    nested = v2.serialize(scope)
    review.life.put(review.token, {scope.tenant_id + "-" + digest(nested): nested})
    before = inventory(review.life.data)
    view = CustodySource(review.life, review.token, nested, digest(nested))
    _, proofs = review.session._source()
    bodies = v2.source_bytes(view, scope, proofs)
    assert set(bodies) == {f.path for f in scope.files}
    assert all(digest(bodies[f.path]) == f.file_sha256 for f in scope.files)
    assert not (review.life.data / "nested").exists()
    assert inventory(review.life.data) == before


@pytest.mark.parametrize("attack", ["hash", "mode", "symlink", "hardlink"])
def test_actual_source_substitution_rejected(review, tmp_path, attack):
    view, proofs = review.session._source()
    file = view.scope.files[0]
    target = review.life.data / (view.tenant + "-" + file.file_sha256)
    sentinel = tmp_path / "unrelated-sentinel"
    sentinel.write_bytes(b"synthetic unrelated bytes")
    sentinel.chmod(0o600)
    if attack == "hash":
        target.write_bytes(b"synthetic forged source")
        reason = "registered_evidence_corrupt"
    elif attack == "mode":
        target.chmod(0o644)
        reason = "custody_mode_or_owner"
    else:
        target.unlink()
        if attack == "symlink":
            target.symlink_to(sentinel)
            reason = "v2_source_containment"
        else:
            os.link(sentinel, target)
            reason = "custody_file_type_or_hardlink"
    with pytest.raises(ValueError, match=reason):
        v2.source_bytes(view, view.scope, proofs)
    assert sentinel.read_bytes() == b"synthetic unrelated bytes"


def test_default_temp_is_never_used_and_capture_needs_no_source_view(review, tmp_path, monkeypatch):
    default = tmp_path / "forbidden-default-temp"
    default.mkdir(mode=0o700)
    sentinel = default / "sentinel"
    sentinel.write_bytes(b"unrelated synthetic sentinel")
    before = inventory(default)
    monkeypatch.setenv("TMPDIR", str(default))
    monkeypatch.setattr(tempfile, "tempdir", str(default))

    def forbidden(*args, **kwargs):
        raise AssertionError("unmanaged temporary source export")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", forbidden)
    monkeypatch.setattr(tempfile, "mkdtemp", forbidden)
    original = review.session._source
    monkeypatch.setattr(review.session, "_source", forbidden)
    advance(review, 4)  # Handoff and exact raw-response capture need no source reconstruction.
    monkeypatch.setattr(review.session, "_source", original)
    advance_remaining = ["seal_reference", "reveal", "compare", "close"]
    for operation in advance_remaining:
        payload = {
            "seal_reference": v2.serialize(review.ref),
            "reveal": v2.serialize(review.pred),
            "compare": v2.serialize(review.ref),
            "close": review.session.records()[-1][0],
        }[operation]
        signed, approval = grant_for(review.session, review.key, operation, payload)
        review.session.perform(signed, approval, payload)
    assert inventory(default) == before
    assert available_tick(review.life)["state"] == "SEALED"
    record("rv09-no-default-temp", dict(before=before, after=inventory(default), source_copies=0))


@pytest.mark.parametrize(
    "phase", ["before_view", "source_read", "reference_validation", "before_commit", "cleanup"]
)
def test_sigkill_leaves_no_untracked_source_copy(review, tmp_path, phase):
    advance(review, 4)
    default = tmp_path / "default-temp-kill"
    default.mkdir(mode=0o700)
    (default / "sentinel").write_bytes(b"unrelated synthetic sentinel")
    unrelated = inventory(default)
    before = inventory(review.life.data)
    receipt = (review.life.control / "identity.json").read_bytes()
    deadline = review.life.plan["expires_at"]
    if phase == "cleanup":
        review.process.kill()
        review.process.wait(5)
        review.life.transition(review.token, "WITHDRAWN")
    signed, approval = (
        grant_for(review.session, review.key, "seal_reference", v2.serialize(review.ref))
        if phase != "cleanup"
        else (b"", b"")
    )

    def killed():
        tempfile.tempdir = str(default)
        os.environ["TMPDIR"] = str(default)

        def stop(*args, **kwargs):
            os.kill(os.getpid(), signal.SIGKILL)

        if phase == "before_view":
            review_module.CustodySource = stop
        elif phase == "source_read":
            original = source_module._CustodyFile.open

            def during_read(self, mode):
                stream = original(self, mode)
                stream.read(1)
                stop()

            source_module._CustodyFile.open = during_read
        elif phase == "reference_validation":
            original = v2.validate_citation

            def during_validation(*args):
                original(*args)
                stop()

            v2.validate_citation = during_validation
        elif phase == "before_commit":
            review_module.screen_bytes = stop
        else:
            original = os.unlink
            source_name = (
                review.life.plan["tenant"] + "-" + review.ref.assertions[0].fact.subject.file_sha256
            )

            def during_cleanup(*args, **kwargs):
                original(*args, **kwargs)
                if args[0] == source_name:
                    stop()

            os.unlink = during_cleanup
            available_tick(review.life)
        review.session.perform(signed, approval, v2.serialize(review.ref))

    child = multiprocessing.get_context("fork").Process(target=killed)
    child.start()
    child.join(5)
    assert child.exitcode == -signal.SIGKILL
    after = inventory(review.life.data)
    assert inventory(default) == unrelated
    if phase == "cleanup":
        assert after.keys() < before.keys()
        assert available_tick(review.life)["state"] == "EXPIRED"
        assert not list(review.life.data.iterdir())
    else:
        assert after == before
        assert available_tick(review.life)["state"] == "ACTIVE"
        assert len(review.session.records()) == 4
    assert review.life.plan["expires_at"] == deadline
    assert (review.life.control / "identity.json").read_bytes() == receipt
    record(
        "rv09-forced-termination",
        dict(
            phase=phase,
            exit_code=child.exitcode,
            before=before,
            after=after,
            unmanaged_before=unrelated,
            unmanaged_after=inventory(default),
            deadline=deadline,
            receipt_sha256=digest(receipt),
            protected_source_exports=0,
        ),
    )


def test_source_view_cannot_read_after_natural_expiry(case, tmp_path):
    original, scope, _, _, _ = case
    life, token = fixture(
        tmp_path, seconds=1, tenant=scope.tenant_id, version="custodian-lifecycle-1.1"
    )
    body = v2.serialize(scope)
    entries = {scope.tenant_id + "-" + digest(body): body}
    entries.update(
        {
            scope.tenant_id + "-" + f.file_sha256: (original / f.path).read_bytes()
            for f in scope.files
        }
    )
    life.put(token, entries)
    view = CustodySource(life, token, body, digest(body))
    receipt = canonical(life.receipt)
    deadline = life.plan["expires_at"]
    time.sleep(1.05)
    with pytest.raises(ValueError, match="stale_authorization"):
        (view / scope.files[0].path).open("rb")
    assert available_tick(life)["state"] == "EXPIRED"
    assert not list(life.data.iterdir()) and life.plan["expires_at"] == deadline
    assert canonical(life.receipt) == receipt


def test_review_source_modules_have_no_persistent_export_primitives():
    for module in [review_module, source_module]:
        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names]
                assert not any(n in {"tempfile", "shutil"} for n in names)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {
                    "write_bytes",
                    "write_text",
                    "mkdir",
                    "mkdtemp",
                    "TemporaryDirectory",
                    "NamedTemporaryFile",
                    "TemporaryFile",
                    "copyfile",
                    "mkstemp",
                    "memfd_create",
                }


def test_old_temp_pattern_negative_control_leaves_bytes_after_sigkill(tmp_path):
    """Deliberately reproduce ONLY the former pattern with disposable synthetic data."""
    default = tmp_path / "old-pattern-control"
    default.mkdir(mode=0o700)
    ctx = multiprocessing.get_context("fork")
    receiver, sender = ctx.Pipe(duplex=False)
    body = b"SYNTHETIC negative control; never real source"

    def old_pattern():
        with tempfile.TemporaryDirectory(prefix="rv-review-", dir=default) as directory:
            path = Path(directory) / "source.py"
            path.write_bytes(body)
            path.chmod(0o600)
            sender.send(directory)
            os.kill(os.getpid(), signal.SIGKILL)

    child = ctx.Process(target=old_pattern)
    child.start()
    assert receiver.poll(5)
    directory = Path(receiver.recv())
    child.join(5)
    assert child.exitcode == -signal.SIGKILL
    assert directory.parent == default and not directory.is_symlink()
    assert list(default.iterdir()) == [directory]
    assert inventory(directory) == {"source.py": digest(body)}
    path = directory / "source.py"
    value = path.lstat()
    assert stat.S_ISREG(value.st_mode) and value.st_nlink == 1
    assert value.st_uid == value.st_gid == 10002 and stat.S_IMODE(value.st_mode) == 0o600
    record(
        "rv09-old-pattern-negative-control",
        dict(
            exit_code=child.exitcode,
            expected_unmanaged_residue={"source.py": digest(body)},
            synthetic_only=True,
        ),
    )
    # Exact positively identified disposable target only; no recursive/fuzzy cleanup.
    path.unlink()
    directory.rmdir()
    assert not list(default.iterdir())

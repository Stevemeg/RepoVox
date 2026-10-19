"""Offline growing evidence storage. POSIX local filesystems only; no service mounts.

Lock order: namespace flock, SQLite BEGIN IMMEDIATE. No network callback or second
namespace lock is acquired while holding either. All protected bytes are in data/;
the durable ledger contains only opaque bindings, lengths and commitments.
"""

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

VERSION = "custodian-lifecycle-1.0"
REVIEW_VERSION = "custodian-lifecycle-1.1"
LIMIT = 50_000_000
STATES = {"CREATED", "ACTIVE", "SEALED", "INVALIDATED", "WITHDRAWN", "EXPIRING", "EXPIRED"}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def stamp(value):
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None and result.utcoffset().total_seconds() == 0, "utc_required")
    return result.timestamp()


def strict(body):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_metadata_key")
            result[key] = value
        return result

    return json.loads(body, object_pairs_hook=pairs)


def identity():
    require(os.getuid() == os.geteuid() == 10002, "custodian_uid")
    require(
        os.getgid() == os.getegid() == 10002 and set(os.getgroups()) <= {10002}, "custodian_gid"
    )
    fields = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    require(fields["NoNewPrivs"].strip() == "1", "custodian_privileges")
    require(
        all(int(fields[k], 16) == 0 for k in ["CapEff", "CapPrm", "CapInh", "CapBnd", "CapAmb"]),
        "custodian_capabilities",
    )


def info(path, directory=False):
    value = path.lstat()
    require((stat.S_ISDIR if directory else stat.S_ISREG)(value.st_mode), "custody_file_type")
    require(value.st_uid == value.st_gid == 10002, "custody_owner")
    require(stat.S_IMODE(value.st_mode) == (0o700 if directory else 0o600), "custody_mode")
    require(directory or value.st_nlink == 1, "custody_hardlink")
    return [value.st_dev, value.st_ino]


def ancestry(path):
    require(path.is_absolute(), "absolute_custody_path_required")
    require(all(not p.is_symlink() for p in [path, *path.parents]), "custody_symlink")
    require(not any((p / ".git").exists() for p in [path, *path.parents]), "custody_overlaps_git")


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def exclusive(path, body):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(path.parent)


def validate_plan(plan):
    require(
        set(plan)
        == {
            "version",
            "namespace",
            "tenant",
            "attempt",
            "manifest_sha256",
            "created_at",
            "expires_at",
            "authorization_expires_at",
            "authorization_sha256",
        },
        "lifecycle_plan_fields",
    )
    require(plan["version"] in {VERSION, REVIEW_VERSION}, "lifecycle_version")
    for key in ["namespace", "tenant"]:
        require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", plan[key]), "lifecycle_binding")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", plan["attempt"]), "lifecycle_attempt")
    for key in ["manifest_sha256", "authorization_sha256"]:
        require(re.fullmatch(r"[a-f0-9]{64}", plan[key]), "lifecycle_commitment")
    created, expires, auth = [
        stamp(plan[k]) for k in ["created_at", "expires_at", "authorization_expires_at"]
    ]
    require(
        0 < expires - created <= 30 * 86400 and created < auth <= expires,
        "immutable_retention_ceiling",
    )


def schema_hash(db):
    return digest(
        canonical(
            [
                list(r)
                for r in db.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
                )
            ]
        )
    )


SCHEMA = """
CREATE TABLE meta(body BLOB NOT NULL);
CREATE TRIGGER meta_update BEFORE UPDATE ON meta BEGIN SELECT RAISE(ABORT,'immutable_plan'); END;
CREATE TRIGGER meta_delete BEFORE DELETE ON meta BEGIN SELECT RAISE(ABORT,'immutable_plan'); END;
CREATE TRIGGER meta_insert BEFORE INSERT ON meta WHEN EXISTS(SELECT 1 FROM meta)
BEGIN SELECT RAISE(ABORT,'immutable_plan'); END;
CREATE TABLE lifecycle(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL,
 generation INTEGER NOT NULL,last_clock REAL NOT NULL,reason TEXT NOT NULL);
CREATE TRIGGER terminal BEFORE UPDATE ON lifecycle WHEN
 OLD.state='EXPIRED' OR NEW.generation<OLD.generation OR
 NOT (NEW.state=OLD.state OR (OLD.state='CREATED' AND
 NEW.state IN ('ACTIVE','INVALIDATED','WITHDRAWN','EXPIRING')) OR
 (OLD.state='ACTIVE' AND NEW.state IN ('SEALED','INVALIDATED','WITHDRAWN','EXPIRING')) OR
 (OLD.state='SEALED' AND NEW.state IN ('INVALIDATED','WITHDRAWN','EXPIRING')) OR
 (OLD.state IN ('INVALIDATED','WITHDRAWN') AND NEW.state='EXPIRING') OR
 (OLD.state='EXPIRING' AND NEW.state='EXPIRED'))
 BEGIN SELECT RAISE(ABORT,'irreversible_lifecycle'); END;
CREATE TABLE files(name TEXT PRIMARY KEY,sha TEXT NOT NULL,size INTEGER NOT NULL,
 batch TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('INTENT','COMMITTED','DELETED')));
CREATE TABLE events(session TEXT NOT NULL,sequence INTEGER NOT NULL,sha TEXT NOT NULL,
 PRIMARY KEY(session,sequence));
CREATE TABLE audit(sequence INTEGER PRIMARY KEY,body BLOB NOT NULL,sha TEXT NOT NULL);
"""

REVIEW_SCHEMA = (
    SCHEMA
    + """
CREATE TABLE batches(batch TEXT PRIMARY KEY,deadline REAL NOT NULL,seal INTEGER NOT NULL);
"""
)


class Lifecycle:
    def __init__(self, root, plan, receipt):
        identity()
        validate_plan(plan)
        self.root, self.plan, self.receipt = Path(root), plan, receipt
        self.data, self.control = self.root / "data", self.root / "control"
        self.plan_sha = digest(canonical(plan))
        require(receipt["plan_sha256"] == self.plan_sha, "lifecycle_plan_changed")
        self._paths()

    @classmethod
    def create(cls, root, plan):
        """Initializer must already have provisioned the empty parent as 10002:0700."""
        identity()
        validate_plan(plan)
        os.umask(0o077)
        root = Path(root)
        ancestry(root.parent)
        info(root.parent, True)
        require(
            stamp(plan["created_at"]) <= time.time() < stamp(plan["authorization_expires_at"]),
            "creation_clock",
        )
        root.mkdir(mode=0o700)  # Exclusive namespace; no exist_ok/recovery fallback.
        for name in ["control", "data"]:
            (root / name).mkdir(mode=0o700)
        exclusive(root / "control" / "lock", b"")
        exclusive(root / "control" / "watchdog.lock", b"")
        connection = sqlite3.connect(root / "control" / "ledger.sqlite")
        try:
            connection.execute("PRAGMA synchronous=EXTRA")
            require(connection.execute("PRAGMA synchronous").fetchone()[0] == 3, "ledger_sync_mode")
            connection.executescript(REVIEW_SCHEMA if plan["version"] == REVIEW_VERSION else SCHEMA)
            connection.execute("INSERT INTO meta VALUES (?)", (canonical(plan),))
            connection.execute(
                "INSERT INTO lifecycle VALUES (1,'CREATED',1,?,'created')", (time.time(),)
            )
            connection.commit()
        finally:
            connection.close()
        info(root / "control" / "ledger.sqlite")
        with sqlite3.connect(root / "control" / "ledger.sqlite") as check:
            schema = schema_hash(check)
        receipt = {
            "plan_sha256": digest(canonical(plan)),
            "paths": {n: info(root / n, True) for n in ["control", "data"]},
            "root": info(root, True),
            "lock": info(root / "control" / "lock"),
            "watchdog_lock": info(root / "control" / "watchdog.lock"),
            "ledger": info(root / "control" / "ledger.sqlite"),
            "schema_sha256": schema,
        }
        exclusive(root / "control" / "identity.json", canonical(receipt))
        sync_dir(root / "control")
        sync_dir(root)
        sync_dir(root.parent)
        return receipt

    def _paths(self):
        ancestry(self.root)
        require(info(self.root, True) == self.receipt["root"], "namespace_inode_changed")
        require(set(os.listdir(self.root)) == {"control", "data"}, "unexpected_namespace_entry")
        for name in ["control", "data"]:
            require(
                info(self.root / name, True) == self.receipt["paths"][name],
                "directory_inode_changed",
            )
        require(
            set(os.listdir(self.control))
            <= {"identity.json", "lock", "watchdog.lock", "ledger.sqlite", "ledger.sqlite-journal"},
            "unexpected_control_entry",
        )
        for name in os.listdir(self.control):
            try:
                info(self.control / name)
            except FileNotFoundError:
                require(name == "ledger.sqlite-journal", "control_entry_disappeared")
        require((self.control / "ledger.sqlite").stat().st_size <= 16_000_000, "ledger_size_limit")
        require(
            strict((self.control / "identity.json").read_bytes()) == self.receipt,
            "namespace_receipt_changed",
        )
        require(
            info(self.control / "lock") == self.receipt["lock"]
            and info(self.control / "watchdog.lock") == self.receipt["watchdog_lock"]
            and info(self.control / "ledger.sqlite") == self.receipt["ledger"],
            "control_inode_changed",
        )

    @contextmanager
    def watchdog_lock(self):
        """Lifetime singleton lock precedes namespace lock; writers never take it."""
        self._paths()
        fd = os.open(self.control / "watchdog.lock", os.O_RDWR | os.O_NOFOLLOW)
        try:
            require(
                [os.fstat(fd).st_dev, os.fstat(fd).st_ino] == self.receipt["watchdog_lock"],
                "watchdog_lock_changed",
            )
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    @contextmanager
    def locked(self, wait_seconds=1.0):
        identity()
        self._paths()
        fd = os.open(self.control / "lock", os.O_RDWR | os.O_NOFOLLOW)
        try:
            require(
                [os.fstat(fd).st_dev, os.fstat(fd).st_ino] == info(self.control / "lock"),
                "lock_replaced",
            )
            until = time.monotonic() + wait_seconds
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= until:
                        raise
                    time.sleep(min(0.01, max(0, until - time.monotonic())))
            self._paths()
            self._df = os.open(self.data, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            require(
                [os.fstat(self._df).st_dev, os.fstat(self._df).st_ino]
                == self.receipt["paths"]["data"],
                "directory_inode_changed",
            )
            db = sqlite3.connect(self.control / "ledger.sqlite", timeout=0, isolation_level=None)
            db.row_factory = sqlite3.Row
            try:
                db.execute("PRAGMA synchronous=EXTRA")
                require(db.execute("PRAGMA synchronous").fetchone()[0] == 3, "ledger_sync_mode")
                require(
                    db.execute("PRAGMA journal_mode").fetchone()[0] == "delete",
                    "ledger_journal_mode",
                )
                require(db.execute("PRAGMA quick_check").fetchone()[0] == "ok", "ledger_corrupt")
                require(schema_hash(db) == self.receipt["schema_sha256"], "ledger_schema_changed")
                require(
                    bytes(db.execute("SELECT body FROM meta").fetchone()[0])
                    == canonical(self.plan),
                    "immutable_plan_changed",
                )
                previous = None
                for sequence, record in enumerate(
                    db.execute("SELECT * FROM audit ORDER BY sequence"), 1
                ):
                    body = bytes(record["body"])
                    value = strict(body)
                    require(
                        record["sequence"] == value["sequence"] == sequence
                        and value["previous"] == previous
                        and value["plan_sha256"] == self.plan_sha
                        and digest(body) == record["sha"],
                        "audit_chain_corrupt",
                    )
                    previous = record["sha"]
                yield db
            finally:
                db.close()
                os.close(self._df)
        finally:
            os.close(fd)

    def _audit(self, db, kind):
        last = db.execute(
            "SELECT sequence,sha FROM audit ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        require(last is None or last[0] < 15000, "audit_count_limit")
        body = canonical(
            {
                "sequence": last[0] + 1 if last else 1,
                "previous": last[1] if last else None,
                "kind": kind,
                "plan_sha256": self.plan_sha,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        db.execute(
            "INSERT INTO audit VALUES (?,?,?)", (last[0] + 1 if last else 1, body, digest(body))
        )

    def _state(self, db):
        row = db.execute("SELECT * FROM lifecycle").fetchone()
        require(row["state"] in STATES, "unknown_lifecycle_state")
        now = time.time()
        if row["state"] != "EXPIRED":
            require(now >= row["last_clock"], "wall_clock_regressed")
            db.execute("BEGIN IMMEDIATE")
            if now >= stamp(self.plan["expires_at"]) and row["state"] != "EXPIRING":
                db.execute(
                    "UPDATE lifecycle SET state='EXPIRING',generation=generation+1,"
                    "last_clock=?,reason='deadline'",
                    (now,),
                )
                self._audit(db, "expiry_admission_closed")
            else:
                db.execute("UPDATE lifecycle SET last_clock=?", (now,))
            db.execute("COMMIT")
        return db.execute("SELECT * FROM lifecycle").fetchone()

    def _authorized(self, db, token, writing=True, created=False, cleanup=False):
        row = self._state(db)
        require(
            set(token) == {"tenant", "namespace", "attempt", "generation", "secret"},
            "authorization_fields",
        )
        require(
            all(token[k] == self.plan[k] for k in ["tenant", "namespace", "attempt"]),
            "authorization_binding",
        )
        require(
            token["generation"] == row["generation"]
            and digest(token["secret"].encode()) == self.plan["authorization_sha256"],
            "stale_authorization",
        )
        require(
            cleanup or time.time() < stamp(self.plan["authorization_expires_at"]),
            "authorization_expired",
        )
        require(
            row["state"]
            in (
                {"CREATED", "ACTIVE", "SEALED"}
                if created
                else ({"ACTIVE"} if writing else {"ACTIVE", "SEALED"})
            ),
            "lifecycle_not_executable",
        )

    def _file(self, name, maximum=LIMIT):
        require(
            re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", name) and name not in {".", ".."},
            "evidence_path",
        )
        before = self._file_info(name)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._df)
        try:
            st = os.fstat(fd)
            require(
                before == [st.st_dev, st.st_ino] and st.st_size <= maximum, "evidence_inode_or_size"
            )
            with os.fdopen(fd, "rb", closefd=False) as stream:
                body = stream.read(maximum + 1)
            require(len(body) == st.st_size and self._file_info(name) == before, "evidence_changed")
            return body
        finally:
            os.close(fd)

    def _file_info(self, name):
        value = os.stat(name, dir_fd=self._df, follow_symlinks=False)
        require(
            stat.S_ISREG(value.st_mode) and value.st_nlink == 1, "custody_file_type_or_hardlink"
        )
        require(
            value.st_uid == value.st_gid == 10002 and stat.S_IMODE(value.st_mode) == 0o600,
            "custody_mode_or_owner",
        )
        require(value.st_dev == self.receipt["paths"]["data"][0], "custody_device")
        return [value.st_dev, value.st_ino]

    def _inventory(self, db, deleting=False):
        rows = {r["name"]: r for r in db.execute("SELECT * FROM files")}
        found = set(os.listdir(self._df))
        require(found <= rows.keys(), "unregistered_evidence")
        for name, row in rows.items():
            if name not in found:
                require(
                    deleting or row["status"] in {"INTENT", "DELETED"},
                    "registered_evidence_missing",
                )
                continue
            require(row["status"] != "DELETED", "deleted_evidence_returned")
            body = self._file(name)
            if row["status"] == "COMMITTED":
                require(
                    digest(body) == row["sha"] and len(body) == row["size"],
                    "registered_evidence_corrupt",
                )
            else:
                require(len(body) <= row["size"], "intent_size_changed")
        return rows, found

    def _recover(self, db):
        rows, found = self._inventory(db)
        intents = [r for r in rows.values() if r["status"] == "INTENT"]
        if not intents:
            return
        complete = all(
            r["name"] in found
            and digest(self._file(r["name"])) == r["sha"]
            and len(self._file(r["name"])) == r["size"]
            for r in intents
        )
        seals = False
        deadlines = []
        if self.plan["version"] == REVIEW_VERSION:
            for batch in {r["batch"] for r in intents}:
                policy = db.execute("SELECT * FROM batches WHERE batch=?", (batch,)).fetchone()
                if policy:
                    complete = complete and time.time() < policy["deadline"]
                    deadlines.append(policy["deadline"])
                    seals = seals or bool(policy["seal"])
        if complete:
            for entry in intents:
                fd = os.open(entry["name"], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self._df)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            os.fsync(self._df)
        complete = complete and all(time.time() < deadline for deadline in deadlines)
        db.execute("BEGIN IMMEDIATE")
        if complete:
            db.execute("UPDATE files SET status='COMMITTED' WHERE status='INTENT'")
            if seals:
                db.execute("UPDATE lifecycle SET state='SEALED',reason='recovered_close'")
            self._audit(db, "recovered_committed_bytes")
        else:
            db.execute(
                "UPDATE lifecycle SET state='INVALIDATED',generation=generation+1,"
                "reason='incomplete_write'"
            )
            self._audit(db, "incomplete_write_invalidated")
        db.execute("COMMIT")

    def activate(self, token, retention_ready):
        require(
            isinstance(retention_ready, dict)
            and retention_ready["namespace"] == self.plan["namespace"]
            and retention_ready["plan_sha256"] == self.plan_sha
            and retention_ready["runtime_verified"] is True
            and retention_ready["progress"][1] > retention_ready["progress"][0]
            and 0 <= time.time() - stamp(retention_ready["observed_at"]) <= 3,
            "retention_not_ready",
        )
        with self.locked() as db:
            state = self._state(db)
            require(state["state"] == "CREATED", "activation_not_created")
            require(time.time() - stamp(retention_ready["observed_at"]) <= 3, "retention_not_ready")
            # Authorization is checked after switching within the same locked operation.
            require(
                token["tenant"] == self.plan["tenant"]
                and token["namespace"] == self.plan["namespace"]
                and token["attempt"] == self.plan["attempt"]
                and token["generation"] == 1
                and digest(token["secret"].encode()) == self.plan["authorization_sha256"]
                and time.time() < stamp(self.plan["authorization_expires_at"]),
                "activation_authorization",
            )
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE lifecycle SET state='ACTIVE'")
            self._audit(db, "activated")
            db.execute("COMMIT")

    def put(self, token, entries, event=None, *, operation_expires_at=None, seal=False):
        """All entries form one durable intent; no body is complete until the batch commits."""
        require(entries and len(entries) <= 8, "write_batch_limit")
        for name, body in entries.items():
            require(isinstance(body, bytes) and len(body) <= LIMIT, "evidence_size")
            require(
                re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", name) and name not in {".", ".."},
                "evidence_path",
            )
        expected = {n: {"sha": digest(b), "size": len(b)} for n, b in entries.items()}
        deadline = stamp(operation_expires_at) if operation_expires_at else None
        require(not seal or deadline is not None, "close_deadline_required")
        if deadline is not None:
            require(self.plan["version"] == REVIEW_VERSION, "review_lifecycle_required")
            require(
                deadline <= stamp(self.plan["authorization_expires_at"]),
                "operation_exceeds_custody_authorization",
            )
        with self.locked() as db:
            self._authorized(db, token)
            require(deadline is None or time.time() < deadline, "operation_authorization_expired")
            self._recover(db)
            self._authorized(db, token)
            rows, _ = self._inventory(db)
            duplicates = set(entries) & rows.keys()
            if duplicates:
                require(
                    duplicates == set(entries)
                    and all(
                        rows[n]["status"] == "COMMITTED"
                        and rows[n]["sha"] == expected[n]["sha"]
                        and rows[n]["size"] == expected[n]["size"]
                        for n in entries
                    ),
                    "exclusive_commitment_conflict",
                )
                return expected
            require(
                len(rows) + len(entries) <= 5000
                and sum(r["size"] for r in rows.values()) + sum(len(b) for b in entries.values())
                <= LIMIT,
                "custody_resource_limit",
            )
            if event:
                session, sequence, sha = event
                prior = db.execute(
                    "SELECT e.sequence,e.sha FROM events e JOIN files f ON "
                    "f.name=? || '-' || e.sha AND f.status='COMMITTED' "
                    "WHERE session=? ORDER BY e.sequence",
                    (self.plan["tenant"], session),
                ).fetchall()
                require(sequence == len(prior) + 1 and sequence <= 7, "event_sequence_conflict")
            batch = digest(canonical(expected))
            db.execute("BEGIN IMMEDIATE")
            if deadline is not None:
                db.execute("INSERT INTO batches VALUES (?,?,?)", (batch, deadline, int(seal)))
            for name, e in expected.items():
                db.execute(
                    "INSERT INTO files VALUES (?,?,?,?, 'INTENT')",
                    (name, e["sha"], e["size"], batch),
                )
            if event:
                db.execute("INSERT INTO events VALUES (?,?,?)", event)
            self._audit(db, "write_intent")
            db.execute("COMMIT")  # Durable before any evidence byte.
            for name, body in entries.items():
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=self._df,
                )
                with os.fdopen(fd, "wb") as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(self._df)
                require(self._file(name) == body, "write_readback")
            self._authorized(db, token)  # Deadline can pass during a bounded write.
            require(deadline is None or time.time() < deadline, "operation_authorization_expired")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE files SET status='COMMITTED' WHERE batch=? AND status='INTENT'", (batch,)
            )
            self._audit(db, "write_committed")
            if seal:
                db.execute("UPDATE lifecycle SET state='SEALED',reason='review_closed'")
                self._audit(db, "sealed")
            db.execute("COMMIT")
            return expected

    def read(self, token, name):
        with self.locked() as db:
            self._authorized(db, token, False)
            self._recover(db)
            self._authorized(db, token, False)
            self._inventory(db)
            row = db.execute(
                "SELECT * FROM files WHERE name=? AND status='COMMITTED'", (name,)
            ).fetchone()
            require(row is not None, "evidence_not_committed")
            body = self._file(name)
            self._authorized(db, token, False)
            return body

    def transition(self, token, target):
        require(target in {"SEALED", "INVALIDATED", "WITHDRAWN"}, "invalid_transition")
        with self.locked() as db:
            row = self._state(db)
            if row["state"] == target and target in {"SEALED", "INVALIDATED", "WITHDRAWN"}:
                require(
                    token["namespace"] == self.plan["namespace"]
                    and token["tenant"] == self.plan["tenant"]
                    and token["attempt"] == self.plan["attempt"]
                    and digest(token["secret"].encode()) == self.plan["authorization_sha256"],
                    "authorization_binding",
                )
                if target == "SEALED":
                    self._authorized(db, token, False)
                return
            self._authorized(
                db, token, False, created=target != "SEALED", cleanup=target != "SEALED"
            )
            self._recover(db)
            self._authorized(
                db, token, False, created=target != "SEALED", cleanup=target != "SEALED"
            )
            self._inventory(db)
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE lifecycle SET state=?,generation=generation+?,reason=?",
                (target, int(target != "SEALED"), target),
            )
            self._audit(db, target.lower())
            db.execute("COMMIT")

    def tick(self):
        """Watchdog/recovery authority can only observe, invalidate, or erase known files."""
        with self.locked(wait_seconds=0) as db:
            row = self._state(db)
            if row["state"] in {"INVALIDATED", "WITHDRAWN"}:
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE lifecycle SET state='EXPIRING',generation=generation+1")
                self._audit(db, "early_cleanup_admitted")
                db.execute("COMMIT")
                row = db.execute("SELECT * FROM lifecycle").fetchone()
            if row["state"] not in {"EXPIRING", "EXPIRED"}:
                self._recover(db)
                self._inventory(db)
            else:
                rows, found = self._inventory(db, deleting=True)
                require(row["state"] != "EXPIRED" or not found, "evidence_after_expiry")
                for name in sorted(found):
                    # NOFOLLOW, regular mode/owner/link/hash checks precede unlink.
                    pin = self._file_info(name)
                    self._file(name)
                    require(self._file_info(name) == pin, "expiry_inode_changed")
                    os.unlink(name, dir_fd=self._df)
                    os.fsync(self._df)
                require(not os.listdir(self._df), "expiry_incomplete")
                if row["state"] != "EXPIRED":
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("UPDATE files SET status='DELETED'")
                    db.execute("UPDATE lifecycle SET state='EXPIRED'")
                    self._audit(db, "expiry_complete")
                    db.execute("COMMIT")
            row = db.execute("SELECT * FROM lifecycle").fetchone()
            return {
                "version": self.plan["version"],
                "namespace": self.plan["namespace"],
                "plan_sha256": self.plan_sha,
                "state": row["state"],
                "generation": row["generation"],
                "expires_at": self.plan["expires_at"],
                "inventory_checked": True,
                "file_count": db.execute(
                    "SELECT count(*) FROM files WHERE status='COMMITTED'"
                ).fetchone()[0],
            }

"""Independent synthetic cloud identities; no real repositories or cloud credentials."""

import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.phase2_cloud_retention_model import (
    Controller,
    Ledger,
    Manifest,
    MockAlerts,
    MockCloud,
    Refusal,
    Resource,
    canonical,
    digest,
    health,
)
from tools.phase2_cloud_verification import OfflineVerifier, ReadOnlyFixtureInventory

# Publicly labeled disposable signing material, never an owner enrollment key.
FIXTURE_SIGNER = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
VERIFIER_PRINCIPAL = "arn:aws:iam::222222222222:role/synthetic-verifier"


def fixture(tmp_path, activate=True):
    account, region, namespace, tenant = "111111111111", "us-east-1", "syntheticNs", "tenantA"

    def resource(kind, identifier, parent="", key=""):
        return Resource(
            kind,
            identifier,
            account,
            region,
            namespace,
            tenant,
            digest(("synthetic-provisioning/" + identifier).encode()),
            parent,
            key,
        )

    resources = (
        resource("compute", "i-0123456789abcdef0"),
        resource("volume", "vol-0123456789abcdef0", "i-0123456789abcdef0"),
        resource("snapshot", "snap-0123456789abcdef0", "vol-0123456789abcdef0"),
        resource("bucket", "synthetic-bucket"),
        resource("version", "opaque-version-1", "synthetic-bucket", "objects/" + "a" * 64),
        resource("version", "opaque-version-2", "synthetic-bucket", "objects/" + "a" * 64),
        resource("upload", "opaque-upload-1", "synthetic-bucket", "objects/" + "b" * 64),
    )
    manifest = Manifest(
        "syntheticOwner",
        tenant,
        "attemptA",
        namespace,
        "f" * 64,
        account,
        region,
        1000,
        2000,
        1900,
        resources,
        verifier_public_key=FIXTURE_SIGNER.public_key().public_bytes_raw().hex(),
        verifier_principal=VERIFIER_PRINCIPAL,
        cleanup_principal="arn:aws:iam::222222222222:role/synthetic-cleaner",
    )
    ledger = Ledger(tmp_path / "synthetic.sqlite", manifest, manifest.commitment, create=True)
    cloud = MockCloud(resources, account, region)
    cloud.test_directory = tmp_path.resolve()
    if activate:
        ledger.activate(1001, supervision_verified=True, inventory_verified=True)
    return manifest, ledger, cloud, Controller(ledger, cloud)


def provider_fixture(path, resources, account="111111111111", region="us-east-1"):
    """Only legacy fixture setup serializes cloud state; verifier has no shared objects."""
    from dataclasses import asdict

    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE principals(principal TEXT,credential_sha TEXT,permission TEXT);"
            "CREATE TABLE endpoint(account TEXT,region TEXT);"
            "CREATE TABLE resources(body BLOB,present INTEGER);"
        )
        db.execute(
            "INSERT INTO principals VALUES(?,?,?)",
            (VERIFIER_PRINCIPAL, digest(b"synthetic-read-only-credential"), "READ_ONLY_VERIFIER"),
        )
        db.execute("INSERT INTO endpoint VALUES(?,?)", (account, region))
        db.executemany(
            "INSERT INTO resources VALUES(?,1)", [(canonical(asdict(r)),) for r in resources]
        )
    return OfflineVerifier(
        ReadOnlyFixtureInventory(path, VERIFIER_PRINCIPAL, b"synthetic-read-only-credential"),
        FIXTURE_SIGNER,
    )


def cloud_identity(cloud, identifier):
    return next(r.identity for r in cloud.resources.values() if r.identifier == identifier)


def observer(cloud):
    return provider_fixture(
        cloud.test_directory / (uuid.uuid4().hex + ".sqlite"),
        [cloud.resources[k] for k in cloud.present],
        cloud.account,
        cloud.region,
    )


def test_vm_off_cleanup_and_independent_absence(tmp_path):
    manifest, ledger, cloud, controller = fixture(tmp_path)
    cloud.guest_running = False
    assert controller.reconcile(manifest.expires) == "VERIFYING"
    assert ledger.snapshot()[0] == "VERIFYING"  # Successful requests are not completion.
    receipt = controller.verify(2001, observer(cloud))
    assert receipt["remaining"] == 0 and not receipt["real_cloud_proof"]
    assert not cloud.present


def test_activation_required_before_write(tmp_path):
    manifest, ledger, _, _ = fixture(tmp_path, False)
    with pytest.raises(Refusal, match="execution_fenced"):
        ledger.admission(manifest.resources[1], 1, manifest.tenant, 1001)
    with pytest.raises(Refusal, match="retention_not_activated"):
        ledger.activate(1001, supervision_verified=False, inventory_verified=True)


@pytest.mark.parametrize(
    "runtime,external", [(None, 1001), (1001, None), (800, 1001), (1001, 800), (1100, 1001)]
)
def test_missing_stale_or_future_health_fences_durably(tmp_path, runtime, external):
    manifest, ledger, _, _ = fixture(tmp_path)
    assert not health(ledger, 1001, runtime, external)
    assert ledger.snapshot() == ("FENCED", 2, 0)
    assert health(ledger, 1002, 1002, 1002)  # Progress does not reactivate an attempt.
    with pytest.raises(Refusal, match="execution_fenced"):
        ledger.admission(manifest.resources[1], 1, manifest.tenant, 1002)


def test_restart_preserves_expiry_and_invalidation(tmp_path):
    manifest, ledger, cloud, _ = fixture(tmp_path)
    ledger.invalidate("WITHDRAWN")
    reopened = Ledger(ledger.path, manifest, manifest.commitment)
    assert reopened.manifest.expires == 2000 and reopened.snapshot()[0] == "FENCED"
    assert Controller(reopened, cloud).reconcile(1100) == "VERIFYING"


@pytest.mark.parametrize(
    "field,value",
    [
        ("expires", 2001),
        ("authorization_expires", 1950),
        ("tenant", "tenantB"),
        ("scope_sha256", "a" * 64),
    ],
)
def test_changed_manifest_cannot_reopen(tmp_path, field, value):
    manifest, ledger, _, _ = fixture(tmp_path)
    with pytest.raises(Refusal):
        Ledger(ledger.path, replace(manifest, **{field: value}), manifest.commitment)


def test_sql_immutable_original_registry(tmp_path):
    _, ledger, _, _ = fixture(tmp_path)
    with ledger.connect() as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable_registry"):
            db.execute("UPDATE registry SET body=?", (b"changed",))
        with pytest.raises(sqlite3.IntegrityError, match="immutable_registry"):
            db.execute("DELETE FROM registry")


@pytest.mark.parametrize(
    "field,value",
    [
        ("account", "222222222222"),
        ("region", "eu-west-1"),
        ("tenant", "tenantB"),
        ("namespace", "anotherNs"),
        ("identifier", "vol-33333333333333333"),
    ],
)
def test_resource_substitution_never_deleted(tmp_path, field, value):
    manifest, _, cloud, controller = fixture(tmp_path)
    r = manifest.resources[1]
    cloud.resources[r.identity] = replace(r, **{field: value})
    assert controller.reconcile(2000) == "OVERDUE_INCOMPLETE"
    assert cloud.calls == [] and r.identity in cloud.present


@pytest.mark.parametrize("field,value", [("account", "222222222222"), ("region", "eu-west-1")])
def test_wrong_api_endpoint_boundary(tmp_path, field, value):
    _, _, cloud, controller = fixture(tmp_path)
    setattr(cloud, field, value)
    assert controller.reconcile(2000) == "OVERDUE_INCOMPLETE"
    assert not cloud.calls


def test_unmanaged_source_copy_and_unregistered_delete_rejected(tmp_path):
    manifest, ledger, cloud, controller = fixture(tmp_path)
    unknown = replace(manifest.resources[1], identifier="vol-11111111111111111")
    cloud.resources[unknown.identity] = unknown
    cloud.present.add(unknown.identity)
    with pytest.raises(Refusal, match="unregistered_copy"):
        ledger.admission(unknown, 1, manifest.tenant, 1002)
    assert controller.reconcile(2000) == "OVERDUE_INCOMPLETE"
    assert not cloud.calls
    cloud.present.remove(unknown.identity)
    cloud.quiesce(manifest)
    with pytest.raises(Refusal, match="unregistered_delete"):
        cloud.delete(unknown, manifest)


def test_unrelated_sentinel_unchanged(tmp_path):
    manifest, _, cloud, controller = fixture(tmp_path)
    unrelated = replace(
        manifest.resources[1], identifier="vol-22222222222222222", namespace="unrelated"
    )
    cloud.resources[unrelated.identity] = unrelated
    cloud.present.add(unrelated.identity)
    assert controller.reconcile(2000) == "VERIFYING"
    controller.verify(2001, observer(cloud))
    assert cloud.present == {unrelated.identity}


def test_duplicate_cleanup_and_reconciliation_remains_enabled(tmp_path):
    _, _, cloud, controller = fixture(tmp_path)
    controller.reconcile(2000)
    controller.verify(2001, observer(cloud))
    calls = list(cloud.calls)
    assert controller.reconcile(3000) == "COMPLETE" and cloud.calls == calls
    # A resource returning after completion must not be concealed by the receipt.
    cloud.present.add(cloud_identity(cloud, "vol-0123456789abcdef0"))
    with pytest.raises(Refusal, match="post_completion_resource"):
        controller.reconcile(3001)


def test_scheduler_failure_does_not_disable_recurring_reconciliation(tmp_path):
    manifest, _, cloud, controller = fixture(tmp_path)
    # The one-shot scheduler never invokes the controller in this fixture.
    assert controller.reconcile(manifest.expires + 300) == "VERIFYING"
    assert not cloud.present


def test_provider_failure_partial_progress_and_recovery(tmp_path):
    _, ledger, cloud, controller = fixture(tmp_path)
    cloud.fail.add(cloud_identity(cloud, "vol-0123456789abcdef0"))
    assert controller.reconcile(2000) == "OVERDUE_INCOMPLETE"
    assert (
        cloud_identity(cloud, "vol-0123456789abcdef0") in cloud.present
        and cloud_identity(cloud, "i-0123456789abcdef0") not in cloud.present
    )
    assert ledger.snapshot()[0] != "COMPLETE"
    cloud.fail.clear()
    reopened = Ledger(ledger.path, ledger.manifest, ledger.expected)
    assert Controller(reopened, cloud).reconcile(2001) == "VERIFYING"


def test_crash_after_delete_before_ack_recovers_intent(tmp_path):
    _, ledger, cloud, controller = fixture(tmp_path)
    with pytest.raises(InterruptedError):
        controller.reconcile(2000, crash_after_delete=True)
    with ledger.connect() as db:
        assert db.execute("SELECT status FROM actions").fetchone()[0] == "INTENT"
    restarted = Ledger(ledger.path, ledger.manifest, ledger.expected)
    assert Controller(restarted, cloud).reconcile(2061) == "VERIFYING"
    assert len(cloud.calls) == len(ledger.manifest.resources)


def test_two_workers_and_stale_cleanup_fence(tmp_path):
    _, ledger, _, _ = fixture(tmp_path)
    barrier = Barrier(2)

    def claim(worker):
        barrier.wait()
        try:
            return ledger.claim_cleanup(worker, 2000)
        except Refusal as error:
            return str(error)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(claim, ["one", "two"]))
    assert sum(type(r) is int for r in results) == 1 and "cleanup_busy" in results
    ledger.claim_cleanup("new", 2061)
    with pytest.raises(Refusal, match="cleanup_fenced"):
        ledger.fenced_transaction("one", 2, 2062, lambda db: db.execute("SELECT 1"))


def test_cancellation_races_admission(tmp_path):
    manifest, ledger, _, _ = fixture(tmp_path)
    barrier = Barrier(2)

    def write():
        barrier.wait()
        try:
            return ledger.admission(manifest.resources[1], 1, manifest.tenant, 1002)
        except Refusal:
            return "fenced"

    def cancel():
        barrier.wait()
        ledger.invalidate("SCOPE_FAILURE")

    with ThreadPoolExecutor(2) as pool:
        writing, canceling = pool.submit(write), pool.submit(cancel)
        assert writing.result() in {1, "fenced"}
        canceling.result()
    with pytest.raises(Refusal, match="execution_fenced"):
        ledger.admission(manifest.resources[1], 1, manifest.tenant, 1003)


def test_versions_uploads_snapshots_and_attachment_order(tmp_path):
    _, _, cloud, controller = fixture(tmp_path)
    with pytest.raises(Refusal, match="writers_not_quiescent"):
        cloud.delete(controller.ledger.manifest.resources[1], controller.ledger.manifest)
    controller.reconcile(2000)
    kinds = [kind for kind, _ in cloud.calls]
    assert kinds.index("compute") < kinds.index("volume")
    assert kinds.index("upload") < kinds.index("bucket")
    assert kinds.count("version") == 2 and "snapshot" in kinds and not cloud.present


def test_inflight_writes_must_be_quiescent_before_delete(tmp_path):
    _, _, cloud, controller = fixture(tmp_path)
    cloud.quiesce_available = False
    assert controller.reconcile(2000) == "OVERDUE_INCOMPLETE"
    assert not cloud.calls
    cloud.quiesce_available = True
    assert controller.reconcile(2001) == "VERIFYING"


def test_recycle_bin_or_legal_hold_cannot_be_claimed_deleted(tmp_path):
    _, _, cloud, controller = fixture(tmp_path)
    cloud.recycled.add(cloud_identity(cloud, "snap-0123456789abcdef0"))
    assert controller.reconcile(2000) == "OVERDUE_INCOMPLETE"
    assert cloud_identity(cloud, "snap-0123456789abcdef0") in cloud.present


def test_separate_independent_verification_required(tmp_path):
    _, _, cloud, controller = fixture(tmp_path)
    controller.reconcile(2000)
    with pytest.raises(Refusal, match="separate_observer_required"):
        controller.verify(2001, cloud)
    fake_empty = MockCloud((), cloud.account, cloud.region)
    with pytest.raises(Refusal, match="separate_observer_required"):
        controller.verify(2001, fake_empty)
    reader = observer(cloud)
    reader.reader.credential = b"wrong-synthetic-credential"
    with pytest.raises(Refusal, match="verifier_provider_authentication"):
        controller.verify(2001, reader)


def test_complete_never_reopens_or_renews_authorization(tmp_path):
    manifest, ledger, cloud, controller = fixture(tmp_path)
    controller.reconcile(2000)
    controller.verify(2001, observer(cloud))
    with pytest.raises(Refusal, match="terminal_or_already_active"):
        ledger.activate(1002, supervision_verified=True, inventory_verified=True)
    with pytest.raises(Refusal, match="authorization_expired"):
        ledger.admission(manifest.resources[1], ledger.snapshot()[1], manifest.tenant, 2002)
    assert ledger.manifest.authorization_expires == 1900


def test_wrong_tenant_and_expired_execution_authorization(tmp_path):
    manifest, ledger, _, _ = fixture(tmp_path)
    with pytest.raises(Refusal, match="tenant"):
        ledger.admission(manifest.resources[1], 1, "tenantB", 1002)
    with pytest.raises(Refusal, match="authorization_expired"):
        ledger.admission(manifest.resources[1], 1, manifest.tenant, 1900)


def test_early_cleanup_and_receipts_refused(tmp_path):
    _, _, cloud, controller = fixture(tmp_path)
    with pytest.raises(Refusal, match="not_due"):
        controller.reconcile(1500)
    with pytest.raises(Refusal, match="verification_state"):
        controller.verify(1500, observer(cloud))


def test_no_owner_key_credentials_network_or_sdk_dependency():
    import inspect

    from tools import phase2_cloud_retention_model as module

    source = inspect.getsource(module)
    for forbidden in (
        "import boto",
        "import requests",
        "import socket",
        "import subprocess",
        "PRIVATE KEY",
        "load_pem_private_key",
        "lambda_handler",
    ):
        assert forbidden not in source


def test_corrupt_registry_and_audit_fail_closed(tmp_path):
    _, ledger, cloud, controller = fixture(tmp_path)
    with ledger.connect() as db:
        db.execute("UPDATE audit SET body=? WHERE seq=1", (json.dumps({"seq": 1}).encode(),))
    with pytest.raises(Refusal, match="audit_integrity"):
        controller.reconcile(2000)
    assert not cloud.calls


@pytest.mark.parametrize(
    "change",
    [
        dict(mode="REAL"),
        dict(expires=1000 + 31 * 86400),
        dict(account="*"),
        dict(region="*"),
        dict(created=True),
    ],
)
def test_manifest_boundary_negative_controls(tmp_path, change):
    manifest, _, _, _ = fixture(tmp_path)
    with pytest.raises(Refusal):
        replace(manifest, **change).validate()


def test_policy_preview_has_no_wildcard_destructive_grants():
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "docs/operations/cloud-retention-iam.example.json"
    policy = json.loads(path.read_bytes())
    assert policy["mode"] == "SYNTHETIC_PREVIEW_NOT_DEPLOYABLE"
    for statement in policy["cleanup_identity_policy_preview"]["Statement"]:
        actions, resources = statement["Action"], statement["Resource"]
        if resources == "*":
            assert all(action.startswith("ec2:Describe") for action in actions)
        else:
            assert all(
                "*" not in resource and "111111111111" in resource and ":us-east-1:" in resource
                for resource in resources
            )
        assert not any(
            action in {"ec2:StartInstances", "iam:PassRole", "ec2:RunInstances"}
            for action in actions
        )


def test_cloud_budget_preserves_unknowns_and_no_free_tier():
    from pathlib import Path

    from tools.phase2_cloud_budget import estimate

    path = Path(__file__).resolve().parents[2] / "docs/operations/cloud-retention-costs.json"
    inputs = json.loads(path.read_bytes())
    month, week = estimate(inputs, 730), estimate(inputs, 168)
    assert week["reference_subtotal_usd"] == pytest.approx(
        month["reference_subtotal_usd"] * 168 / 730
    )
    assert not month["complete_budget"] and not month["free_tier_assumed"]
    assert "contracted_24x7_incident_response" in month["unknown_costs"]
    assert "contracted_24x7_incident_response" not in month["items_usd"]
    for hours in [float("nan"), float("inf"), 0, -1, True, 731]:
        with pytest.raises(ValueError):
            estimate(inputs, hours)


def test_budget_rejects_duplicate_items_and_bad_prices():
    from tools.phase2_cloud_budget import estimate

    row = dict(name="synthetic", usd_per_unit=1, monthly_units=1)
    data = dict(mode="REFERENCE_SUBTOTAL_NOT_BUDGET_AUTHORIZATION", items=[row, row])
    with pytest.raises(ValueError, match="duplicate"):
        estimate(data, 730)
    for price in [float("nan"), float("inf"), -1, True]:
        with pytest.raises(ValueError, match="invalid"):
            estimate(dict(mode=data["mode"], items=[dict(row, usd_per_unit=price)]), 730)


def test_notification_failure_is_durable_and_does_not_disable_cleanup(tmp_path):
    manifest, ledger, cloud, controller = fixture(tmp_path)
    assert not health(ledger, 1002, None, None)
    sink = MockAlerts()
    sink.available = False
    with pytest.raises(Refusal, match="notification_unavailable"):
        ledger.deliver_incidents(sink)
    restarted = Ledger(ledger.path, manifest, manifest.commitment)
    with restarted.connect() as db:
        assert db.execute("SELECT status FROM incidents").fetchall() == [("PENDING",)]
    assert controller.reconcile(2000) == "VERIFYING" and not cloud.present
    sink.available = True
    restarted.deliver_incidents(sink)
    restarted.deliver_incidents(sink)
    assert sink.delivered == {(manifest.commitment, "HEALTH_LOST")}


def test_partial_cleanup_queues_opaque_incident(tmp_path):
    manifest, ledger, cloud, controller = fixture(tmp_path)
    cloud.fail.add("inventory")
    assert controller.reconcile(2000) == "OVERDUE_INCOMPLETE"
    sink = MockAlerts()
    ledger.deliver_incidents(sink)
    assert sink.delivered == {(manifest.commitment, "CLEANUP_INCOMPLETE")}


def test_post_completion_drift_is_durably_escalated(tmp_path):
    manifest, ledger, cloud, controller = fixture(tmp_path)
    controller.reconcile(2000)
    controller.verify(2001, observer(cloud))
    cloud.present.add(cloud_identity(cloud, "vol-0123456789abcdef0"))
    with pytest.raises(Refusal, match="post_completion_resource"):
        controller.reconcile(2002)
    sink = MockAlerts()
    ledger.deliver_incidents(sink)
    assert sink.delivered == {(manifest.commitment, "POST_COMPLETION_DRIFT")}


def test_unapproved_incident_body_is_not_persisted(tmp_path):
    _, ledger, _, _ = fixture(tmp_path)
    with pytest.raises(Refusal, match="incident_code"):
        ledger.incident("SYNTHETIC_UNTRUSTED_PAYLOAD")
    with ledger.connect() as db:
        assert not db.execute("SELECT * FROM incidents").fetchall()


def test_changed_provisioning_receipt_refused_before_deletion(tmp_path):
    manifest, _, cloud, controller = fixture(tmp_path)
    original = manifest.resources[0]
    cloud.resources[original.identity] = replace(original, provisioning_sha256="a" * 64)
    assert controller.reconcile(2000) == "OVERDUE_INCOMPLETE" and not cloud.calls


@pytest.mark.parametrize(
    "change",
    [
        dict(custodian_uid=10001),
        dict(custodian_gid=0),
        dict(capability_mask=1),
        dict(no_new_privileges=False),
    ],
)
def test_wrong_declared_custodian_profile_refused(tmp_path, change):
    manifest, _, _, _ = fixture(tmp_path)
    with pytest.raises(Refusal, match="custodian_profile"):
        replace(manifest, **change).validate()

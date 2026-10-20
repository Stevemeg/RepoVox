"""CR-01..04: offline provider fixtures, not cloud or real approval evidence."""

import base64
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_cloud_retention_model import (
    FIXTURE_SIGNER,
    fixture,
    provider_fixture,
)

from tools.phase2_cloud_handoff_policy import evaluate_copy_decision
from tools.phase2_cloud_registration import Registration
from tools.phase2_cloud_retention_model import (
    Controller,
    CreationSlot,
    Ledger,
    MockCloud,
    Refusal,
    canonical,
    digest,
)
from tools.phase2_cloud_verification import accept_observation, challenge


def dynamic_fixture(tmp_path, kind="version"):
    base, _, _, _ = fixture(tmp_path)
    slot = CreationSlot("b" * 64, kind, "synthetic-bucket", "approved/é +%2F.json", "d" * 64)
    manifest = replace(base, creation_slots=(slot,))
    ledger = Ledger(tmp_path / "dynamic.sqlite", manifest, manifest.commitment, create=True)
    ledger.activate(1001, supervision_verified=True, inventory_verified=True)
    cloud = MockCloud(manifest.resources, manifest.account, manifest.region)
    cloud.test_directory = tmp_path.resolve()
    return slot, manifest, ledger, cloud


def returned_resource(manifest, slot, identifier="Native.ID+/==%2F"):
    return replace(
        manifest.resources[-2],
        kind=slot.kind,
        identifier=identifier,
        key=slot.key,
        parent=slot.parent,
        provisioning_sha256=slot.request_sha256,
    )


def provider_created(cloud, resource):
    cloud.resources[resource.identity] = resource
    cloud.present.add(resource.identity)


@pytest.mark.parametrize(
    "kind,identifier,key",
    [
        (
            "version",
            "3sL4kqtJlcpXroDTDmJ+rmSpXd3dIbrHY+MTRCxf3vjVBH40Nr8X8gdRQBpUMLUo",
            "folder/é +%2F?file.json",
        ),
        ("version", "null", "数据/引用.json"),
        ("version", "a" * 1024, "é" * 512),
        (
            "upload",
            "EXAMPLEJZ6e0YupT2h66iePQCc9IEbYbDUy4RTpMeoSMLPRp8Z5o1u8feSRonpvnWsKKG35tI2LB9VDPiCgTy.Gq2VxQLYjrue4Nq.NBdqI-",
            "space and +/trailing.",
        ),
        ("upload", "opaque/+==%2F" * 100, "literal/../periods\r\n"),
    ],
)
def test_native_identifiers_preserved_and_deleted_exactly(tmp_path, kind, identifier, key):
    manifest, _, _, _ = fixture(tmp_path)
    resource = replace(manifest.resources[4], kind=kind, identifier=identifier, key=key)
    native = replace(manifest, resources=manifest.resources[:4] + (resource,))
    ledger = Ledger(tmp_path / "native.sqlite", native, native.commitment, create=True)
    ledger.activate(1001, supervision_verified=True, inventory_verified=True)
    cloud = MockCloud(native.resources, native.account, native.region)
    assert json.loads(native.body)["resources"][4]["identifier"] == identifier
    assert json.loads(native.body)["resources"][4]["key"] == key
    assert Controller(ledger, cloud).reconcile(2000) == "VERIFYING"
    assert (kind, resource.commitment) in cloud.calls and not cloud.present


@pytest.mark.parametrize(
    "field,value",
    [
        ("identifier", ""),
        ("identifier", "a" * 1025),
        ("identifier", "\ud800"),
        ("key", "é" * 513),
        ("key", ""),
        ("key", "\udfff"),
    ],
)
def test_invalid_utf8_or_byte_limits_rejected(tmp_path, field, value):
    manifest, _, _, _ = fixture(tmp_path)
    with pytest.raises(Refusal, match="resource_id|object_key"):
        replace(
            manifest,
            resources=manifest.resources[:4] + (replace(manifest.resources[4], **{field: value}),),
        ).validate()


@pytest.mark.parametrize(
    "left,right",
    [("a+b", "a b"), ("a%2Fb", "a/b"), ("é", "e\u0301"), ("Key", "key"), ("literal/../key", "key")],
)
def test_normalization_never_creates_authority(tmp_path, left, right):
    manifest, _, _, _ = fixture(tmp_path)
    a, b = (replace(manifest.resources[4], key=k) for k in (left, right))
    root = replace(manifest, resources=manifest.resources[:4] + (a, b))
    root.validate()
    cloud = MockCloud(root.resources, root.account, root.region)
    cloud.quiesce(root)
    cloud.delete(a, root)
    assert b.identity in cloud.present and a.identity not in cloud.present
    assert a.commitment != b.commitment


def test_native_id_scoped_by_kind_bucket_key_and_endpoint(tmp_path):
    manifest, _, _, _ = fixture(tmp_path)
    original = manifest.resources[4]
    second_bucket = replace(manifest.resources[3], identifier="another.synthetic-bucket")
    resources = manifest.resources[:4] + (
        second_bucket,
        original,
        replace(original, parent=second_bucket.identifier),
        replace(original, key="other"),
        replace(original, kind="upload"),
    )
    changed = replace(manifest, resources=resources)
    changed.validate()
    assert len(MockCloud(resources, manifest.account, manifest.region).present) == len(resources)
    with pytest.raises(Refusal, match="duplicate_resource"):
        replace(changed, resources=resources + (original,)).validate()
    for field, value in [("account", "222222222222"), ("region", "eu-west-1")]:
        foreign = replace(original, **{field: value})
        with pytest.raises(Refusal, match="resource_boundary"):
            replace(manifest, resources=manifest.resources[:4] + (foreign,)).validate()


@pytest.mark.parametrize("identifier", ["i-1234abcd", "i-0123456789abcdef0"])
def test_legacy_and_long_provider_compute_ids_are_exact(tmp_path, identifier):
    manifest, _, _, _ = fixture(tmp_path)
    compute = replace(manifest.resources[0], identifier=identifier)
    volume = replace(manifest.resources[1], parent=identifier)
    replace(manifest, resources=(compute, volume) + manifest.resources[2:]).validate()


@pytest.mark.parametrize(
    "identifier",
    [
        "i-*",
        "i-0123456789ABCDEF0",
        "arn:aws:ec2:us-east-1:111111111111:instance/i-0123456789abcdef0",
    ],
)
def test_other_resource_id_cannot_be_wildcard_or_arn_alias(tmp_path, identifier):
    manifest, _, _, _ = fixture(tmp_path)
    with pytest.raises(Refusal, match="resource_id"):
        replace(
            manifest,
            resources=(replace(manifest.resources[0], identifier=identifier),)
            + manifest.resources[1:],
        ).validate()


def test_protocol_version_is_explicit_no_existing_database_conversion(tmp_path):
    manifest, ledger, _, _ = fixture(tmp_path)
    with pytest.raises(Refusal, match="model_version"):
        replace(manifest, version="cloud-retention-model-1.0").validate()
    with ledger.connect() as db:
        db.execute("PRAGMA user_version=0")
    with pytest.raises(Refusal, match="ledger_version"):
        Ledger(ledger.path, manifest, manifest.commitment)


def test_absence_observation_uses_separate_process_authenticated_read_only_connection(tmp_path):
    manifest, ledger, cloud, controller = fixture(tmp_path)
    controller.reconcile(2000)
    provider_path = tmp_path / "independent-provider.sqlite"
    provider_fixture(provider_path, [])  # Not derived from cleaner dictionaries.
    request = challenge(ledger, 2001)
    code = """
import base64,json,sys
from pathlib import Path
from test_cloud_retention_model import FIXTURE_SIGNER,VERIFIER_PRINCIPAL
from tools.phase2_cloud_verification import ReadOnlyFixtureInventory,OfflineVerifier
reader=ReadOnlyFixtureInventory(Path(sys.argv[1]),VERIFIER_PRINCIPAL,b'synthetic-read-only-credential')
body,signature=OfflineVerifier(reader,FIXTURE_SIGNER).answer(json.load(sys.stdin))
print(json.dumps([base64.b64encode(body).decode(),signature.hex()]))
"""
    env = dict(
        os.environ, PYTHONPATH=os.pathsep.join([str(Path.cwd()), str(Path.cwd() / "tests/unit")])
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(provider_path)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    body, signature = json.loads(result.stdout)
    assert not hasattr(provider_fixture(tmp_path / "reader2.sqlite", []).reader, "delete")
    receipt = accept_observation(
        ledger, request, (base64.b64decode(body), bytes.fromhex(signature)), 2002
    )
    assert receipt["status"] == "COMPLETE" and not receipt["real_cloud_proof"]
    assert not cloud.present
    with sqlite3.connect(provider_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("DELETE FROM resources")


@pytest.mark.parametrize(
    "change", ["wrong_credential", "cleaner_role", "wrong_account", "wrong_region", "unknown_copy"]
)
def test_independent_reader_refuses_provider_boundary_and_unknown_inventory(tmp_path, change):
    manifest, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    resources = (
        [replace(manifest.resources[1], identifier="vol-11111111111111111")]
        if change == "unknown_copy"
        else []
    )
    verifier = provider_fixture(tmp_path / "separate.sqlite", resources)
    if change == "wrong_credential":
        verifier.reader.credential = b"synthetic-wrong"
    if change == "cleaner_role":
        verifier.reader.principal = "arn:aws:iam::222222222222:role/synthetic-cleaner"
    if change in {"wrong_account", "wrong_region"}:
        with sqlite3.connect(verifier.reader.path) as db:
            db.execute(
                "UPDATE endpoint SET "
                + ("account='999999999999'" if change == "wrong_account" else "region='eu-west-1'")
            )
    reason = (
        "protected_resources_remain"
        if change == "unknown_copy"
        else "provider_boundary"
        if change.startswith("wrong_a") or change == "wrong_region"
        else "verifier_provider_authentication"
    )
    with pytest.raises(Refusal, match=reason):
        controller.verify(2001, verifier)
    assert ledger.snapshot()[0] == "VERIFYING"


@pytest.mark.parametrize(
    "change",
    [
        "signature",
        "root",
        "principal",
        "nonce",
        "catalog",
        "coverage",
        "truncated",
        "future",
        "stale",
        "mode",
    ],
)
def test_signed_observation_tamper_and_incomplete_coverage(tmp_path, change):
    _, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    request = challenge(ledger, 2001)
    verifier = provider_fixture(tmp_path / "independent.sqlite", [])
    body, signature = verifier.answer(request)
    record = json.loads(body)
    if change in {"root", "principal", "nonce", "catalog"}:
        record["request"][change] = "substituted"
    elif change == "coverage":
        record["coverage"].remove("upload")
    elif change == "truncated":
        record["exhaustive"] = False
    elif change == "future":
        record["observed_at"] = 3000
    elif change == "mode":
        record["mode"] = "REAL"
    body = canonical(record)
    key = (
        Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
        if change == "signature"
        else FIXTURE_SIGNER
    )
    signature = key.sign(body)
    with pytest.raises(
        Refusal,
        match="verifier_signature|observation_binding|observation_coverage|observation_stale",
    ):
        accept_observation(ledger, request, (body, signature), 2062 if change == "stale" else 2002)
    assert ledger.snapshot()[0] == "VERIFYING"


def test_observation_nonce_is_durable_and_single_use(tmp_path):
    manifest, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    request = challenge(ledger, 2001)
    envelope = provider_fixture(tmp_path / "independent.sqlite", []).answer(request)
    restarted = Ledger(ledger.path, manifest, manifest.commitment)
    assert accept_observation(restarted, request, envelope, 2002)["status"] == "COMPLETE"
    with pytest.raises(Refusal, match="observation_replay_or_unknown"):
        accept_observation(restarted, request, envelope, 2003)


def test_cleaner_empty_inventory_cannot_override_independent_provider_presence(tmp_path):
    manifest, ledger, cloud, controller = fixture(tmp_path)
    controller.reconcile(2000)
    assert not cloud.present
    # A lying/stale cleaner cannot supply the verifier's own independently queried state.
    verifier = provider_fixture(tmp_path / "provider-still-present.sqlite", [manifest.resources[1]])
    with pytest.raises(Refusal, match="protected_resources_remain"):
        controller.verify(2001, verifier)
    assert ledger.snapshot()[0] == "VERIFYING"


def test_concurrent_verification_cannot_consume_one_observation_twice(tmp_path):
    _, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    request = challenge(ledger, 2001)
    envelope = provider_fixture(tmp_path / "separate.sqlite", []).answer(request)
    barrier = Barrier(2)

    def consume(_):
        barrier.wait()
        try:
            return accept_observation(ledger, request, envelope, 2002)["status"]
        except Refusal as exc:
            return str(exc)

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(consume, range(2))) == ["COMPLETE", "observation_replay_or_unknown"]


def test_cleanup_and_verifier_principals_must_differ(tmp_path):
    manifest, _, _, _ = fixture(tmp_path)
    with pytest.raises(Refusal, match="separate_cleanup_principal"):
        replace(manifest, verifier_principal=manifest.cleanup_principal).validate()


@pytest.mark.parametrize("crash_at", ["PREPARED", "DISPATCHED", "RETURNED", "REGISTERED"])
def test_dynamic_registration_crash_recovery_in_fresh_process(tmp_path, crash_at):
    slot, manifest, ledger, cloud = dynamic_fixture(tmp_path)
    resource = returned_resource(manifest, slot)
    provider_path = tmp_path / "durable-provider.sqlite"
    provider_fixture(provider_path, manifest.resources)
    code = """
import json,os,sys,sqlite3
from pathlib import Path
from tools.phase2_cloud_retention_model import Manifest,Resource,CreationSlot,Ledger
from tools.phase2_cloud_registration import Registration
body=json.loads(sys.stdin.read())
body['resources']=tuple(Resource(**r) for r in body['resources'])
body['creation_slots']=tuple(CreationSlot(**s) for s in body['creation_slots'])
m=Manifest(**body)
r=Registration(Ledger(Path(sys.argv[1]),m,m.commitment)); slot=m.creation_slots[0]
r.prepare(slot,1,m.tenant,1002)
if sys.argv[2]=='PREPARED': os._exit(83)
r.dispatch(slot,1,1002)
if sys.argv[2]=='DISPATCHED': os._exit(83)
from dataclasses import replace,asdict
from tools.phase2_cloud_retention_model import canonical
result=replace(m.resources[-2],kind=slot.kind,identifier='Native.ID+/==%2F',key=slot.key,
parent=slot.parent,provisioning_sha256=slot.request_sha256)
with sqlite3.connect(sys.argv[3]) as provider:
 provider.execute('INSERT INTO resources VALUES(?,1)',(canonical(asdict(result)),))
if sys.argv[2]=='RETURNED': os._exit(83)
r.register(slot,result); os._exit(83)
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(ledger.path), crash_at, str(provider_path)],
        input=manifest.body,
        capture_output=True,
        timeout=20,
    )
    assert process.returncode == 83, process.stderr
    if crash_at in {"RETURNED", "REGISTERED"}:
        from tools.phase2_cloud_retention_model import Resource

        with sqlite3.connect(provider_path) as db:
            persisted = [
                Resource(**json.loads(body))
                for (body,) in db.execute("SELECT body FROM resources WHERE present=1")
            ]
        assert resource in persisted  # Durable provider effect predates killed-client ack.
        cloud = MockCloud(persisted, manifest.account, manifest.region)
    restarted = Ledger(ledger.path, manifest, manifest.commitment)
    reg = Registration(restarted)
    assert restarted.manifest.expires == 2000
    restarted.invalidate("SCOPE_FAILURE")
    result = Controller(restarted, cloud).reconcile(2000)
    if crash_at == "DISPATCHED":
        assert result == "OVERDUE_INCOMPLETE"  # Uncertain send is never retried.
        with pytest.raises(Refusal, match="execution_fenced|authorization_expired"):
            reg.dispatch(slot, 1, 2001)
    else:
        assert result == "VERIFYING" and not cloud.present
        if crash_at != "PREPARED":
            assert resource in restarted.inventory() and reg.pending() == [
                (slot.operation, "REGISTERED")
            ]


def test_registration_ack_loss_idempotence_immutable_append_and_cleanup_only(tmp_path):
    slot, manifest, ledger, cloud = dynamic_fixture(tmp_path)
    reg, resource = Registration(ledger), returned_resource(manifest, slot)
    reg.prepare(slot, 1, manifest.tenant, 1002)
    reg.dispatch(slot, 1, 1002)
    provider_created(cloud, resource)
    ledger.invalidate("WITHDRAWN")
    first = reg.register(slot, resource)
    assert reg.register(slot, resource) == first
    with pytest.raises(Refusal, match="execution_fenced"):
        ledger.admission(resource, ledger.snapshot()[1], manifest.tenant, 1003)
    with ledger.connect() as db:
        assert db.execute("SELECT count(*) FROM registrations").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError, match="immutable_registration"):
            db.execute("DELETE FROM registrations")
        with pytest.raises(sqlite3.IntegrityError, match="immutable_intent"):
            db.execute("UPDATE create_intents SET body='changed'")
    with pytest.raises(Refusal, match="registration_substitution"):
        reg.register(slot, replace(resource, identifier="different-native"))
    assert Controller(ledger, cloud).reconcile(2000) == "VERIFYING" and not cloud.present


@pytest.mark.parametrize(
    "change",
    ["tenant", "parent", "key", "kind", "receipt", "inflight", "ambiguous", "inventory_failure"],
)
def test_dynamic_recovery_never_adopts_substituted_or_uncertain_resources(tmp_path, change):
    slot, manifest, ledger, cloud = dynamic_fixture(tmp_path)
    reg, resource = Registration(ledger), returned_resource(manifest, slot)
    reg.prepare(slot, 1, manifest.tenant, 1002)
    reg.dispatch(slot, 1, 1002)
    fields = {
        "tenant": {"tenant": "foreignTenant"},
        "parent": {"parent": "foreign-bucket"},
        "key": {"key": "unapproved"},
        "kind": {"kind": "upload"},
        "receipt": {"provisioning_sha256": "a" * 64},
    }
    resource = replace(resource, **fields.get(change, {}))
    provider_created(cloud, resource)
    if change == "ambiguous":
        provider_created(cloud, replace(resource, identifier="other-returned-id"))
    if change == "inflight":
        cloud.creation_in_flight = True
    if change == "inventory_failure":
        cloud.fail.add("inventory")
    assert Controller(ledger, cloud).reconcile(2000) == "OVERDUE_INCOMPLETE"
    assert not cloud.calls and resource.identity in cloud.present
    assert ledger.manifest.expires == 2000


def test_two_dispatchers_cannot_repeat_provider_operation(tmp_path):
    slot, manifest, ledger, _ = dynamic_fixture(tmp_path)
    reg = Registration(ledger)
    reg.prepare(slot, 1, manifest.tenant, 1002)
    barrier = Barrier(2)

    def dispatch(_):
        barrier.wait()
        try:
            reg.dispatch(slot, 1, 1002)
            return "send_once"
        except Refusal as exc:
            return str(exc)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(dispatch, range(2)))
    assert sorted(results) == ["creation_already_dispatched_or_missing", "send_once"]


def test_null_version_is_representable_for_cleanup_but_not_new_immutable_evidence(tmp_path):
    slot, manifest, ledger, _ = dynamic_fixture(tmp_path)
    reg = Registration(ledger)
    reg.prepare(slot, 1, manifest.tenant, 1002)
    reg.dispatch(slot, 1, 1002)
    with pytest.raises(Refusal, match="unversioned_creation"):
        reg.register(slot, returned_resource(manifest, slot, "null"))
    assert reg.pending() == [(slot.operation, "DISPATCHED")]


def test_dispatched_intent_blocks_independent_absence_receipt(tmp_path):
    slot, manifest, ledger, cloud = dynamic_fixture(tmp_path)
    reg = Registration(ledger)
    reg.prepare(slot, 1, manifest.tenant, 1002)
    reg.dispatch(slot, 1, 1002)
    assert Controller(ledger, cloud).reconcile(2000) == "OVERDUE_INCOMPLETE"
    with pytest.raises(Refusal, match="verification_state|unresolved_creation"):
        challenge(ledger, 2001)
    assert ledger.snapshot()[0] != "COMPLETE"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("tenant", "tenant"),
        ("scope", "unapproved_creation"),
        ("expiry", "authorization_expired"),
        ("generation", "execution_fenced"),
    ],
)
def test_creation_admission_exact_authority(tmp_path, change, reason):
    slot, manifest, ledger, _ = dynamic_fixture(tmp_path)
    with pytest.raises(Refusal, match=reason):
        Registration(ledger).prepare(
            replace(slot, key="other") if change == "scope" else slot,
            2 if change == "generation" else 1,
            "foreign" if change == "tenant" else manifest.tenant,
            1900 if change == "expiry" else 1002,
        )
    assert Registration(ledger).pending() == []


def test_dispatch_cannot_substitute_scope_after_a_valid_prepare(tmp_path):
    slot, manifest, ledger, _ = dynamic_fixture(tmp_path)
    reg = Registration(ledger)
    reg.prepare(slot, 1, manifest.tenant, 1002)
    with pytest.raises(Refusal, match="unapproved_creation"):
        reg.dispatch(replace(slot, key="excluded/other"), 1, 1002)
    assert reg.pending() == [(slot.operation, "PREPARED")]


@pytest.mark.parametrize("kind", ["version", "upload"])
def test_dynamic_catalog_flows_to_independently_signed_absence(tmp_path, kind):
    slot, manifest, ledger, cloud = dynamic_fixture(tmp_path, kind)
    reg = Registration(ledger)
    reg.prepare(slot, 1, manifest.tenant, 1002)
    reg.dispatch(slot, 1, 1002)
    resource = returned_resource(manifest, slot)
    provider_created(cloud, resource)
    reg.register(slot, resource)
    controller = Controller(ledger, cloud)
    assert controller.reconcile(2000) == "VERIFYING"
    request = challenge(ledger, 2001)
    assert list(resource.identity) in request["identities"]
    verifier = provider_fixture(tmp_path / "independent-final-provider.sqlite", [])
    assert (
        accept_observation(ledger, request, verifier.answer(request), 2002)["status"] == "COMPLETE"
    )
    assert len(cloud.calls) == len(manifest.resources) + 1 and not cloud.present
    assert ledger.manifest.expires == 2000


def copy_fixture():
    destination = dict(
        account="111111111111",
        region="us-east-1",
        resource_sha256="c" * 64,
        namespace="syntheticNs",
    )
    binding = dict(
        owner="syntheticOwner",
        tenant="syntheticTenant",
        attempt="syntheticAttempt",
        namespace="syntheticNs",
        scope_sha256="a" * 64,
        package_a_sha256="b" * 64,
        created=1000,
        retention_expires=2000,
        approval_evidence_sha256="e" * 64,
        registered_destinations=[destination],
        approved_processor_contracts=["f" * 64],
    )
    record = dict(
        version="reviewer-copy-decision-1.0",
        mode="SYNTHETIC_ONLY",
        status="APPROVED",
        option="MANAGED_REVIEW",
        binding=binding,
        authorization_expires=1500,
        approval_evidence_sha256="e" * 64,
        copies=[
            dict(
                destination=destination,
                classification="SOURCE_ONLY_A",
                expires=2000,
                independent_deletion_verification=True,
                provider_contract_sha256=None,
                cleanup_receipt_required=True,
            )
        ],
    )
    return record, binding


def evaluate(record, binding, signer=FIXTURE_SIGNER, now=1001):
    body = canonical(record)
    return evaluate_copy_decision(
        body,
        signer.sign(body),
        approved_public_key=FIXTURE_SIGNER.public_key().public_bytes_raw(),
        binding=binding,
        now=now,
    )


def test_actual_owner_record_is_pending_and_blocks_every_handoff():
    path = Path("docs/operations/cloud-reviewer-copy-decision.json")
    record = json.loads(path.read_bytes())
    assert record["selected_option"] is None and not record["handoff_authorized"]
    assert record["approval_evidence_sha256"] is None
    with pytest.raises(Refusal, match="owner_decision_pending"):
        evaluate(record, {})


@pytest.mark.parametrize("option", ["MANAGED_REVIEW", "CONTRACTED_PROCESSOR"])
def test_signed_synthetic_copy_options_require_registered_destinations(option):
    record, binding = copy_fixture()
    record["option"] = option
    if option == "CONTRACTED_PROCESSOR":
        record["copies"][0]["provider_contract_sha256"] = "f" * 64
    assert evaluate(record, binding) == dict(
        status="SYNTHETIC_POLICY_ELIGIBLE",
        decision_sha256=digest(canonical(record)),
        real_handoff_authorized=False,
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        ("no_export", "handoff_option_blocked"),
        ("waiver", "handoff_option_blocked"),
        ("unmanaged", "unregistered_export"),
        ("prediction", "prediction_export_forbidden"),
        ("extended", "copy_retention_extension"),
        ("unknown_cleanup", "copy_cleanup_unproven"),
        ("no_contract", "processor_contract_missing"),
        ("wrong_tenant", "decision_binding"),
        ("real", "not_live_authorization"),
        ("forged", "owner_decision_authentication"),
        ("expired", "copy_authorization_expired"),
        ("duplicate", "duplicate_copy"),
    ],
)
def test_copy_policy_negative_controls(tmp_path, change, reason):
    record, binding = copy_fixture()
    copy = record["copies"][0]
    if change == "no_export":
        record["option"] = "NO_EXPORT_NO_HANDOFF"
    if change == "waiver":
        record["option"] = "UNCONTROLLED_EXPORT_WAIVER"
    if change == "unmanaged":
        copy["destination"] = dict(namespace="host-download")
    if change == "prediction":
        copy["classification"] = "PACKAGE_B"
    if change == "extended":
        copy["expires"] = 2001
    if change == "unknown_cleanup":
        copy["independent_deletion_verification"] = False
    if change == "no_contract":
        record["option"] = "CONTRACTED_PROCESSOR"
    if change == "wrong_tenant":
        record["binding"] = dict(binding, tenant="other")
    if change == "real":
        record["mode"] = "REAL"
    if change == "duplicate":
        record["copies"].append(dict(copy))
    signer = (
        Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
        if change == "forged"
        else FIXTURE_SIGNER
    )
    with pytest.raises(Refusal, match=reason):
        evaluate(record, binding, signer, 1500 if change == "expired" else 1001)

"""CR-02 account-wide read coverage never confers exact-resource delete authority."""

import json
from dataclasses import replace

import pytest
from test_cloud_retention_model import FIXTURE_SIGNER, fixture, observer, provider_fixture

from tools.phase2_cloud_retention_model import Refusal, canonical, digest
from tools.phase2_cloud_verification import accept_observation, challenge


def assert_remaining_refused(tmp_path, ledger, controller, resources):
    original_root, original_expiry = ledger.expected, ledger.manifest.expires
    verifier = provider_fixture(tmp_path / "independent-provider.sqlite", resources)
    request = challenge(ledger, 2001)
    envelope = verifier.answer(request)
    record = json.loads(envelope[0])
    assert record["present"] == sorted(r.commitment for r in resources)
    with pytest.raises(Refusal, match="protected_resources_remain"):
        accept_observation(ledger, request, envelope, 2002)
    assert ledger.snapshot()[0] == "VERIFYING"
    assert (
        ledger.manifest.commitment == original_root and ledger.manifest.expires == original_expiry
    )
    with ledger.connect() as db:
        assert db.execute(
            "SELECT consumed FROM observations WHERE nonce=?", (request["nonce"],)
        ).fetchone() == (0,)


def test_foreign_namespace_snapshot_of_registered_custody_volume_blocks_complete(tmp_path):
    manifest, ledger, cloud, controller = fixture(tmp_path)
    controller.reconcile(2000)
    assert not cloud.present  # Cleaner success must not replace independent inventory.
    snapshot = replace(
        manifest.resources[2], identifier="snap-11111111111111111", namespace="foreignSnapshotNs"
    )
    assert snapshot.parent == manifest.resources[1].identifier
    assert_remaining_refused(tmp_path, ledger, controller, [snapshot])


def test_foreign_namespace_volume_attached_to_registered_compute_blocks_complete(tmp_path):
    manifest, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    volume = replace(
        manifest.resources[1], identifier="vol-11111111111111111", namespace="foreignVolumeNs"
    )
    assert volume.parent == manifest.resources[0].identifier
    assert_remaining_refused(tmp_path, ledger, controller, [volume])


def test_transitive_foreign_volume_and_snapshot_are_both_observed(tmp_path):
    manifest, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    volume = replace(
        manifest.resources[1], identifier="vol-11111111111111111", namespace="foreignVolumeNs"
    )
    snapshot = replace(
        manifest.resources[2],
        identifier="snap-11111111111111111",
        parent=volume.identifier,
        namespace="foreignSnapshotNs",
    )
    # Child precedes parent in provider output; neither parent is registered/present.
    assert_remaining_refused(tmp_path, ledger, controller, [snapshot, volume])


@pytest.mark.parametrize("kind", ["compute", "volume", "snapshot", "bucket", "version", "upload"])
def test_account_region_coverage_includes_disconnected_resources_without_matching_labels(
    tmp_path, kind
):
    manifest, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    original = next(r for r in manifest.resources if r.kind == kind)
    identifier = {
        "compute": "i-33333333333333333",
        "volume": "vol-33333333333333333",
        "snapshot": "snap-33333333333333333",
        "bucket": "unrelated-bucket",
        "version": "unrelated.Version+/=",
        "upload": "unrelated.Upload+/=",
    }[kind]
    parent = {
        "compute": "",
        "volume": "",  # Detached volume: no remaining attachment edge.
        "snapshot": "vol-33333333333333333",  # Arbitrary copied-snapshot lineage.
        "bucket": "",
        "version": "unrelated-bucket",
        "upload": "unrelated-bucket",
    }[kind]
    unrelated = replace(
        original,
        namespace="foreignNs",
        tenant="foreignTenant",
        identifier=identifier,
        parent=parent,
    )
    assert unrelated.identity not in {r.identity for r in manifest.resources}
    # Includes detached volumes, copied-snapshot arbitrary lineage and unknown S3 buckets.
    assert_remaining_refused(tmp_path, ledger, controller, [unrelated])


def test_unrelated_volume_is_never_adopted_as_cleanup_authority(tmp_path):
    manifest, ledger, cloud, controller = fixture(tmp_path)
    unrelated = replace(
        manifest.resources[1],
        identifier="vol-11111111111111111",
        parent="i-22222222222222222",
        namespace="unrelatedNs",
    )
    cloud.resources[unrelated.identity] = unrelated
    cloud.present.add(unrelated.identity)
    assert controller.reconcile(2000) == "VERIFYING"
    calls = list(cloud.calls)
    assert len(calls) == len(manifest.resources)
    assert (unrelated.kind, unrelated.commitment) not in calls
    with pytest.raises(Refusal, match="protected_resources_remain"):
        controller.verify(2001, observer(cloud))
    with pytest.raises(Refusal, match="unregistered_delete"):
        cloud.delete(unrelated, manifest)
    assert cloud.calls == calls and cloud.present == {unrelated.identity}
    assert unrelated not in ledger.inventory()


@pytest.mark.parametrize("field,value", [("account", "999999999999"), ("region", "eu-west-1")])
def test_provider_rows_cannot_silently_substitute_account_or_region(tmp_path, field, value):
    manifest, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    wrong_boundary = replace(manifest.resources[2], namespace="foreignNs", **{field: value})
    verifier = provider_fixture(tmp_path / "wrong-boundary.sqlite", [wrong_boundary])
    with pytest.raises(Refusal, match="provider_resource_boundary"):
        controller.verify(2001, verifier)
    assert ledger.snapshot()[0] == "VERIFYING"


def test_unsupported_provider_resource_cannot_be_silently_omitted(tmp_path):
    manifest, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    unsupported = replace(manifest.resources[2], kind="image", namespace="foreignNs")
    verifier = provider_fixture(tmp_path / "unsupported-provider.sqlite", [unsupported])
    with pytest.raises(Refusal, match="provider_resource_kind"):
        controller.verify(2001, verifier)
    assert ledger.snapshot()[0] == "VERIFYING"


def test_legacy_query_version_cannot_be_reinterpreted_as_account_wide(tmp_path):
    _, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    verifier = provider_fixture(tmp_path / "empty-provider.sqlite", [])
    request = dict(challenge(ledger, 2001), version="absence-query-1.1")
    with pytest.raises(Refusal, match="inventory_scope"):
        verifier.answer(request)
    assert ledger.snapshot()[0] == "VERIFYING"


@pytest.mark.parametrize("scope", [None, "PARENT_SCOPED", "NAMESPACE_ONLY"])
def test_narrower_or_legacy_scope_cannot_supply_account_wide_absence(tmp_path, scope):
    _, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    verifier = provider_fixture(tmp_path / "empty-provider.sqlite", [])
    request = challenge(ledger, 2001)
    altered = dict(request, inventory_scope=scope)
    with pytest.raises(Refusal, match="inventory_scope"):
        verifier.answer(altered)
    body, _ = verifier.answer(request)
    record = json.loads(body)
    record["request"] = altered
    body = canonical(record)
    # Even a fixture-signed narrower observation cannot substitute for the query.
    with pytest.raises(Refusal, match="inventory_scope|observation_binding"):
        accept_observation(ledger, altered, (body, FIXTURE_SIGNER.sign(body)), 2002)
    assert ledger.snapshot()[0] == "VERIFYING"


def test_empty_account_region_receipt_explicitly_binds_enumeration_scope(tmp_path):
    _, ledger, _, controller = fixture(tmp_path)
    controller.reconcile(2000)
    verifier = provider_fixture(tmp_path / "empty-provider.sqlite", [])
    request = challenge(ledger, 2001)
    assert request["inventory_scope"] == "DEDICATED_ACCOUNT_REGION"
    assert request["version"] == "absence-query-1.2"
    envelope = verifier.answer(request)
    receipt = accept_observation(ledger, request, envelope, 2002)
    assert receipt["inventory_scope"] == request["inventory_scope"]
    assert receipt["version"] == "synthetic-cleanup-receipt-1.2"
    assert receipt["observation_sha256"] == digest(envelope[0])
    assert not receipt["real_cloud_proof"]

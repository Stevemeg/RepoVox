"""Durability/concurrency on a disposable local protocol emulator, not DynamoDB."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest
from aws_fixtures import ACCOUNT, ANCHOR, BOUNDARY, REGION, ROOT_BODY, Harness, LocalDynamo

from tools.phase2_aws_registry import Registry
from tools.phase2_cloud_retention_model import Refusal, canonical


def registry(tmp_path):
    emulator = LocalDynamo(tmp_path / "disposable.sqlite")
    # Registry SDK interface uses the SQLite fixture; no cloud SDK/network.
    emulator.boundary = BOUNDARY
    instance = Registry(emulator, "synthetic-registry", deepcopy(ROOT_BODY), ANCHOR)
    instance.initialize()
    instance.activate("a" * 64, 1100)
    return instance, emulator


def resource():
    slot = ROOT_BODY["creation_slots"][0]
    return {k: slot[k] for k in ["kind", "parent", "key", "request_sha256"]} | dict(
        account=ACCOUNT, region=REGION, identifier="native/+==%2F"
    )


def test_registry_initial_transaction_is_actual_sdk_shape():
    h = Harness(["dynamodb"])
    r = Registry(h.sdk, "synthetic-registry", ROOT_BODY, ANCHOR)
    # ANY token is SDK-valid; exact request body is independently asserted below.
    from botocore.stub import ANY

    h.expect(
        "dynamodb",
        "transact_write_items",
        {},
        dict(
            ClientRequestToken=ANY,
            TransactItems=[
                r.put("ROOT", body=canonical(ROOT_BODY).decode()),
                r.put(
                    "STATE",
                    status="PENDING",
                    generation=0,
                    revision=0,
                    outstanding=0,
                    lease_end=0,
                    worker="",
                    health_until=0,
                    progress=0,
                ),
            ],
        ),
    )
    r.initialize()
    h.done()


def test_expiry_and_terminal_fence_cannot_be_renewed(tmp_path):
    r, emulator = registry(tmp_path)
    original = r.get("ROOT")
    r.fence(1200)
    with pytest.raises(Refusal, match="conditional_transaction"):
        r.activate("b" * 64, 1300)
    with pytest.raises(Refusal, match="conditional_transaction"):
        r.prepare("operation-1", ROOT_BODY["creation_slots"][0], 1, 1300)
    recreated = Registry(emulator, "synthetic-registry", ROOT_BODY, ANCHOR)
    with pytest.raises(Refusal, match="conditional_transaction"):
        recreated.initialize()
    assert r.get("ROOT") == original


def test_creation_crash_dispatch_and_lost_registration_ack(tmp_path):
    r, emulator = registry(tmp_path)
    slot = ROOT_BODY["creation_slots"][0]
    r.prepare("operation-1", slot, 1, 1100)
    r.dispatch("operation-1", 1, 1100)
    r.fence(1200)
    token = r.claim("synthetic-cleaner", 1200)
    with pytest.raises(Refusal, match="unsettled_creation"):
        r.challenge(1200, BOUNDARY.role, "a" * 64)
    with pytest.raises(Refusal, match="conditional_transaction"):
        r.dispatch("operation-1", 1, 1300)  # No resubmission after uncertain create.
    emulator.fail_after_commit = True
    with pytest.raises(TimeoutError):
        r.register("operation-1", resource())  # Provider result arrives late, cleanup only.
    original = r.get("ROOT")
    r = Registry(emulator, "synthetic-registry", ROOT_BODY, ANCHOR)
    commitment = r.register("operation-1", resource())
    assert len(commitment) == 64 and r.validate()["outstanding"] == 0
    with pytest.raises(Refusal, match="registration_substitution"):
        r.register("operation-1", resource() | dict(identifier="other"))
    assert r.get("ROOT") == original
    assert r.validate()["generation"] == token["generation"]
    with pytest.raises(Refusal, match="write_settlement_unproven"):
        r.challenge(1300, BOUNDARY.role, "a" * 64)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"account": "222222222222"}, "registration_boundary"),
        ({"region": "us-west-2"}, "registration_boundary"),
        ({"key": "elsewhere"}, "registration_scope"),
        ({"identifier": "null"}, "unversioned_creation"),
    ],
)
def test_dynamic_registration_substitution_refused(tmp_path, change, code):
    r, _ = registry(tmp_path)
    r.prepare("operation-1", ROOT_BODY["creation_slots"][0], 1, 1100)
    r.dispatch("operation-1", 1, 1100)
    with pytest.raises(Refusal, match=code):
        r.register("operation-1", resource() | change)
    assert r.validate()["outstanding"] == 1


def test_two_concurrent_cleanup_claims_one_winner_and_stale_worker(tmp_path):
    r, _ = registry(tmp_path)
    r.fence(1200)
    barrier = Barrier(2)

    def claim(worker):
        barrier.wait()
        try:
            return r.claim(worker, 1200)
        except Refusal:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["one", "two"]))
    winners = [x for x in results if x]
    assert len(winners) == 1
    r.check_claim(winners[0], 1201)
    replacement = r.claim("recovery", 1246)
    with pytest.raises(Refusal, match="stale_claim"):
        r.progress(winners[0], "a" * 64, "REQUESTED", 1247)
    r.progress(replacement, "a" * 64, "INCOMPLETE", 1247)


def test_nonce_consume_atomic_replay_and_continued_reconciliation(tmp_path):
    r, emulator = registry(tmp_path)
    r.fence(1200)
    token = r.claim("cleaner", 1200)
    emulator.seed("SETTLEMENT", generation=token["generation"], sha256="a" * 64)
    request = r.challenge(1201, BOUNDARY.role, "a" * 64)
    r.complete(request, "b" * 64, 1202)
    with pytest.raises(Refusal, match="conditional_transaction"):
        r.complete(request, "b" * 64, 1203)
    # Cleanup completion does not reopen execution; reconciliation keeps running.
    next_claim = r.claim("reconcile-after-complete", 1246)
    assert next_claim["generation"] > token["generation"]
    with pytest.raises(Refusal):
        r.prepare("operation-1", ROOT_BODY["creation_slots"][0], next_claim["generation"], 1250)


def test_expired_creation_authorization(tmp_path):
    r, _ = registry(tmp_path)
    with pytest.raises(Refusal, match="authorization_expired"):
        r.prepare("operation-1", ROOT_BODY["creation_slots"][0], 1, 1800)
    assert r.validate()["outstanding"] == 0


def test_missing_source_or_attempt_binding_cannot_initialize(tmp_path):
    from dataclasses import replace

    from tools.phase2_cloud_retention_model import digest

    body = deepcopy(ROOT_BODY)
    del body["manifest_sha256"]
    emulator = LocalDynamo(tmp_path / "missing-binding.sqlite")
    anchor = digest(canonical(body))
    emulator.boundary = replace(BOUNDARY, root=anchor)
    with pytest.raises(Refusal, match="root_binding_fields"):
        Registry(emulator, "fixture", body, anchor)
    assert emulator.calls == []


def test_stalled_health_blocks_writes_and_heartbeat_cannot_extend_expiry(tmp_path):
    r, _ = registry(tmp_path)
    with pytest.raises(Refusal, match="conditional_transaction"):
        r.prepare("operation-1", ROOT_BODY["creation_slots"][0], 1, 1221)
    r.heartbeat(1, 1, 1221)
    with pytest.raises(Refusal, match="conditional_transaction"):
        r.heartbeat(1, 1, 1222)  # Container alive, but loop made no progress.
    r.heartbeat(1, 2, 1799)
    assert r.validate()["health_until"] == ROOT_BODY["authorization_expires"]
    assert r.get("ROOT")["body"] == canonical(ROOT_BODY).decode()

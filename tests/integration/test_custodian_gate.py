"""Actual authenticated PostgreSQL fence, with no acquisition or prediction."""

from conftest import A
from test_pilot_control import cp as cp

from tools.phase2_custodian_adapter import LeaseBoundExecutor, PilotLeaseAdmission


def test_preclaimed_handover_is_one_use_and_binding_checked(cp):
    import pytest

    gate = PilotLeaseAdmission(
        cp.worker, cp.attempt, 1, cp.manifest.sha256, "sample", cp.stage, "tenant-a"
    )
    first, duplicate = LeaseBoundExecutor(cp.worker, gate), LeaseBoundExecutor(cp.worker, gate)
    with pytest.raises(ValueError, match="execution_claim_binding"):
        first.claim(cp.stage, cp.attempt, 2, cp.manifest.sha256, "sample")
    assert first.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample") == gate.lease
    assert duplicate.claim(cp.stage, cp.attempt, 1, cp.manifest.sha256, "sample") is None
    cp.control.invalidate(A, cp.attempt, 1)
    assert not gate(
        dict(tenant="tenant-a", attempt=str(cp.attempt), manifest_sha256=cp.manifest.sha256)
    )
    assert cp.hub.calls == 0


def test_custody_gate_uses_real_claim_and_rejects_cancelled_attempt(cp):
    gate = PilotLeaseAdmission(
        cp.worker, cp.attempt, 1, cp.manifest.sha256, "sample", cp.stage, "tenant-a"
    )
    plan = {"attempt": str(cp.attempt), "manifest_sha256": cp.manifest.sha256, "tenant": "tenant-a"}
    assert gate(plan)
    assert not gate(dict(plan, attempt="other-attempt"))
    assert not gate(dict(plan, manifest_sha256="0" * 64))
    assert not gate(dict(plan, tenant="tenant-b"))
    cp.control.invalidate(A, cp.attempt, 1)
    assert not gate(plan)
    assert cp.hub.calls == 0

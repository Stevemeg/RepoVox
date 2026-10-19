"""Actual authenticated PostgreSQL fence, with no acquisition or prediction."""

from conftest import A
from test_pilot_control import cp as cp

from tools.phase2_custodian_adapter import PilotLeaseAdmission


def test_custody_gate_uses_real_claim_and_rejects_cancelled_attempt(cp):
    gate = PilotLeaseAdmission(cp.worker, cp.attempt, 1, cp.manifest.sha256, "sample", cp.stage)
    plan = {"attempt": str(cp.attempt), "manifest_sha256": cp.manifest.sha256}
    assert gate(plan)
    assert not gate(dict(plan, attempt="other-attempt"))
    assert not gate(dict(plan, manifest_sha256="0" * 64))
    cp.control.invalidate(A, cp.attempt, 1)
    assert not gate(plan)
    assert cp.hub.calls == 0

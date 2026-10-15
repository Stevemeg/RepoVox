"""Prediction-side binding tests; independent reference fixtures live separately."""

import pytest
from repovox.evaluation.projection_v2 import project_analysis
from repovox.evaluation.v2 import digest, serialize
from test_analysis import SNAPSHOT_ID, analyze
from test_evaluation_v2 import FILES, OWNER, run
from test_evaluation_v2 import case as case


@pytest.fixture
def analysis_input(case):
    root, scope, _, _, _ = case
    request, result = analyze(root, FILES)
    scope.repository = result["knowledge"]["repository"]["repository"]
    scope.commit_sha = result["knowledge"]["repository"]["commit_sha"]
    scope.analysis_owner_id = str(OWNER)
    envelope = {
        "schema_version": "2.3",
        "kind": "verify",
        "owner_id": str(OWNER),
        "snapshot_id": str(SNAPSHOT_ID),
        "commit_sha": scope.commit_sha,
        "pipeline_version": "phase2-static-v1",
        "input_digest": "a" * 64,
        "generation_metadata": None,
        "payload": result,
    }
    return scope, envelope


def project(scope, envelope):
    body = serialize(envelope)
    return project_analysis(body, digest(body), scope, digest(serialize(scope)), "d" * 40)


def test_projection_copies_ledger_not_parser_success(analysis_input):
    scope, envelope = analysis_input
    p = project(scope, envelope)
    assert any(f.verdict_origin == "bound_analysis_ledger" for f in p.facts)
    assert all(f.status == "unreviewed" for f in p.facts if f.fact.category == "entrypoint")
    claim = envelope["payload"]["knowledge"]["claims"][0]
    verdict = next(
        v for v in envelope["payload"]["verification"]["verdicts"] if v["claim_id"] == claim["id"]
    )
    counts = envelope["payload"]["verification"]["counts"]
    counts[claim["status"]] -= 1
    counts["inferred"] = counts.get("inferred", 0) + 1
    claim["status"] = verdict["status"] = "inferred"
    assert (
        next(f for f in project(scope, envelope).facts if f.claim_id == claim["id"]).status
        == "inferred"
    )


def test_runtime_text_cannot_inherit_static_verified_status(analysis_input):
    scope, envelope = analysis_input
    claim = envelope["payload"]["knowledge"]["claims"][0]
    claim["text"] = "The function successfully executes and sends an external message."
    p = project(scope, envelope)
    assert any(c.id == claim["id"] for c in p.unprojected_claims)
    assert not any(f.claim_id == claim["id"] for f in p.facts)
    assert any(f.status == "unreviewed" for f in p.facts)


@pytest.mark.parametrize(
    "problem", ["owner", "commit", "version", "ledger", "evidence", "duplicate", "fact"]
)
def test_projection_binding_failures(analysis_input, problem):
    scope, e = analysis_input
    if problem == "owner":
        e["owner_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    elif problem == "commit":
        e["commit_sha"] = "f" * 40
    elif problem == "version":
        e["schema_version"] = "2.2"
    elif problem == "ledger":
        e["payload"]["verification"]["verdicts"] = []
    elif problem == "evidence":
        e["payload"]["knowledge"]["claims"][0]["evidence_ids"] = ["missing"]
    elif problem == "duplicate":
        e["payload"]["knowledge"]["claims"].append(e["payload"]["knowledge"]["claims"][0])
    elif problem == "fact":
        e["payload"]["knowledge"]["canonical_facts"][0]["subject"]["qualified_name"] = "forged"
    with pytest.raises(ValueError):
        project(scope, e)


def test_score_recomputes_real_projection_and_rejects_resealed_verdict_changes(
    case, analysis_input
):
    from repovox.evaluation.custody_v2 import source_packet

    scope, envelope = analysis_input
    root, _, proofs, ref, _ = case
    # The reference facts were manually authored before analysis_input ran. Only the
    # synthetic snapshot metadata and packet commitments are bound here.
    ref.repository, ref.commit_sha = scope.repository, scope.commit_sha
    ref.scope_sha256 = digest(serialize(scope))
    for a in ref.assertions:
        a.fact.repository, a.fact.commit_sha = scope.repository, scope.commit_sha
    ref.annotation_scope = "partial"
    packet = serialize(source_packet(serialize(scope), ref.scope_sha256, root, proofs))
    proofs[digest(packet)] = packet
    ref.blind_source_sha256 = digest(packet)
    body = serialize(envelope)
    proofs[digest(body)] = body
    pred = project(scope, envelope)
    result = run((root, scope, proofs, ref, pred))
    assert result.completeness["acceptance_status"] == "INCOMPLETE"
    assert result.summary["counts"]["predictions"] == len(pred.facts)
    fact = next(f for f in pred.facts if f.status == "verified")
    fact.status = "unsupported"
    with pytest.raises(ValueError, match="prediction_projection_changed"):
        run((root, scope, proofs, ref, pred))
    proofs.pop(digest(body))
    with pytest.raises(ValueError, match="original_analysis_missing"):
        run((root, scope, proofs, ref, pred))


@pytest.mark.parametrize("field", ["rules", "pipeline", "verifier_version", "counts"])
def test_mixed_version_and_ledger_counts_rejected(analysis_input, field):
    scope, envelope = analysis_input
    payload = envelope["payload"]
    if field == "counts":
        payload["verification"]["counts"]["verified"] = 999
        expected = "ledger_counts_mismatch"
    elif field == "verifier_version":
        payload["verification"][field] = "static-rules-v1"
        expected = "version_mismatch"
    else:
        payload["knowledge"]["versions"][field] = "wrong-version"
        expected = "version_mismatch"
    with pytest.raises(ValueError, match=expected):
        project(scope, envelope)


def test_duplicate_semantic_subject_cannot_be_collapsed(analysis_input):
    from copy import deepcopy

    scope, envelope = analysis_input
    symbols = envelope["payload"]["knowledge"]["symbols"]
    extra = deepcopy(symbols[0])
    extra["id"] = "s-different-id-same-meaning"
    symbols.append(extra)
    with pytest.raises(ValueError, match="canonical_subject_mismatch"):
        project(scope, envelope)

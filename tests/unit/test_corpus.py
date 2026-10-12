from pathlib import Path

import pytest
from repovox.evaluation.corpus import Corpus, CustodianStore, allowed, counts, freeze, withdraw
from repovox.evaluation.scoring import aggregate, compare, valid_citation


def empty() -> Corpus:
    return Corpus(
        version="eval-v1-preparation",
        status="UNFROZEN",
        reviewer_status="PENDING OWNER APPOINTMENT",
        appointment=None,
        families=[],
        access_policy_sha256=None,
        contamination_manifest_sha256=None,
        deletion_policy_sha256=None,
        freeze_sha256=None,
        dependent_reports=[],
        invalidated_reports=[],
    )


def test_corpus_never_invents_review_or_counts() -> None:
    corpus = empty()
    assert counts(corpus)["approved"] == 0 and counts(corpus)["held_out"] == 0
    with pytest.raises(ValueError, match="independent_human_appointment_required"):
        freeze(corpus)
    assert corpus.status == "UNFROZEN" and corpus.freeze_sha256 is None


@pytest.mark.parametrize("split", ["TOOLING_FIXTURE", "EVAL_DEV", "EVAL_TEST"])
@pytest.mark.parametrize("purpose", ["training", "calibration"])
def test_evaluation_is_never_training(split: str, purpose: str) -> None:
    assert not allowed(split, purpose, frozen=True, registered=True)


@pytest.mark.parametrize("purpose", ["development", "prompt_tuning", "annotation", "human_review"])
def test_heldout_not_prompt_data(purpose: str) -> None:
    assert not allowed("EVAL_TEST", purpose, frozen=True, registered=True)


def test_registered_heldout_access_requires_freeze() -> None:
    assert not allowed("EVAL_TEST", "registered_final_evaluation", False, True)
    assert not allowed("EVAL_TEST", "registered_final_evaluation", True, False)
    assert allowed("EVAL_TEST", "registered_final_evaluation", True, True)


def test_hidden_store_never_inside_git(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="protected_store_requires_external_posix_boundary"):
        CustodianStore(tmp_path / "protected", tmp_path)


def test_denominators_and_empty_results_are_explicit() -> None:
    assert compare({("source", "target")}, set()) == {
        "true_positive": 0,
        "predicted": 0,
        "gold": 1,
        "precision": None,
        "recall": 0,
    }
    assert aggregate([])["repositories"] == 0


def test_unknown_withdrawal_does_not_fabricate_lineage() -> None:
    with pytest.raises(ValueError, match="unknown_family"):
        withdraw(empty(), "invented-family")


def test_evaluator_checks_bytes_instead_of_analyzer_status(tmp_path: Path) -> None:
    import hashlib

    body = b"source\n"
    (tmp_path / "file.py").write_bytes(body)
    citation = {
        "path": "file.py",
        "file_sha256": hashlib.sha256(body).hexdigest(),
        "start_line": 1,
        "end_line": 1,
        "commit_sha": "a" * 40,
        "validation_status": "valid",
    }
    assert valid_citation(citation, tmp_path, "a" * 40)
    citation["file_sha256"] = "b" * 64
    assert not valid_citation(citation, tmp_path, "a" * 40)
    citation["path"] = "../forged.py"
    assert not valid_citation(citation, tmp_path, "a" * 40)

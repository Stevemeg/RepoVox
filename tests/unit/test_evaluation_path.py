"""Manually authored engineering gold; not official corpus labels or human-reviewed gold."""

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError
from repovox.evaluation.corpus import Corpus, Family, Rights, counts, intake, serialize
from repovox.evaluation.gold import (
    Attributes,
    Citation,
    EdgeFact,
    EdgeIdentity,
    GoldClaim,
    GoldEdge,
    GoldEntrypoint,
    GoldEvaluation,
    GoldSymbol,
    SymbolFact,
    SymbolIdentity,
)
from repovox.evaluation.scoring import aggregate, score

SHA = "a" * 40  # Explicit synthetic snapshot; never an official pinned repository.
SOURCES = {
    "main.py": (
        b"import helper\ndef run(value):\n    return value\n"
        b'if __name__ == "__main__":\n    run(1)\n'
    ),
    "helper.py": b"def helper(value):\n    return value\n",
}


def authored_gold() -> GoldEvaluation:
    """All names, ranges, attributes, edges and verdicts are authored before analysis."""
    import hashlib

    def symbol(
        path: str, start: int, end: int, kind: str, name: str, rule: str, **attributes: object
    ) -> SymbolIdentity:
        return SymbolIdentity(
            path=path,
            file_sha256=hashlib.sha256(SOURCES[path]).hexdigest(),
            start_line=start,
            end_line=end,
            kind=kind,
            name=name,
            language="python",
            rule=rule,
            attributes=Attributes.model_validate(attributes),
        )

    main = symbol("main.py", 1, 5, "module", "main.py", "module-v1")
    helper = symbol("helper.py", 1, 2, "module", "helper.py", "module-v1")
    imported = symbol(
        "main.py", 1, 1, "import", "helper", "import-v1", alias="helper", imported_name="helper"
    )
    run = symbol("main.py", 2, 3, "function", "run", "declaration-v1", parameters=["value"])
    helper_function = symbol(
        "helper.py", 1, 2, "function", "helper", "declaration-v1", parameters=["value"]
    )
    guard = symbol("main.py", 4, 5, "entrypoint", "__main__", "python-main-v1")
    call = symbol(
        "main.py", 5, 5, "call", "run", "call-expression-v1", binding="", dispatch="named"
    )
    symbols = [main, helper, imported, run, helper_function, guard, call]
    edges = [
        EdgeIdentity(
            source=main,
            target=helper,
            relationship="imports",
            classification="resolved_static",
            support=[imported],
        ),
        EdgeIdentity(
            source=main,
            target=run,
            relationship="contains",
            classification="declared",
            support=[run],
        ),
        EdgeIdentity(
            source=helper,
            target=helper_function,
            relationship="contains",
            classification="declared",
            support=[helper_function],
        ),
        EdgeIdentity(
            source=main,
            target=guard,
            relationship="contains",
            classification="declared",
            support=[guard],
        ),
        EdgeIdentity(
            source=main,
            target=call,
            relationship="call_expression",
            classification="unresolved",
            support=[call],
        ),
    ]

    def citation(s: SymbolIdentity) -> Citation:
        return Citation.model_validate(s.model_dump(include=set(Citation.model_fields)))

    return GoldEvaluation(
        gold_schema_version="gold-evaluation-1.0",
        repository="example/gold-tooling",
        commit_sha=SHA,
        annotation_scope="complete",
        symbols=[
            GoldSymbol(id=f"manual-symbol-{i}", **s.model_dump()) for i, s in enumerate(symbols)
        ],
        entrypoints=[
            GoldEntrypoint(
                id="manual-main-entry",
                path="main.py",
                rule="python-main-v1",
                citations=[citation(guard)],
            )
        ],
        edges=[
            GoldEdge(
                id=f"manual-edge-{i}",
                supported=True,
                citations=[citation(e.support[0])],
                **e.model_dump(),
            )
            for i, e in enumerate(edges)
        ],
        claims=[
            GoldClaim(
                id=f"manual-claim-symbol-{i}",
                text=f"Observed source syntax: {s.kind} {s.name}.",
                status="verified",
                fact=SymbolFact(type="symbol_syntax", symbol=s),
                citations=[citation(s)],
            )
            for i, s in enumerate(symbols)
        ]
        + [
            GoldClaim(
                id=f"manual-claim-edge-{i}",
                text=f"Qualified static relation: {e.relationship}; execution is unknown.",
                status="inferred" if i == 4 else "verified",
                fact=EdgeFact(type="static_relationship", edge=e),
                citations=[citation(e.support[0])],
            )
            for i, e in enumerate(edges)
        ],
        safety_observations={
            "fixture_status": "Owner-authorized synthetic engineering test; "
            "no independent review or official admission."
        },
    )


@pytest.fixture
def path_case(tmp_path: Path) -> tuple[Path, Family, dict]:
    from pydantic import TypeAdapter
    from repovox.analysis.contracts import PAYLOADS
    from repovox.analysis.github import Snapshot
    from repovox.analysis.sandbox import execute
    from repovox.evaluation.corpus import checksum

    gold = authored_gold()  # No predictions exist when expected facts/verdicts are authored.
    source = tmp_path / "source"
    source.mkdir()
    for path, body in SOURCES.items():
        (source / path).write_bytes(body)
    snapshot = Snapshot(
        "example/gold-tooling",
        "https://github.com/example/gold-tooling",
        1,
        "example",
        "gold-tooling",
        True,
        "main",
        SHA,
        "2026-10-12T00:00:00Z",
    ).data()
    request = {
        "snapshot": snapshot,
        "snapshot_id": "11111111-1111-4111-8111-111111111111",
        "archive_hash": "b" * 64,
        "inputs": {},
    }
    result = {}
    for ordinal, kind in enumerate(
        ["filter", "structure", "entrypoints", "infer", "knowledge", "evidence", "verify"], 3
    ):
        result = execute(ordinal, source, request)
        TypeAdapter(PAYLOADS[kind]).validate_python(result)
        request["inputs"][str(ordinal)] = result
    manifest = serialize(result["knowledge"]["coverage"])
    (tmp_path / "source_manifest.json").write_bytes(manifest)
    family = Family(
        **gold.model_dump(),
        id="owner-synthetic-tooling",
        language_slice="python",
        split="TOOLING_FIXTURE",
        hidden=False,
        newly_owner_authored=False,
        derivatives=[],
        family_grouping_evidence_sha256=None,
        source_manifest_sha256=checksum(manifest),
        content_fingerprints=[],
        rights=Rights(
            basis="pending",
            license_id="UNAPPROVED TOOLING FIXTURE",
            license_text_sha256=None,
            permission_evidence_sha256=None,
            attribution="Engineering test only",
            retention_days=1,
            reviewer_access_permitted=False,
            redistribution_permitted=False,
            approved_by_owner=False,
        ),
        screening="pending",
        adversarial_variants=[],
        gold_review=None,
    )
    return source, family, result


def test_complete_serialization_validation_intake_load_and_score(path_case: tuple) -> None:
    source, family, prediction = path_case
    corpus = Corpus.model_validate_json(
        Path("docs/ai/evaluation-corpus.manifest.json").read_bytes()
    )
    corpus = intake(corpus, family, source)
    encoded = serialize(corpus.model_dump())
    schema = json.loads(Path("docs/ai/evaluation-corpus.schema.json").read_text())
    jsonschema.validate(json.loads(encoded), schema)
    loaded = Corpus.model_validate_json(encoded)
    report = score(loaded.families[0], json.loads(serialize(prediction)), source)
    assert report["pairing_status"] == "COMPLETE"
    assert report["acceptance_status"] == "REVIEW_REQUIRED"  # Never an official corpus PASS.
    assert report["claims"]["gold_count"] == report["claims"]["prediction_count"] == 12
    assert report["claims"]["matched_count"] == report["claims"]["correct_verdicts"] == 12
    assert (
        report["claims"]["gold_matching_coverage"]
        == report["claims"]["prediction_matching_coverage"]
        == 1
    )
    assert report["claims"]["false_verified_predictions"] == 0
    assert (
        report["claims"]["reviewed_verified_precision"] == report["claims"]["verified_recall"] == 1
    )
    assert report["claims"]["unsupported_rejection_recall"] is None
    for metric in ["graph", "import_graph", "symbols", "entrypoints"]:
        assert report[metric]["precision"] == report[metric]["recall"] == 1
    assert report["citations"] == {"denominator": 7, "valid": 7}
    assert all(p["gold_id"] != p["prediction_id"] for p in report["alignment"]["pairs"])
    assert json.loads(serialize(report)) == report
    standalone = GoldEvaluation.model_validate_json(
        serialize(family.model_dump(include=set(GoldEvaluation.model_fields)))
    )
    jsonschema.validate(
        standalone.model_dump(), json.loads(Path("docs/ai/gold-evaluation.schema.json").read_text())
    )
    assert score(standalone, prediction, source) == report
    assert score(json.loads(serialize(family.model_dump())), prediction, source) == report
    assert counts(loaded)["approved"] == 0 and loaded.status == "UNFROZEN"


@pytest.mark.parametrize("field", ["symbols", "entrypoints"])
def test_required_gold_inputs_are_not_silently_empty(field: str) -> None:
    data = authored_gold().model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        GoldEvaluation.model_validate_json(serialize(data))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            data, json.loads(Path("docs/ai/gold-evaluation.schema.json").read_text())
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-id",
        "missing-evidence",
        "bad-hash",
        "bad-range",
        "bad-type",
        "extra-field",
        "duplicate-fact",
    ],
)
def test_malformed_gold_annotations_are_rejected(mutation: str) -> None:
    data = authored_gold().model_dump()
    if mutation == "duplicate-id":
        data["claims"][1]["id"] = data["claims"][0]["id"]
    elif mutation == "missing-evidence":
        data["claims"][0]["citations"] = []
    elif mutation == "bad-hash":
        data["symbols"][0]["file_sha256"] = "invented"
    elif mutation == "bad-range":
        data["claims"][0]["citations"][0]["start_line"] = 100
    elif mutation == "bad-type":
        data["symbols"][0]["start_line"] = "1"
    elif mutation == "extra-field":
        data["claims"][0]["confidence_override"] = True
    else:
        data["claims"][1]["fact"] = deepcopy(data["claims"][0]["fact"])
        data["claims"][1]["citations"] = deepcopy(data["claims"][0]["citations"])
    with pytest.raises(ValidationError):
        GoldEvaluation.model_validate(data)


def test_changed_source_hash_rejects_evaluation(path_case: tuple) -> None:
    source, gold, prediction = path_case
    (source / "helper.py").write_bytes(b"# changed source\n")
    with pytest.raises(ValueError, match="gold_invalid_citation"):
        score(gold, prediction, source)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-claim",
        "duplicate-claim",
        "duplicate-verdict",
        "duplicate-symbol",
        "missing-evidence",
        "forged-evidence-id",
    ],
)
def test_invalid_prediction_references_reject_without_keyerrors(
    path_case: tuple, mutation: str
) -> None:
    source, gold, original = path_case
    prediction = deepcopy(original)
    if mutation == "unknown-claim":
        prediction["verification"]["verdicts"][0]["claim_id"] = "wrong-claim-identifier"
    elif mutation == "duplicate-claim":
        prediction["knowledge"]["claims"].append(deepcopy(prediction["knowledge"]["claims"][0]))
    elif mutation == "duplicate-verdict":
        prediction["verification"]["verdicts"].append(
            deepcopy(prediction["verification"]["verdicts"][0])
        )
    elif mutation == "duplicate-symbol":
        prediction["knowledge"]["symbols"].append(deepcopy(prediction["knowledge"]["symbols"][0]))
    elif mutation == "missing-evidence":
        prediction["knowledge"]["claims"][0]["evidence_ids"] = []
    else:
        claim = prediction["knowledge"]["claims"][0]
        claim["evidence_ids"] = ["invented-evidence"]
        next(v for v in prediction["verification"]["verdicts"] if v["claim_id"] == claim["id"])[
            "evidence_ids"
        ] = ["invented-evidence"]
    with pytest.raises(ValueError):
        score(gold, prediction, source)


def test_unmatched_predictions_and_partial_gold_are_incomplete(path_case: tuple) -> None:
    source, gold, prediction = path_case
    data = gold.model_dump(include=set(GoldEvaluation.model_fields))
    data["claims"] = data["claims"][:1]
    data["annotation_scope"] = "partial"
    report = score(data, prediction, source)
    assert report["acceptance_status"] == report["pairing_status"] == "INCOMPLETE"
    assert report["claims"]["matched_count"] == 1
    assert report["claims"]["unmatched_prediction_count"] == 11
    assert report["claims"]["gold_matching_coverage"] == 1
    assert report["claims"]["prediction_matching_coverage"] == 1 / 12
    assert report["claims"]["unscored_predictions_requiring_human_review"] == 11
    assert aggregate([report])["acceptance_status"] == "INCOMPLETE"
    data["annotation_scope"] = "complete"  # Self-reported completeness cannot bypass pairing.
    assert score(data, prediction, source)["acceptance_status"] == "INCOMPLETE"


def test_zero_matches_are_never_an_acceptance_success(path_case: tuple) -> None:
    source, gold, original = path_case
    prediction = deepcopy(original)
    for claim in prediction["knowledge"]["claims"]:
        claim["text"] = "The application has successfully executed and is secure."
    report = score(gold, prediction, source)
    assert report["claims"]["matched_count"] == 0
    assert report["claims"]["gold_matching_coverage"] == 0
    assert report["claims"]["prediction_matching_coverage"] == 0
    assert report["claims"]["reviewed_verified_precision"] is None
    assert report["claims"]["unscored_predictions_requiring_human_review"] == 12
    assert report["acceptance_status"] == "INCOMPLETE"
    assert aggregate([])["acceptance_status"] == "INCOMPLETE"


def test_gold_ids_cannot_force_pairing_to_a_different_fact(path_case: tuple) -> None:
    source, gold, prediction = path_case
    data = gold.model_dump(include=set(GoldEvaluation.model_fields))
    # Deliberately corrupt a test annotation, even giving it an actual predicted ID.
    data["claims"][0]["id"] = prediction["knowledge"]["claims"][0]["id"]
    data["claims"][0]["fact"]["symbol"]["name"] = "wrong-symbol"
    report = score(data, prediction, source)
    assert report["claims"]["matched_count"] == 11
    assert report["claims"]["unmatched_gold_count"] == 1
    assert report["acceptance_status"] == "INCOMPLETE"


def test_prediction_ids_can_change_without_changing_alignment(path_case: tuple) -> None:
    source, gold, original = path_case
    prediction = deepcopy(original)
    ids = {
        c["id"]: f"independent-prediction-{i}"
        for i, c in enumerate(prediction["knowledge"]["claims"])
    }
    for claim in prediction["knowledge"]["claims"]:
        claim["id"] = ids[claim["id"]]
    for verdict in prediction["verification"]["verdicts"]:
        verdict["claim_id"] = ids[verdict["claim_id"]]
    assert score(gold, prediction, source)["claims"] == score(gold, original, source)["claims"]


def test_unmatched_gold_is_counted_and_incomplete(path_case: tuple) -> None:
    source, gold, original = path_case
    prediction = deepcopy(original)
    omitted = prediction["knowledge"]["claims"].pop()["id"]
    prediction["verification"]["verdicts"] = [
        v for v in prediction["verification"]["verdicts"] if v["claim_id"] != omitted
    ]
    report = score(gold, prediction, source)
    assert report["claims"]["unmatched_gold_count"] == 1
    assert report["claims"]["unmatched_prediction_count"] == 0
    assert report["claims"]["gold_matching_coverage"] == 11 / 12
    assert report["claims"]["prediction_matching_coverage"] == 1
    assert report["pairing_status"] == report["acceptance_status"] == "INCOMPLETE"


def test_duplicate_facts_with_distinct_prediction_ids_are_ambiguous(path_case: tuple) -> None:
    source, gold, original = path_case
    prediction = deepcopy(original)
    claim = deepcopy(prediction["knowledge"]["claims"][0])
    prior_id = claim["id"]
    claim["id"] = "duplicate-fact-different-id"
    prediction["knowledge"]["claims"].append(claim)
    verdict = deepcopy(
        next(v for v in prediction["verification"]["verdicts"] if v["claim_id"] == prior_id)
    )
    verdict["claim_id"] = claim["id"]
    prediction["verification"]["verdicts"].append(verdict)
    report = score(gold, prediction, source)
    assert report["claims"]["matched_count"] == 11
    assert report["claims"]["unscored_predictions_requiring_human_review"] == 2
    assert report["pairing_status"] == "INCOMPLETE"


@pytest.mark.parametrize("mutation", ["wrong-sha", "invented-path", "changed-hash", "wrong-range"])
def test_invalid_predicted_source_is_not_scored_as_valid(path_case: tuple, mutation: str) -> None:
    source, gold, original = path_case
    prediction = deepcopy(original)
    item = prediction["evidence"]["items"][0]
    if mutation == "wrong-sha":
        item["commit_sha"] = "b" * 40
    elif mutation == "invented-path":
        item["path"] = "invented.py"
    elif mutation == "changed-hash":
        item["file_sha256"] = "b" * 64
    else:
        item["end_line"] = 999
    if mutation == "wrong-sha":
        assert score(gold, prediction, source)["acceptance_status"] == "INCOMPLETE"
    else:
        with pytest.raises(ValueError, match="prediction_evidence_symbol_mismatch"):
            score(gold, prediction, source)


def test_empty_annotations_do_not_pass(path_case: tuple) -> None:
    source, gold, prediction = path_case
    data = gold.model_dump(include=set(GoldEvaluation.model_fields))
    data["claims"] = []
    report = score(data, prediction, source)
    assert report["claims"]["gold_matching_coverage"] is None
    assert report["claims"]["prediction_matching_coverage"] == 0
    assert report["acceptance_status"] == "INCOMPLETE"


def add_manual_hard_negative(gold: Family, prediction: dict, status: str) -> tuple[dict, dict]:
    """Known source lacks ghost(). Expected unsupported is authored independently of status."""
    import hashlib

    assertion = SymbolIdentity(
        path="main.py",
        file_sha256=hashlib.sha256(SOURCES["main.py"]).hexdigest(),
        start_line=2,
        end_line=3,
        kind="function",
        name="ghost",
        language="python",
        rule="declaration-v1",
        attributes=Attributes(parameters=["value"]),
    )
    citation = assertion.model_dump(include=set(Citation.model_fields))
    data = gold.model_dump(include=set(GoldEvaluation.model_fields))
    data["claims"].append(
        GoldClaim(
            id="manual-hard-negative",
            text="The cited source does not declare ghost().",
            status="unsupported",
            fact=SymbolFact(type="symbol_syntax", symbol=assertion),
            citations=[Citation(**citation)],
        ).model_dump()
    )
    result = deepcopy(prediction)
    result["knowledge"]["symbols"].append(
        {
            "id": "fabricated-ghost-symbol",
            **citation,
            "kind": "function",
            "name": "ghost",
            "parser_language": "python",
            "rule": "declaration-v1",
            "parameters": ["value"],
        }
    )
    result["evidence"]["items"].append(
        {
            "id": "fabricated-ghost-evidence",
            **citation,
            "commit_sha": SHA,
            "symbol_id": "fabricated-ghost-symbol",
        }
    )
    result["knowledge"]["claims"].append(
        {
            "id": "prediction-ghost-claim",
            "text": "main.py contains function syntax named ghost.",
            "status": status,
            "rule": "symbol-fact-v1",
            "subject_id": "fabricated-ghost-symbol",
            "evidence_ids": ["fabricated-ghost-evidence"],
        }
    )
    result["verification"]["verdicts"].append(
        {
            "claim_id": "prediction-ghost-claim",
            "status": status,
            "rule": "symbol-fact-v1",
            "evidence_ids": ["fabricated-ghost-evidence"],
        }
    )
    return data, result


@pytest.mark.parametrize("verdict", ["verified", "unsupported"])
def test_false_verified_and_unsupported_rejection_against_manual_gold(
    path_case: tuple, verdict: str
) -> None:
    source, gold, original = path_case
    data, prediction = add_manual_hard_negative(gold, original, verdict)
    report = score(data, prediction, source)
    assert report["claims"]["gold_count"] == report["claims"]["prediction_count"] == 13
    assert report["claims"]["matched_count"] == 13
    assert report["claims"]["gold_unsupported_count"] == 1
    assert report["claims"]["false_verified_predictions"] == (1 if verdict == "verified" else 0)
    assert report["claims"]["unsupported_rejected"] == (0 if verdict == "verified" else 1)
    assert report["claims"]["unsupported_rejection_recall"] == (0 if verdict == "verified" else 1)
    assert report["claims"]["reviewed_verified_precision"] == (
        11 / 12 if verdict == "verified" else 1
    )
    assert report["acceptance_status"] == (
        "REJECTED" if verdict == "verified" else "REVIEW_REQUIRED"
    )
    assert GoldEvaluation.model_validate(data).claims[-1].status == "unsupported"
    rollup = aggregate([report, score(gold, original, source)])
    assert rollup["claims"]["gold_count"] == 25
    assert (
        rollup["claims"]["false_verified_predictions"]
        == report["claims"]["false_verified_predictions"]
    )
    assert rollup["acceptance_status"] == report["acceptance_status"]

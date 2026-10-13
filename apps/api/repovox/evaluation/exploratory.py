"""Blind source packets and sealed exploratory predictions; never official corpus gold."""

import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from pydantic import Field, model_validator

from repovox.analysis.privacy import redact
from repovox.evaluation.corpus import checksum, serialize
from repovox.evaluation.gold import (
    SHA,
    Citation,
    GoldEvaluation,
    Hash,
    Record,
    validate_gold_source,
)

TRACK = "AI_AUDITED_EXPLORATORY"


class Policy(Record):
    track: Literal["AI_AUDITED_EXPLORATORY"] = "AI_AUDITED_EXPLORATORY"
    reviewer_role: Literal["INDEPENDENT_AI_TECHNICAL_REVIEWER"] = (
        "INDEPENDENT_AI_TECHNICAL_REVIEWER"
    )
    independently_human_reviewed: Literal[False] = False
    official_eval_entry_contribution: Literal[False] = False
    held_out_benchmark: Literal[False] = False
    full_corpus_freeze: Literal[False] = False
    production_accuracy_certification: Literal[False] = False
    training_authorized: Literal[False] = False


class SourceExcerpt(Citation):
    bytes: int = Field(ge=0)
    language: str
    numbered_excerpt: str
    redactions: list[dict[str, int | str]]
    permalink: str


class BlindPacket(Record):
    schema_version: Literal["exploratory-blind-source-1.0"]
    policy: Policy
    repository: str
    commit_sha: SHA
    rights_evidence_sha256: Hash
    rights_summary: str
    inventory: list[dict[str, str | int]]
    excerpts: list[SourceExcerpt]
    eligible_language_files: dict[str, int]
    selected_source_bytes: int
    whole_eligible_source_bytes: int
    limitations: list[str]

    @model_validator(mode="after")
    def source_only(self) -> "BlindPacket":
        allowed = {"path", "file_sha256", "bytes", "language", "classification", "status", "reason"}
        if not self.excerpts or any(set(item) != allowed for item in self.inventory):
            raise ValueError("blind_source_inventory_only")
        if len({e.path for e in self.excerpts}) != len(self.excerpts):
            raise ValueError("duplicate_blind_scope")
        return self


class Observation(Record):
    assertion: str = Field(min_length=1)
    expected_status: Literal[
        "verified", "inferred", "documentation_only", "unsupported", "unreviewed"
    ]
    citations: list[Citation] = Field(min_length=1)


class AIReference(Record):
    schema_version: Literal["exploratory-ai-reference-1.0"]
    policy: Policy
    reviewer: Literal["ChatGPT"]
    blind_packet_sha256: Hash
    prediction_packet_sha256: Hash
    response_capture_sha256: Hash
    gold: GoldEvaluation
    semantic_observations: list[Observation]
    limitations: list[str]
    revision: int = Field(default=1, ge=1)
    supersedes_sha256: Hash | None = None
    correction_explanation: str | None = None
    correction_citations: list[Citation] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_empty_reference(self) -> "AIReference":
        if not self.gold.claims:
            raise ValueError("independent_source_assertions_required")
        if self.revision > 1 and not (
            self.supersedes_sha256 and self.correction_explanation and self.correction_citations
        ):
            raise ValueError("reference_correction_lineage_required")
        return self


class PredictionPacket(Record):
    schema_version: Literal["exploratory-sealed-prediction-1.0"]
    policy: Policy
    repository: str
    commit_sha: SHA
    rights_evidence_sha256: Hash
    selected_scope: list[dict[str, str | int]]
    original_artifacts: list[dict[str, str | int]]
    verified_payload: dict[str, Any]
    metrics: dict[str, Any]
    reference_included: Literal[False] = False

    @model_validator(mode="after")
    def pinned_prediction(self) -> "PredictionPacket":
        snapshot = self.verified_payload["knowledge"]["repository"]
        if snapshot["repository"] != self.repository or snapshot["commit_sha"] != self.commit_sha:
            raise ValueError("prediction_snapshot_mismatch")
        if not self.selected_scope or any(
            set(s) != {"path", "start_line", "end_line"} for s in self.selected_scope
        ):
            raise ValueError("prediction_scope_required")
        return self


def write_immutable(root: Path, name: str, body: bytes) -> str:
    """Exclusive files plus digests detect edits; not a claim of administrator-proof WORM."""
    from repovox.analysis.archive import safe_path

    relative = safe_path(name)
    destination = root / str(relative)
    if root.is_symlink() or not destination.resolve().is_relative_to(root.resolve()):
        raise ValueError("exploratory_store_containment")
    for parent in reversed(destination.parents):
        if parent == root or parent.is_relative_to(root):
            parent.mkdir(mode=0o700, exist_ok=True)
    if any(p.is_symlink() for p in [destination, *destination.parents]):
        raise ValueError("exploratory_store_symlink")
    with destination.open("xb") as target:
        if os.name == "posix":
            os.chmod(destination, 0o600)
        target.write(body)
    return checksum(body)


def checked_bytes(root: Path, name: str, digest: str) -> bytes:
    from repovox.analysis.archive import safe_path

    destination = root / str(safe_path(name))
    if destination.is_symlink() or not destination.resolve().is_relative_to(root.resolve()):
        raise ValueError("sealed_file_containment")
    body = destination.read_bytes()
    if checksum(body) != digest:
        raise ValueError("sealed_content_changed")
    return body


def validate_pinned_tree(source: Path, tree: dict[str, Any]) -> None:
    """Compare acquired bytes with Git's individually inspected immutable blob inventory."""
    if tree.get("truncated") or any(i["type"] == "commit" for i in tree["tree"]):
        raise ValueError("incomplete_or_submodule_tree")
    expected = {i["path"]: i["sha"] for i in tree["tree"] if i["type"] == "blob"}
    actual = {p.relative_to(source).as_posix(): p for p in source.rglob("*") if p.is_file()}
    if set(actual) != set(expected):
        raise ValueError("acquired_tree_inventory_changed")
    for name, path in actual.items():
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError("acquired_tree_containment")
        body = path.read_bytes()
        if hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest() != expected[name]:
            raise ValueError("pinned_source_blob_changed")


def restrict_source_scope(manifest: dict[str, Any], selected: frozenset[str]) -> dict[str, Any]:
    """Exploratory opt-in only, after all-file security screening; original hashes retained."""
    result = deepcopy(manifest)
    available = {i["path"] for i in result["files"] if i["status"] in {"eligible", "context"}}
    if not selected or selected - available:
        raise ValueError("exploratory_scope_missing_or_excluded")
    for item in result["files"]:
        if item["path"] not in selected and item["status"] in {"eligible", "context"}:
            item.update(status="skipped", reason="AI_AUDITED_EXPLORATORY_outside_selected_scope")
    result["eligible_bytes"] = sum(i["bytes"] for i in result["files"] if i["status"] == "eligible")
    result["eligible_files"] = sum(i["status"] == "eligible" for i in result["files"])
    result["excluded_bytes"] = sum(i["bytes"] for i in result["files"] if i["status"] == "skipped")
    return result


def blind_packet(
    source: Path,
    repository: str,
    sha: str,
    manifest: dict[str, Any],
    rights: dict[str, Any],
    selected: dict[str, tuple[int, int | None]],
) -> BlindPacket:
    """Only source/filter/rights inputs accepted; no prediction bundle enters this function."""
    if manifest["repository"] != repository or manifest["commit_sha"] != sha:
        raise ValueError("blind_snapshot_mismatch")
    if rights["repository"] != repository or rights["commit_sha"] != sha:
        raise ValueError("blind_rights_snapshot_mismatch")
    if rights["decision"] != "PERMITTED_INTERNAL_EXPLORATORY":
        raise ValueError("exploratory_rights_required")
    files = {item["path"]: item for item in manifest["files"]}
    excerpts = []
    for path, (start, requested_end) in selected.items():
        item = files.get(path)
        if item is None or item["status"] not in {"eligible", "context"}:
            raise ValueError("blind_scope_missing_or_excluded")
        candidate = source / path
        if candidate.is_symlink() or not candidate.resolve().is_relative_to(source.resolve()):
            raise ValueError("blind_source_containment")
        body = candidate.read_bytes()
        if checksum(body) != item["file_sha256"]:
            raise ValueError("blind_source_changed")
        lines = body.decode("utf-8").split("\n")
        end = requested_end if requested_end is not None else len(lines)
        if not 1 <= start <= end <= len(lines):
            raise ValueError("blind_source_range")
        excerpt, redactions = redact("\n".join(lines[start - 1 : end]))
        excerpts.append(
            SourceExcerpt(
                path=path,
                file_sha256=item["file_sha256"],
                start_line=start,
                end_line=end,
                bytes=len(body),
                language=item["language"],
                numbered_excerpt="\n".join(
                    f"{i}: {line}" for i, line in enumerate(excerpt.split("\n"), start)
                ),
                redactions=redactions,
                permalink=(
                    f"https://github.com/{repository}/blob/{sha}/"
                    f"{quote(path, safe='/')}#L{start}-L{end}"
                ),
            )
        )
    language_files: dict[str, int] = {}
    for item in files.values():
        if item["status"] == "eligible":
            language_files[item["language"]] = language_files.get(item["language"], 0) + 1
    return BlindPacket(
        schema_version="exploratory-blind-source-1.0",
        policy=Policy(),
        repository=repository,
        commit_sha=sha,
        rights_evidence_sha256=checksum(serialize(rights)),
        rights_summary=rights["summary"],
        inventory=[
            {
                key: item[key]
                for key in [
                    "path",
                    "file_sha256",
                    "bytes",
                    "language",
                    "classification",
                    "status",
                    "reason",
                ]
            }
            for item in manifest["files"]
        ],
        excerpts=excerpts,
        eligible_language_files=language_files,
        selected_source_bytes=sum(
            files[path]["bytes"] for path in selected if files[path]["status"] == "eligible"
        ),
        whole_eligible_source_bytes=manifest["eligible_bytes"],
        limitations=[
            "Source inventory/eligibility is not parser success or independent correctness.",
            "Selected source scope is not whole-repository coverage or a held-out benchmark.",
            "Original hashes apply to full original files, not redacted numbered excerpts.",
            "Redacted or inaccessible assertions must remain unreviewed; do not infer execution.",
            "No analyzer claims, verdicts, predictions, scores or answer keys are supplied.",
        ],
    )


def seal_packet(
    root: Path, kind: Literal["A", "B", "REFERENCE"], value: dict[str, Any]
) -> dict[str, str]:
    if kind == "A":
        value = BlindPacket.model_validate(value).model_dump()
    elif kind == "B":
        value = PredictionPacket.model_validate(value).model_dump()
    else:
        reference = AIReference.model_validate(value)
        for letter, digest in [
            ("a", reference.blind_packet_sha256),
            ("b", reference.prediction_packet_sha256),
        ]:
            checked_bytes(root, f"sealed/package-{letter}-{digest}.json", digest)
        checked_bytes(
            root,
            f"review/response-{reference.response_capture_sha256}.txt",
            reference.response_capture_sha256,
        )
        events = [
            json.loads((root / f"events/{letter}-{digest}.json").read_bytes())
            for letter, digest in [
                ("a", reference.blind_packet_sha256),
                ("b", reference.prediction_packet_sha256),
            ]
        ]
        capture = json.loads((root / "review/capture-event.json").read_bytes())
        if capture["sha256"] != reference.response_capture_sha256 or any(
            e["recorded_at"] > capture["recorded_at"] for e in events
        ):
            raise ValueError("blind_review_chronology_invalid")
        prior = list((root / "events").glob("reference-*.json"))
        if prior:
            if not reference.supersedes_sha256 or reference.revision == 1:
                raise ValueError("reference_correction_lineage_required")
            digest = reference.supersedes_sha256
            previous = AIReference.model_validate_json(
                checked_bytes(root, f"sealed/package-reference-{digest}.json", digest)
            )
            if (
                reference.revision != previous.revision + 1
                or reference.blind_packet_sha256 != previous.blind_packet_sha256
                or reference.prediction_packet_sha256 != previous.prediction_packet_sha256
            ):
                raise ValueError("reference_correction_snapshot_mismatch")
        value = reference.model_dump()
    if kind in {"A", "B"} and list((root / "events").glob(f"{kind.lower()}-*.json")):
        raise ValueError("packet_already_sealed")
    body = serialize(value)
    digest = checksum(body)
    name = f"sealed/package-{kind.lower()}-{digest}.json"
    write_immutable(root, name, body)
    event = {
        "schema_version": "exploratory-seal-event-1.0",
        "track": TRACK,
        "kind": kind,
        "sha256": digest,
        "path": name,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    write_immutable(root, f"events/{kind.lower()}-{digest}.json", serialize(event))
    return {"sha256": digest, "path": name, "event_sha256": checksum(serialize(event))}


def capture_response(root: Path, body: bytes) -> str:
    """Record owner's supplied raw review. Digest/clock prove bytes/order, not AI identity."""
    from repovox.analysis.privacy import screen_bytes

    screen_bytes(body)
    if not body.strip() or not all(list((root / "events").glob(f"{k}-*.json")) for k in ["a", "b"]):
        raise ValueError("sealed_blind_handoff_required")
    digest = checksum(body)
    write_immutable(root, f"review/response-{digest}.txt", body)
    write_immutable(
        root,
        "review/capture-event.json",
        serialize(
            {
                "sha256": digest,
                "recorded_at": datetime.now(UTC).isoformat(),
                "identity_authenticated_by_hash": False,
            }
        ),
    )
    return digest


def scoped_prediction(payload: dict[str, Any], packet: BlindPacket) -> dict[str, Any]:
    """Project supported files/ranges; never edit the previously sealed original."""
    from repovox.evaluation.scoring import Prediction, unique

    parsed = Prediction.model_validate(payload)
    symbols_by_id = unique(parsed.knowledge.symbols)
    edges_by_id = unique(parsed.knowledge.edges)
    evidence_by_id = unique(parsed.evidence.items)
    claims_by_id = unique(parsed.knowledge.claims)
    unique(parsed.verification.verdicts, "claim_id")
    if (
        any(
            {e.source, e.target, *e.support_ids} - symbols_by_id.keys()
            for e in parsed.knowledge.edges
        )
        or any(e.symbol_id not in symbols_by_id for e in parsed.evidence.items)
        or any(
            c.subject_id not in symbols_by_id
            and c.subject_id not in edges_by_id
            or set(c.evidence_ids) - evidence_by_id.keys()
            for c in parsed.knowledge.claims
        )
        or any(
            v.claim_id not in claims_by_id or set(v.evidence_ids) - evidence_by_id.keys()
            for v in parsed.verification.verdicts
        )
    ):
        raise ValueError("prediction_reference_invalid_before_scope")
    result = deepcopy(payload)
    ranges = {e.path: (e.start_line, e.end_line) for e in packet.excerpts}

    def included(item: dict[str, Any]) -> bool:
        window = ranges.get(item["path"])
        return bool(window and window[0] <= item["start_line"] <= item["end_line"] <= window[1])

    knowledge = result["knowledge"]
    symbols = [s for s in knowledge["symbols"] if included(s)]
    symbol_ids = {s["id"] for s in symbols}
    edges = [
        e for e in knowledge["edges"] if {e["source"], e["target"], *e["support_ids"]} <= symbol_ids
    ]
    subjects = symbol_ids | {e["id"] for e in edges}
    evidence = [e for e in result["evidence"]["items"] if e["symbol_id"] in symbol_ids]
    evidence_ids = {e["id"] for e in evidence}
    claims = [
        c
        for c in knowledge["claims"]
        if c["subject_id"] in subjects and set(c["evidence_ids"]) <= evidence_ids
    ]
    knowledge["symbols"], knowledge["edges"], knowledge["claims"] = symbols, edges, claims
    knowledge["entrypoints"]["candidates"] = [
        c
        for c in knowledge["entrypoints"]["candidates"]
        if c["path"] in ranges and {c["symbol_id"], *c["support_ids"]} <= symbol_ids
    ]
    result["evidence"]["items"] = evidence
    claim_ids = {c["id"] for c in claims}
    result["verification"]["verdicts"] = [
        v for v in result["verification"]["verdicts"] if v["claim_id"] in claim_ids
    ]
    return result


def compare_reference(
    reference: AIReference,
    packet: BlindPacket,
    prediction: PredictionPacket,
    source: Path,
    sealed_store: Path,
) -> dict[str, Any]:
    """Call accepted scorer unchanged. Reference capture/chronology must be sealed separately."""
    from repovox.evaluation.scoring import score

    reference = AIReference.model_validate(reference.model_dump())
    digest = checksum(serialize(reference.model_dump()))
    checked_bytes(sealed_store, f"sealed/package-reference-{digest}.json", digest)
    checked_bytes(
        sealed_store,
        f"review/response-{reference.response_capture_sha256}.txt",
        reference.response_capture_sha256,
    )
    if (
        reference.blind_packet_sha256 != checksum(serialize(packet.model_dump()))
        or reference.prediction_packet_sha256 != checksum(serialize(prediction.model_dump()))
        or reference.gold.repository != packet.repository
        or reference.gold.commit_sha != packet.commit_sha
    ):
        raise ValueError("independent_reference_snapshot_mismatch")
    validate_gold_source(reference.gold, source)
    ranges = {e.path: e for e in packet.excerpts}

    def within(item: Citation) -> bool:
        scope = ranges.get(item.path)
        return bool(
            scope
            and item.file_sha256 == scope.file_sha256
            and scope.start_line <= item.start_line <= item.end_line <= scope.end_line
        )

    cited = [*reference.gold.symbols, *reference.correction_citations]
    for entry in reference.gold.entrypoints:
        cited.extend(entry.citations)
    for edge in reference.gold.edges:
        cited.extend([edge.source, edge.target, *edge.support, *edge.citations])
    for claim in reference.gold.claims:
        cited.extend(claim.citations)
    for observation in reference.semantic_observations:
        cited.extend(observation.citations)
    if not all(within(c) for c in cited):
        raise ValueError("independent_reference_outside_blind_scope")
    for observation in reference.semantic_observations:
        from repovox.evaluation.gold import source_valid

        if not all(source_valid(c, source) for c in observation.citations):
            raise ValueError("independent_observation_citation_invalid")
    report = score(reference.gold, scoped_prediction(prediction.verified_payload, packet), source)
    return {
        "schema_version": "exploratory-comparison-1.0",
        "policy": Policy().model_dump(),
        "score": report,
        "semantic_observations": "REQUIRE_SEPARATE_SOURCE_REVIEW",
        "independent_acceptance": "REVIEW_REQUIRED",
    }

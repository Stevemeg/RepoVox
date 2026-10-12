import hashlib
import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def serialize(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def checksum(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Rights(Record):
    basis: Literal[
        "owner_authored", "explicit_evaluation_permission", "license_reviewed", "pending"
    ]
    license_id: str
    license_text_sha256: Hash | None
    permission_evidence_sha256: Hash | None
    attribution: str
    retention_days: int = Field(ge=1, le=365)
    reviewer_access_permitted: bool
    redistribution_permitted: bool
    approved_by_owner: bool


class Appointment(Record):
    reviewer_id: str
    type: Literal["actual_human"]
    owner_appointment_sha256: Hash
    rights_access_sha256: Hash


class GoldReview(Record):
    preparer_id: str
    reviewer_id: str
    source_review_sha256: Hash
    adjudication_sha256: Hash
    approval_evidence_sha256: Hash
    approved: bool


class Citation(Record):
    path: str
    file_sha256: Hash
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class GoldClaim(Record):
    id: str
    text: str
    status: Literal["verified", "inferred", "documentation_only", "unsupported"]
    citations: list[Citation]


class GoldEdge(Record):
    source: str
    target: str
    relationship: str
    supported: bool
    citations: list[Citation]


class Family(Record):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,79}$")
    repository: str
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    language_slice: Literal["python", "javascript_typescript", "mixed"]
    split: Literal["TOOLING_FIXTURE", "EVAL_DEV", "EVAL_TEST"]
    hidden: bool
    newly_owner_authored: bool
    derivatives: list[str]
    family_grouping_evidence_sha256: Hash | None
    source_manifest_sha256: Hash
    content_fingerprints: list[Hash]
    rights: Rights
    screening: Literal["pending", "clear", "rejected"]
    claims: list[GoldClaim]
    edges: list[GoldEdge]
    adversarial_variants: list[str]
    gold_review: GoldReview | None
    withdrawn: bool = False


class Corpus(Record):
    version: str
    status: Literal["UNFROZEN", "FROZEN", "WITHDRAWN"]
    reviewer_status: str
    appointment: Appointment | None
    families: list[Family]
    access_policy_sha256: Hash | None
    contamination_manifest_sha256: Hash | None
    deletion_policy_sha256: Hash | None
    freeze_sha256: Hash | None
    dependent_reports: list[str]
    invalidated_reports: list[str]

    @model_validator(mode="after")
    def immutable_freeze_hash(self) -> "Corpus":
        if self.status == "FROZEN":
            expected = checksum(serialize(self.model_dump(exclude={"freeze_sha256"})))
            if self.freeze_sha256 != expected or self.appointment is None:
                raise ValueError("invalid_frozen_manifest")
        return self


def counts(corpus: Corpus) -> dict[str, int]:
    families = [f for f in corpus.families if f.split != "TOOLING_FIXTURE" and not f.withdrawn]
    approved = [f for f in families if permitted(f) and f.gold_review and f.gold_review.approved]
    return {
        "candidates": len(families),
        "approved": len(approved),
        "tooling_fixtures": sum(f.split == "TOOLING_FIXTURE" for f in corpus.families),
        "development": sum(f.split == "EVAL_DEV" for f in approved),
        "held_out": sum(f.split == "EVAL_TEST" for f in approved),
        "hidden_owner_authored": sum(
            f.split == "EVAL_TEST" and f.hidden and f.newly_owner_authored for f in approved
        ),
        "python": sum(f.split == "EVAL_TEST" and f.language_slice == "python" for f in approved),
        "javascript_typescript": sum(
            f.split == "EVAL_TEST" and f.language_slice == "javascript_typescript" for f in approved
        ),
        "mixed": sum(f.split == "EVAL_TEST" and f.language_slice == "mixed" for f in approved),
        "adversarial_variants": sum(
            len(f.adversarial_variants) for f in approved if f.split == "EVAL_TEST"
        ),
        "gold_claims": sum(sum(bool(c.citations) for c in f.claims) for f in approved),
        "supported_gold_edges": sum(sum(e.supported for e in f.edges) for f in approved),
    }


def permitted(family: Family) -> bool:
    rights = family.rights
    return bool(
        rights.basis != "pending"
        and rights.permission_evidence_sha256
        and rights.approved_by_owner
        and rights.reviewer_access_permitted
        and (rights.basis == "owner_authored" or rights.license_text_sha256)
    )


def validate_labels(family: Family, source: Path) -> None:
    citations = [c for claim in family.claims for c in claim.citations] + [
        c for edge in family.edges for c in edge.citations
    ]
    if len({c.id for c in family.claims}) != len(family.claims):
        raise ValueError("duplicate_gold_id")
    for claim in family.claims:
        if claim.status != "unsupported" and not claim.citations:
            raise ValueError("gold_missing_source")
    for edge in family.edges:
        if edge.supported and not edge.citations:
            raise ValueError("edge_missing_source")
    for citation in citations:
        path = (source / citation.path).resolve()
        if not path.is_relative_to(source.resolve()) or not path.is_file() or path.is_symlink():
            raise ValueError("gold_invalid_path")
        body = path.read_bytes()
        lines = body.split(b"\n")
        if checksum(
            body
        ) != citation.file_sha256 or not 1 <= citation.start_line <= citation.end_line <= len(
            lines
        ):
            raise ValueError("gold_invalid_citation")
    # Entailment still requires the appointed human; hash/range validity does not approve labels.


def intake(corpus: Corpus, family: Family, source: Path) -> Corpus:
    if corpus.status != "UNFROZEN" or any(f.id == family.id for f in corpus.families):
        raise ValueError("intake_requires_new_unfrozen_family")
    from repovox.analysis.filtering import filter_sources

    manifest_path = source.parent / "source_manifest.json"
    original = manifest_path.read_bytes()
    if checksum(original) != family.source_manifest_sha256:
        raise ValueError("source_manifest_hash_mismatch")
    manifest = json.loads(original)
    if manifest["commit_sha"] != family.commit_sha:
        raise ValueError("source_manifest_sha_mismatch")
    screened = filter_sources(
        source, manifest["repository"], family.commit_sha, manifest["archive_sha256"]
    )
    expected = {(f["path"], f["file_sha256"], f["bytes"]) for f in manifest["files"]}
    actual = {(f["path"], f["file_sha256"], f["bytes"]) for f in screened["files"]}
    if expected != actual:
        raise ValueError("intake_source_changed")
    candidate = family.model_copy(deep=True)
    candidate.screening = "clear"
    candidate.content_fingerprints = sorted(
        {
            f["file_sha256"]
            for f in screened["files"]
            if f["bytes"] >= 64 and f["status"] == "eligible"
        }
    )
    validate_labels(candidate, source)
    result = corpus.model_copy(deep=True)
    result.families.append(candidate)
    return result


def freeze(
    corpus: Corpus, sources: dict[str, Path] | None = None, provenance: Path | None = None
) -> Corpus:
    if corpus.status != "UNFROZEN" or corpus.appointment is None:
        raise ValueError("independent_human_appointment_required")
    if not all(
        [
            corpus.access_policy_sha256,
            corpus.contamination_manifest_sha256,
            corpus.deletion_policy_sha256,
        ]
    ):
        raise ValueError("custodian_manifests_required")
    if sources is None or provenance is None:
        raise ValueError("actual_source_and_provenance_required")

    def proof(value: str | None) -> None:
        if value is None:
            raise ValueError("provenance_missing")
        path = provenance / value
        if not path.is_file() or path.is_symlink() or checksum(path.read_bytes()) != value:
            raise ValueError("provenance_hash_mismatch")

    for value in [
        corpus.appointment.owner_appointment_sha256,
        corpus.appointment.rights_access_sha256,
        corpus.access_policy_sha256,
        corpus.contamination_manifest_sha256,
        corpus.deletion_policy_sha256,
    ]:
        proof(value)
    seen_ids: set[str] = set()
    seen_fingerprints: dict[str, str] = {}
    variants: set[str] = set()
    for family in corpus.families:
        if family.split == "TOOLING_FIXTURE":
            continue
        if family.id in seen_ids or any(d in seen_ids for d in family.derivatives):
            raise ValueError("family_overlap")
        seen_ids.update([family.id, *family.derivatives])
        if not permitted(family) or family.screening != "clear" or family.withdrawn:
            raise ValueError("rights_or_screening_incomplete")
        review = family.gold_review
        if (
            review is None
            or not review.approved
            or review.preparer_id == review.reviewer_id
            or review.reviewer_id != corpus.appointment.reviewer_id
        ):
            raise ValueError("independent_gold_review_required")
        if not family.family_grouping_evidence_sha256:
            raise ValueError("family_grouping_review_required")
        source = sources.get(family.id)
        if source is None:
            raise ValueError("actual_gold_source_required")
        validate_labels(family, source)
        manifest = source.parent / "source_manifest.json"
        if (
            not manifest.is_file()
            or checksum(manifest.read_bytes()) != family.source_manifest_sha256
        ):
            raise ValueError("source_manifest_hash_mismatch")
        source_metadata = json.loads(manifest.read_bytes())
        if source_metadata["commit_sha"] != family.commit_sha:
            raise ValueError("source_manifest_sha_mismatch")
        for value in [
            family.rights.permission_evidence_sha256,
            family.family_grouping_evidence_sha256,
            review.source_review_sha256,
            review.adjudication_sha256,
            review.approval_evidence_sha256,
        ]:
            proof(value)
        if family.rights.license_text_sha256:
            proof(family.rights.license_text_sha256)
        for fingerprint in family.content_fingerprints:
            prior = seen_fingerprints.get(fingerprint)
            if prior and prior != family.id:
                raise ValueError("contamination_or_family_overlap")
            seen_fingerprints[fingerprint] = family.id
        for variant in family.adversarial_variants:
            if variant in variants:
                raise ValueError("duplicate_variant")
            variants.add(variant)
    target = {
        "development": 20,
        "held_out": 60,
        "hidden_owner_authored": 10,
        "python": 20,
        "javascript_typescript": 20,
        "mixed": 20,
        "adversarial_variants": 100,
        "gold_claims": 600,
        "supported_gold_edges": 120,
    }
    actual = counts(corpus)
    if any(actual[key] < minimum for key, minimum in target.items()):
        raise ValueError("eval_entry_counts_incomplete")
    if sum(bool(f.adversarial_variants) for f in corpus.families if f.split == "EVAL_TEST") < 20:
        raise ValueError("adversarial_family_coverage_incomplete")
    result = corpus.model_copy(deep=True)
    result.status = "FROZEN"
    result.freeze_sha256 = checksum(serialize(result.model_dump(exclude={"freeze_sha256"})))
    return result


def allowed(split: str, purpose: str, frozen: bool, registered: bool = False) -> bool:
    if purpose in {"training", "calibration"}:
        return False
    if split == "EVAL_TEST":
        return purpose == "registered_final_evaluation" and frozen and registered
    return split in {"TOOLING_FIXTURE", "EVAL_DEV"} and purpose in {
        "annotation",
        "development",
        "human_review",
    }


class CustodianStore:
    """Separate offline store, absent from API/worker mounts and credentials."""

    def __init__(self, root: Path, git_root: Path) -> None:
        if root.resolve().is_relative_to(git_root.resolve()) or os.name != "posix":
            raise ValueError("protected_store_requires_external_posix_boundary")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        current_uid = int(getattr(os, "getuid", lambda: -1)())
        if root.stat().st_uid != current_uid or root.stat().st_mode & 0o077:
            raise ValueError("protected_store_permissions")
        self.root = root

    def write(self, version: str, body: bytes) -> str:
        if not re.fullmatch(r"[a-z0-9-]{1,80}", version):
            raise ValueError("invalid_corpus_version")
        key = f"{version}-{checksum(body)}.json"
        with (self.root / key).open("xb") as target:
            os.chmod(target.name, 0o600)
            target.write(body)
        return key


def withdraw(corpus: Corpus, family_id: str) -> Corpus:
    result = corpus.model_copy(deep=True)
    found = next((f for f in result.families if f.id == family_id), None)
    if found is None:
        raise ValueError("unknown_family")
    found.withdrawn = True
    result.status = "WITHDRAWN"
    result.invalidated_reports = sorted(set(result.invalidated_reports + result.dependent_reports))
    # Custodian deletes live source/gold from approved lineage; retain only suppression hashes.
    return result

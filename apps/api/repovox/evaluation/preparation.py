"""Offline preparation evidence, never an approval generator or analyzer-backed gold."""

import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, model_validator

from repovox.evaluation.corpus import Corpus, Family, checksum, serialize
from repovox.evaluation.gold import ID, SHA, EdgeFact, EdgeIdentity, Hash, Record, identity

TARGETS = {
    "development": 20,
    "held_out": 60,
    "python": 20,
    "javascript_typescript": 20,
    "mixed": 20,
    "hidden_owner_authored": 10,
    "adversarial_variants": 100,
    "adversarial_families": 20,
    "gold_claims": 600,
    "supported_gold_edges": 120,
}


def human_id(value: str) -> str:
    if not value.strip() or re.search(r"codex|chatgpt|assistant|\bbot\b|\bai\b", value, re.I):
        raise ValueError("actual_human_identity_required")
    return value


class Candidate(Record):
    family_id: ID
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    url: str
    commit_sha: SHA
    language_slice: Literal["python", "javascript_typescript", "mixed"]
    language_basis: str
    license_id: str
    license_path: str | None
    license_text_sha256: Hash | None
    permission_basis: str
    permission_evidence_sha256: Hash | None
    attribution: str
    redistribution: Literal["pending", "permitted", "restricted"]
    reviewer_access: Literal["pending", "permitted", "restricted"]
    retention: str
    ancestry: list[str]
    ancestry_basis: str
    complexity: str
    preliminary_coverage: str
    rights_status: Literal["pending", "rejected", "rights_reviewed", "owner_approved"]
    rights_review_sha256: Hash | None
    owner_approval_sha256: Hash | None
    reason: str

    @model_validator(mode="after")
    def approval_evidence(self) -> "Candidate":
        if self.url != f"https://github.com/{self.repository}":
            raise ValueError("candidate_repository_url_mismatch")
        if self.rights_status in {"rights_reviewed", "owner_approved"} and not all(
            [self.permission_evidence_sha256, self.rights_review_sha256]
        ):
            raise ValueError("candidate_rights_evidence_required")
        if self.rights_status == "owner_approved" and (
            not self.owner_approval_sha256 or self.reviewer_access != "permitted"
        ):
            raise ValueError("candidate_owner_permission_required")
        return self


class Catalog(Record):
    schema_version: Literal["evaluation-candidates-1.0"]
    captured_on: str
    candidates: list[Candidate]

    @model_validator(mode="after")
    def unique_candidates(self) -> "Catalog":
        families = [c.family_id for c in self.candidates]
        repositories = [c.repository.lower() for c in self.candidates]
        if len(set(families)) != len(families) or len(set(repositories)) != len(repositories):
            raise ValueError("duplicate_candidate_family_or_repository")
        return self


class ReviewIdentity(Record):
    family_id: ID
    annotation_sha256: Hash
    preparer_id: ID
    reviewer_id: ID
    claim_ids: list[ID]
    edge_ids: list[ID]

    @model_validator(mode="after")
    def independent(self) -> "ReviewIdentity":
        human_id(self.preparer_id)
        human_id(self.reviewer_id)
        if self.preparer_id.casefold() == self.reviewer_id.casefold():
            raise ValueError("self_review_forbidden")
        return self


class ReviewSeal(ReviewIdentity):
    approval_sha256: Hash


class ReviewReceipt(ReviewIdentity):
    schema_version: Literal["gold-review-receipt-1.0"]
    # The seal references these immutable receipt bytes.
    source_checked: Literal[True]
    approved: Literal[True]
    unresolved_disagreements: Literal[0]


def validate_receipt(body: bytes, seal: ReviewSeal) -> None:
    receipt = ReviewReceipt.model_validate_json(body)
    if receipt.model_dump(
        exclude={
            "schema_version",
            "source_checked",
            "approved",
            "unresolved_disagreements",
            "approval_sha256",
        }
    ) != (seal.model_dump(exclude={"approval_sha256"})):
        raise ValueError("review_receipt_mismatch")


class VariantReview(Record):
    id: ID
    family_id: ID
    parent_commit_sha: SHA
    recipe_sha256: Hash
    materialized_manifest_sha256: Hash
    expected_outcome: Literal["qualified_extraction", "abstention", "intake_rejection"]
    expectations_sha256: Hash
    preparer_id: ID
    reviewer_id: ID
    approval_sha256: Hash

    @model_validator(mode="after")
    def independent(self) -> "VariantReview":
        human_id(self.preparer_id)
        human_id(self.reviewer_id)
        if self.preparer_id.casefold() == self.reviewer_id.casefold():
            raise ValueError("self_review_forbidden")
        return self


class HiddenAuthorship(Record):
    family_id: ID
    author_id: Literal["Stevemeg"]
    genuinely_owner_authored: Literal[True]
    newly_authored: Literal[True]
    provenance_sha256: Hash
    owner_declaration_sha256: Hash
    reviewer_confirmation_sha256: Hash


class GatePacket(Record):
    schema_version: Literal["eval-entry-preparation-1.0"]
    catalog: Catalog
    reviews: list[ReviewSeal]
    variants: list[VariantReview]
    hidden_authorship: list[HiddenAuthorship]
    worker_uid: int = Field(ge=1)
    operational_access_review_sha256: Hash
    budget_approval_sha256: Hash
    retention_access_approval_sha256: Hash


def annotation_digest(family: Family) -> str:
    # The review covers source, rights, split, grouping, variants and ALL gold fields.
    return checksum(serialize(family.model_dump(exclude={"gold_review"})))


def evidence(root: Path, value: str) -> bytes:
    path = root / value
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("invalid_evidence_key")
    if path.is_symlink() or not path.is_file() or checksum(path.read_bytes()) != value:
        raise ValueError("preparation_evidence_missing_or_changed")
    return path.read_bytes()


def language_slice(source_manifest: dict[str, Any]) -> str:
    languages = {f["language"] for f in source_manifest["files"] if f["status"] == "eligible"}
    python = "python" in languages
    js = bool(languages & {"javascript", "typescript", "tsx"})
    if python and js:
        return "mixed"
    if python:
        return "python"
    if js:
        return "javascript_typescript"
    raise ValueError("no_supported_language_slice")


def source_fingerprints(source: Path) -> list[dict[str, str]]:
    """Mechanical overlap suggestions only; normalized hashes are never citation hashes."""
    from repovox.analysis.filtering import LANGUAGES

    results = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("fingerprint_source_symlink")
        if path.is_file() and path.suffix in LANGUAGES:
            body = path.read_bytes()
            if body:
                results.append(
                    {
                        "path": path.relative_to(source).as_posix(),
                        "original_sha256": checksum(body),
                        "whitespace_normalized_sha256": checksum(re.sub(rb"\s+", b"", body)),
                    }
                )
    return results


def grouping_suggestions(inventories: dict[str, list[dict[str, str]]]) -> list[list[str]]:
    indexed: dict[str, set[str]] = {}
    for family, files in inventories.items():
        for item in files:
            for key in ["original_sha256", "whitespace_normalized_sha256"]:
                indexed.setdefault(item[key], set()).add(family)
    return [
        list(item)
        for item in sorted(
            {tuple(sorted(families)) for families in indexed.values() if len(families) > 1}
        )
    ]


def verify_boundary(root: Path, git_root: Path, worker_uid: int) -> None:
    """Check actual DAC, including descendants; operator review covers mounts/credentials."""
    if os.name != "posix" or root.is_symlink():
        raise ValueError("protected_posix_boundary_required")
    resolved = root.resolve()
    if resolved.is_relative_to(git_root.resolve()) or git_root.resolve().is_relative_to(resolved):
        raise ValueError("protected_store_overlaps_git")
    uid = int(getattr(os, "getuid", lambda: -1)())
    if worker_uid == uid or worker_uid == 0:
        raise ValueError("worker_custodian_identity_overlap")
    if not resolved.is_dir():
        raise ValueError("protected_store_missing")
    for path in [resolved, *resolved.rglob("*")]:
        info = path.lstat()
        if (
            path.is_symlink()
            or info.st_uid != uid
            or info.st_mode & 0o077
            or not (path.is_file() or path.is_dir())
        ):
            raise ValueError("protected_store_permissions_or_links")


def validate_variant_source(manifest: bytes, source: Path, sha: str) -> None:
    """Variants can intentionally fail intake; verify bytes without running/filtering them."""
    data = json.loads(manifest)
    if data["parent_commit_sha"] != sha or not source.is_dir():
        raise ValueError("variant_source_or_parent_missing")
    expected = {}
    for item in data["files"]:
        path = PurePosixPath(item["path"])
        if (
            path.is_absolute()
            or any(part in {".", ".."} for part in path.parts)
            or "\\" in item["path"]
            or ":" in item["path"]
            or path.as_posix() != item["path"]
            or item["path"] in expected
        ):
            raise ValueError("invalid_variant_manifest_path")
        expected[item["path"]] = item["file_sha256"]
    actual = {
        file.relative_to(source).as_posix(): checksum(file.read_bytes())
        for file in source.rglob("*")
        if file.is_file()
    }
    if not actual or actual != expected:
        raise ValueError("variant_source_changed")


def validate_preparation(
    corpus: Corpus,
    sources: dict[str, Path],
    provenance: Path,
    packet_path: Path,
    git_root: Path,
) -> None:
    """Required supplement to the accepted freeze algorithm; no thresholds are changed."""
    packet = GatePacket.model_validate_json(packet_path.read_bytes())
    root = provenance.parent.resolve()
    verify_boundary(root, git_root, packet.worker_uid)
    if not packet_path.resolve().is_relative_to(root):
        raise ValueError("preparation_packet_outside_custodian")
    if corpus.appointment is None:
        raise ValueError("independent_human_appointment_required")
    human_id(corpus.appointment.reviewer_id)
    for digest in [
        packet.operational_access_review_sha256,
        packet.budget_approval_sha256,
        packet.retention_access_approval_sha256,
    ]:
        evidence(provenance, digest)
    candidates = {c.family_id: c for c in packet.catalog.candidates}
    reviews = {r.family_id: r for r in packet.reviews}
    variants = {v.id: v for v in packet.variants}
    authorship = {a.family_id: a for a in packet.hidden_authorship}
    if (
        len(reviews) != len(packet.reviews)
        or len(variants) != len(packet.variants)
        or len(authorship) != len(packet.hidden_authorship)
    ):
        raise ValueError("duplicate_preparation_approval")
    families = [f for f in corpus.families if f.split != "TOOLING_FIXTURE"]
    if set(reviews) != {f.id for f in families} or set(variants) != {
        v for f in families for v in f.adversarial_variants
    }:
        raise ValueError("partial_or_unassigned_preparation_review")
    for family in families:
        candidate = candidates.get(family.id)
        if candidate is None or candidate.rights_status != "owner_approved":
            raise ValueError("candidate_not_owner_approved")
        if (
            candidate.repository != family.repository
            or candidate.commit_sha != family.commit_sha
            or candidate.language_slice != family.language_slice
            or candidate.license_text_sha256 != family.rights.license_text_sha256
            or candidate.permission_evidence_sha256 != family.rights.permission_evidence_sha256
        ):
            raise ValueError("candidate_family_mismatch")
        for candidate_digest in [candidate.rights_review_sha256, candidate.owner_approval_sha256]:
            if candidate_digest is None:
                raise ValueError("candidate_approval_evidence_missing")
            evidence(provenance, candidate_digest)
        source = sources[family.id]
        if not source.resolve().is_relative_to(root):
            raise ValueError("source_outside_custodian")
        manifest = json.loads((source.parent / "source_manifest.json").read_bytes())
        if manifest["repository"] != family.repository:
            raise ValueError("cross_repository_source_contamination")
        if language_slice(manifest) != family.language_slice:
            raise ValueError("incorrect_language_slice")
        edge_facts = [
            identity(
                EdgeFact(
                    type="static_relationship",
                    edge=EdgeIdentity.model_validate(
                        edge.model_dump(exclude={"id", "supported", "citations"})
                    ),
                ),
                family.repository,
                family.commit_sha,
            )
            for edge in family.edges
        ]
        entries = [(entry.path, entry.rule, entry.target) for entry in family.entrypoints]
        if len(set(edge_facts)) != len(edge_facts) or len(set(entries)) != len(entries):
            raise ValueError("duplicate_graph_or_entrypoint_fact")
        review = reviews[family.id]
        if (
            review.annotation_sha256 != annotation_digest(family)
            or set(review.claim_ids) != {c.id for c in family.claims}
            or len(review.claim_ids) != len(family.claims)
            or set(review.edge_ids) != {e.id for e in family.edges}
            or len(review.edge_ids) != len(family.edges)
            or family.gold_review is None
            or review.preparer_id != family.gold_review.preparer_id
            or review.reviewer_id != family.gold_review.reviewer_id
            or review.reviewer_id != corpus.appointment.reviewer_id
            or review.approval_sha256 != family.gold_review.approval_evidence_sha256
        ):
            raise ValueError("review_seal_changed_or_incomplete")
        validate_receipt(evidence(provenance, review.approval_sha256), review)
        if family.newly_owner_authored:
            record = authorship.get(family.id)
            if record is None or not family.hidden or family.split != "EVAL_TEST":
                raise ValueError("hidden_owner_authorship_required")
            for digest in [
                record.provenance_sha256,
                record.owner_declaration_sha256,
                record.reviewer_confirmation_sha256,
            ]:
                evidence(provenance, digest)
        for variant_id in family.adversarial_variants:
            variant = variants[variant_id]
            if (
                family.split != "EVAL_TEST"
                or variant.family_id != family.id
                or variant.parent_commit_sha != family.commit_sha
                or variant.reviewer_id != corpus.appointment.reviewer_id
            ):
                raise ValueError("variant_parent_or_review_mismatch")
            for digest in [
                variant.recipe_sha256,
                variant.materialized_manifest_sha256,
                variant.expectations_sha256,
                variant.approval_sha256,
            ]:
                evidence(provenance, digest)
            validate_variant_source(
                evidence(provenance, variant.materialized_manifest_sha256),
                source.parent / "variants" / variant.id / "source",
                family.commit_sha,
            )


def readiness(corpus: Corpus, catalog: Catalog) -> dict[str, Any]:
    """Public aggregate only. Unchecked flags never become verified readiness counts."""
    from repovox.evaluation.corpus import counts

    raw = counts(corpus)
    blockers = []
    if corpus.appointment is None:
        blockers.append("independent_human_appointment_required")
    if any(raw.get(key, 0) < target for key, target in TARGETS.items()):
        blockers.append("approved_corpus_counts_incomplete")
    blockers.extend(
        ["source_rights_and_review_evidence_unverified", "protected_storage_unverified"]
    )
    return {
        "schema_version": "eval-entry-readiness-1.0",
        "corpus_status": corpus.status,
        "manifest_sha256": checksum(serialize(corpus.model_dump())),
        "catalog_sha256": checksum(serialize(catalog.model_dump())),
        "candidate_families": len(catalog.candidates),
        "candidate_rights_reviewed_records": sum(
            c.rights_status in {"rights_reviewed", "owner_approved"} for c in catalog.candidates
        ),
        "candidate_owner_approved_records": sum(
            c.rights_status == "owner_approved" for c in catalog.candidates
        ),
        "declared_gold_prepared_families": sum(
            bool(f.claims) and f.split != "TOOLING_FIXTURE" and not f.withdrawn
            for f in corpus.families
        ),
        "verified_rights_approved_families": 0,
        "verified_human_reviewed_families": 0,
        "declared_corpus_counts": raw,
        "verified_approved_counts": dict.fromkeys(TARGETS, 0),
        "targets": TARGETS,
        "reviewer_appointment": "PENDING" if corpus.appointment is None else "RECORD_UNVERIFIED",
        "annotation_completeness": "UNVERIFIED" if corpus.families else "NO_OFFICIAL_ANNOTATIONS",
        "rights_clearance": "UNVERIFIED",
        "protected_storage": "NOT_DEMONSTRATED_FOR_OFFICIAL_CORPUS",
        "contamination_check": "NO_APPROVED_CORPUS" if not corpus.families else "UNVERIFIED",
        "freeze_eligible": False,
        "independent_approval": "PENDING",
        "blockers": blockers,
        "verification_note": "Metadata-only report. Run protected freeze validation to verify "
        "actual evidence; synthetic tests confer no official readiness.",
    }

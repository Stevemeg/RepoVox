"""Metadata-only readiness and blank review worksheets; never generates source facts."""

import argparse
import json
import os
from pathlib import Path

from repovox.evaluation.corpus import Corpus, Family, freeze
from repovox.evaluation.preparation import (
    Catalog,
    GatePacket,
    annotation_digest,
    readiness,
    source_fingerprints,
)

parser = argparse.ArgumentParser()
parser.add_argument("--catalog", type=Path)
parser.add_argument("--manifest", type=Path)
parser.add_argument("--worksheet", type=Path)
parser.add_argument("--fingerprints", type=Path)
parser.add_argument("--output", type=Path)
parser.add_argument("--source", type=Path)
parser.add_argument("--provenance", type=Path)
parser.add_argument("--preparation", type=Path)
parser.add_argument("--verify", action="store_true")
parser.add_argument("--check", action="store_true", help="Compare aggregate output without writing")
args = parser.parse_args()
try:
    if args.fingerprints:
        if args.output is None or os.name != "posix":
            raise ValueError("fingerprints_require_protected_posix_output")
        from repovox.evaluation.corpus import CustodianStore

        store = CustodianStore(args.output.parent, Path(__file__).resolve().parents[1])
        inventory = {
            "schema_version": "source-fingerprints-1.0",
            "files": source_fingerprints(args.fingerprints),
        }
        print(
            json.dumps(
                {
                    "protected_fingerprints_key": store.write(
                        "fingerprints", json.dumps(inventory).encode()
                    )
                }
            )
        )
    elif args.worksheet:
        if args.output is None or os.name != "posix":
            raise ValueError("worksheet_requires_external_protected_posix_output")
        from repovox.evaluation.corpus import CustodianStore

        store = CustodianStore(args.output.parent, Path(__file__).resolve().parents[1])
        family = Family.model_validate_json(args.worksheet.read_bytes())
        result = {
            "schema_version": "annotation-review-worksheet-1.0",
            "family_id": family.id,
            "annotation_sha256": annotation_digest(family),
            "rows": [
                {"claim_id": c.id, "decision": None, "source_checked": None, "notes": None}
                for c in family.claims
            ],
            "edge_rows": [
                {"edge_id": e.id, "decision": None, "support_checked": None, "notes": None}
                for e in family.edges
            ],
            "preparer_id": None,
            "reviewer_id": None,
            "approval_evidence": None,
        }
        print(
            json.dumps(
                {"protected_worksheet_key": store.write("worksheet", json.dumps(result).encode())}
            )
        )
    else:
        if args.catalog is None or args.manifest is None:
            raise ValueError("catalog_and_manifest_required")
        catalog = Catalog.model_validate_json(args.catalog.read_bytes())
        corpus = Corpus.model_validate_json(args.manifest.read_bytes())
        result = readiness(corpus, catalog)
        if args.verify:
            if args.preparation is None or (
                GatePacket.model_validate_json(args.preparation.read_bytes()).catalog != catalog
            ):
                raise ValueError("readiness_catalog_packet_mismatch")
            sources = (
                {f.id: args.source / f.id / "source" for f in corpus.families}
                if args.source
                else None
            )
            checked = freeze(corpus, sources, args.provenance, args.preparation)
            from repovox.evaluation.corpus import counts

            verified = counts(checked)
            result["verified_approved_counts"] = {key: verified[key] for key in result["targets"]}
            result.update(
                freeze_eligible=True,
                blockers=[],
                reviewer_appointment="EVIDENCE_CHECKED",
                annotation_completeness="COMPLETE_SEALED_SOURCE_CHECKED",
                rights_clearance="EVIDENCE_CHECKED",
                protected_storage="POSIX_CHECKED_OPERATOR_REVIEW_RECORDED",
                contamination_check="FAMILY_AND_FINGERPRINT_CHECKED",
                dry_run_freeze_sha256=checked.freeze_sha256,
                verified_rights_approved_families=verified["approved"],
                verified_human_reviewed_families=verified["approved"],
            )
        body = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            if args.check:
                if args.output.read_text(encoding="utf-8") != body:
                    raise ValueError("readiness_report_drift")
            else:
                with args.output.open("x", encoding="utf-8") as target:
                    target.write(body)
        print(body)
except (ValueError, OSError, KeyError):
    print(
        json.dumps({"status": "BLOCKED", "reason": "Preparation evidence incomplete or invalid."})
    )
    raise SystemExit(2) from None

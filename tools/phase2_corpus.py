"""Offline custodian preparation; never creates approvals or calls a model."""

import argparse
import json
import os
from pathlib import Path

from repovox.evaluation.corpus import (
    Corpus,
    Family,
    counts,
    freeze,
    intake,
    serialize,
    validate_labels,
    withdraw,
)

parser = argparse.ArgumentParser()
parser.add_argument("manifest", type=Path)
parser.add_argument(
    "--action",
    choices=["inspect", "intake", "validate-labels", "freeze", "withdraw"],
    default="inspect",
)
parser.add_argument("--source", type=Path)
parser.add_argument("--family")
parser.add_argument("--output", type=Path)
parser.add_argument("--provenance", type=Path)
parser.add_argument("--candidate", type=Path)
args = parser.parse_args()
try:
    corpus = Corpus.model_validate_json(args.manifest.read_bytes())
    if args.action == "intake":
        if args.candidate is None or args.source is None:
            raise ValueError("actual_candidate_and_source_required")
        family = Family.model_validate_json(args.candidate.read_bytes())
        corpus = intake(corpus, family, args.source)
    elif args.action == "validate-labels":
        if not args.source or not args.family:
            raise ValueError("source_and_family_required")
        family: Family = next(f for f in corpus.families if f.id == args.family)
        validate_labels(family, args.source)
    elif args.action == "freeze":
        sources = (
            {f.id: args.source / f.id / "source" for f in corpus.families} if args.source else None
        )
        corpus = freeze(corpus, sources, args.provenance)
    elif args.action == "withdraw":
        if not args.family:
            raise ValueError("family_required")
        corpus = withdraw(corpus, args.family)
    if args.output:
        if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
            raise ValueError("gold_or_freeze_output_must_be_outside_git")
        if corpus.families and os.name != "posix":
            raise ValueError("protected_corpus_requires_posix_access_boundary")
        with args.output.open("xb") as target:
            os.chmod(target.name, 0o600)
            target.write(serialize(corpus.model_dump()))
    print(
        json.dumps(
            {"status": corpus.status, "reviewer": corpus.reviewer_status, "counts": counts(corpus)}
        )
    )
except Exception:
    print(
        json.dumps(
            {
                "status": "BLOCKED",
                "reason": "Corpus action prerequisites are incomplete; no approval created.",
            }
        )
    )
    raise SystemExit(2) from None

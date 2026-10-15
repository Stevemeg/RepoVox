"""Offline source-only authoring validation. No predictions, gold generation or reveal."""

import argparse
import json
from pathlib import Path

from repovox.evaluation.custody_v2 import Store
from repovox.evaluation.v2 import Scope, decode, validate_reference

parser = argparse.ArgumentParser()
parser.add_argument("--store", type=Path, required=True)
parser.add_argument("--tenant", required=True)
parser.add_argument("--worker-uid", type=int, required=True)
parser.add_argument("--scope-sha256", required=True)
parser.add_argument("--reference-sha256", required=True)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--proof-sha256", action="append", default=[])
parser.add_argument("--predecessor-sha256", action="append", default=[])
args = parser.parse_args()
git_root = Path(__file__).resolve().parents[1]
store = Store(args.store, git_root, args.tenant, args.worker_uid)
if not args.source.resolve().is_relative_to(args.store.resolve()):
    raise ValueError("v2_source_must_remain_private")
scope = decode(store.read(args.tenant, args.scope_sha256), args.scope_sha256, Scope)
if scope.tenant_id != args.tenant:
    raise ValueError("v2_tenant_denied")
ref = validate_reference(
    store.read(args.tenant, args.reference_sha256),
    args.reference_sha256,
    scope,
    args.scope_sha256,
    args.source,
    {key: store.read(args.tenant, key) for key in args.proof_sha256},
    {key: store.read(args.tenant, key) for key in args.predecessor_sha256},
)
print(
    json.dumps(
        {
            "schema_version": "v2-authoring-validation-1.0",
            "reference_sha256": args.reference_sha256,
            "assertions": len(ref.assertions),
            "annotation_scope": ref.annotation_scope,
            "result": "STRUCTURAL_VALIDATION_ONLY",
            "independent_acceptance": False,
        }
    )
)

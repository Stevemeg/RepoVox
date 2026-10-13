"""Export ONLY verified source packet A and retained notices, outside Git."""

import argparse
import json
import zipfile
from io import BytesIO
from pathlib import Path

from repovox.evaluation.corpus import checksum, serialize
from repovox.evaluation.exploratory import BlindPacket, checked_bytes, write_immutable

parser = argparse.ArgumentParser()
parser.add_argument("--store", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
workspace = Path(__file__).resolve().parents[1]
if args.store.resolve().is_relative_to(workspace) or args.output.resolve().is_relative_to(
    workspace
):
    raise ValueError("handoff_must_remain_outside_git")
content = BytesIO()
manifest = {}


def put(archive: zipfile.ZipFile, name: str, body: bytes) -> None:
    if name in manifest:
        raise ValueError("duplicate_review_export")
    archive.writestr(name, body)
    manifest[name] = checksum(body)


with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
    put(
        archive,
        "START-HERE.md",
        (workspace / "docs/development/exploratory-handoff.md").read_bytes(),
    )
    for name in ["gold-evaluation.schema.json", "exploratory-ai-reference.schema.json"]:
        put(archive, f"contracts/{name}", (workspace / "docs/ai" / name).read_bytes())
    put(
        archive,
        "contracts/source-fact-handbook.md",
        (workspace / "docs/development/evaluation-gold.md").read_bytes(),
    )
    for repo in ["pallets-click", "sindresorhus-p-limit", "jupyterlite-echo-kernel"]:
        root = args.store / repo
        seals = json.loads((root / "handoff-seals.json").read_bytes())
        body = checked_bytes(root, seals["A"]["path"], seals["A"]["sha256"])
        packet = BlindPacket.model_validate_json(body)
        rights_body = checked_bytes(root, "rights-decision.json", packet.rights_evidence_sha256)
        rights = json.loads(rights_body)
        put(archive, f"{repo}/package-a.json", body)
        put(archive, f"{repo}/rights-decision.json", rights_body)
        # Only opaque commitments to B, never its metrics, artifacts, predictions or paths.
        put(
            archive,
            f"{repo}/commitments.json",
            serialize(
                {
                    "A_sha256": seals["A"]["sha256"],
                    "B_sha256": seals["B"]["sha256"],
                    "prediction_reveal": "ONLY_AFTER_REFERENCE_RECORDED",
                    "track": packet.policy.track,
                }
            ),
        )
        for legal in rights["legal_evidence"]:
            if "path" in legal:
                put(
                    archive,
                    f"{repo}/notices/{Path(legal['path']).name}",
                    checked_bytes(root, legal["path"], legal["sha256"]),
                )
        for excerpt in packet.excerpts:
            text = (
                f"{packet.repository}@{packet.commit_sha}\n{excerpt.permalink}\n"
                f"Original file SHA256: {excerpt.file_sha256}\n"
                f"Lines {excerpt.start_line}-{excerpt.end_line}; "
                f"redactions: {len(excerpt.redactions)}\n\n" + excerpt.numbered_excerpt + "\n"
            )
            put(archive, f"{repo}/source/{excerpt.path}.numbered.txt", text.encode())
    archive.writestr(
        "export-manifest.json",
        serialize(
            {
                "schema_version": "exploratory-blind-export-1.0",
                "files": manifest,
                "predictions_included": False,
                "independent_reference_included": False,
            }
        ),
    )
body = content.getvalue()
write_immutable(args.output.parent, args.output.name, body)
print(
    json.dumps(
        {
            "blind_export_sha256": checksum(body),
            "bytes": len(body),
            "files": len(manifest) + 1,
            "predictions_included": False,
        }
    )
)

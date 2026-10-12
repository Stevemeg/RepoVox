"""Export/check explicit analysis 2.2 JSON Schema without contacting any service."""

import argparse
import json
from pathlib import Path

from repovox.analysis.contracts import PAYLOADS, Envelope
from repovox.evaluation.corpus import Corpus
from repovox.evaluation.gold import GoldEvaluation

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
schema = Envelope.model_json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = "https://repovox.invalid/contracts/analysis/2.2"
schema["allOf"] = []
for kind, model in PAYLOADS.items():
    payload = model.model_json_schema()
    schema.setdefault("$defs", {}).update(payload.pop("$defs", {}))
    schema["allOf"].append(
        {
            "if": {"properties": {"kind": {"const": kind}}},
            "then": {"properties": {"payload": payload}},
        }
    )
corpus = Corpus.model_json_schema()
corpus["$schema"] = "https://json-schema.org/draft/2020-12/schema"
corpus["$id"] = "https://repovox.invalid/contracts/evaluation-corpus/2.0"
gold = GoldEvaluation.model_json_schema()
gold["$schema"] = "https://json-schema.org/draft/2020-12/schema"
gold["$id"] = "https://repovox.invalid/contracts/gold-evaluation/1.0"
for destination, value in [
    (root / "docs/architecture/analysis.schema.json", schema),
    (root / "docs/ai/evaluation-corpus.schema.json", corpus),
    (root / "docs/ai/gold-evaluation.schema.json", gold),
]:
    body = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if args.check:
        assert destination.read_text(encoding="utf-8") == body, f"Schema drift: {destination.name}"
    else:
        destination.write_text(body, encoding="utf-8")
print(
    "Analysis/evaluation schemas checked."
    if args.check
    else "Analysis/evaluation schemas exported."
)

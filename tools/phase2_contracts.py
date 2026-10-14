"""Check frozen analysis 2.2 and additive 2.3/fact schemas without network access."""

import argparse
import json
from pathlib import Path

from repovox.analysis import contracts, contracts_v22
from repovox.analysis.facts import CanonicalFact
from repovox.evaluation.corpus import Corpus
from repovox.evaluation.exploratory import AIReference, BlindPacket, PredictionPacket
from repovox.evaluation.gold import GoldEvaluation
from repovox.evaluation.preparation import Catalog, GatePacket, ReviewReceipt

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
schemas = []
for version, module in [("2.2", contracts_v22), ("2.3", contracts)]:
    schema = module.Envelope.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://repovox.invalid/contracts/analysis/" + version
    schema["allOf"] = []
    for kind, model in module.PAYLOADS.items():
        payload = model.model_json_schema()
        schema.setdefault("$defs", {}).update(payload.pop("$defs", {}))
        schema["allOf"].append(
            {
                "if": {"properties": {"kind": {"const": kind}}},
                "then": {"properties": {"payload": payload}},
            }
        )
    schemas.append(schema)
corpus = Corpus.model_json_schema()
corpus["$schema"] = "https://json-schema.org/draft/2020-12/schema"
corpus["$id"] = "https://repovox.invalid/contracts/evaluation-corpus/2.0"
gold = GoldEvaluation.model_json_schema()
gold["$schema"] = "https://json-schema.org/draft/2020-12/schema"
gold["$id"] = "https://repovox.invalid/contracts/gold-evaluation/1.0"
for destination, value in [
    (root / "docs/architecture/analysis.schema.json", schemas[0]),
    (root / "docs/architecture/analysis-2.3.schema.json", schemas[1]),
    (root / "docs/architecture/source-fact-2.0.schema.json", CanonicalFact.model_json_schema()),
    (root / "docs/ai/evaluation-corpus.schema.json", corpus),
    (root / "docs/ai/gold-evaluation.schema.json", gold),
    (root / "docs/ai/evaluation-candidates.schema.json", Catalog.model_json_schema()),
    (root / "docs/ai/eval-entry-preparation.schema.json", GatePacket.model_json_schema()),
    (root / "docs/ai/gold-review-receipt.schema.json", ReviewReceipt.model_json_schema()),
    (root / "docs/ai/exploratory-blind-source.schema.json", BlindPacket.model_json_schema()),
    (
        root / "docs/ai/exploratory-sealed-prediction.schema.json",
        PredictionPacket.model_json_schema(),
    ),
    (root / "docs/ai/exploratory-ai-reference.schema.json", AIReference.model_json_schema()),
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

"""Export/check additive offline v2 schemas; never rewrite accepted schemas."""

import argparse
import json
from pathlib import Path

from repovox.evaluation.custody_v2 import Event, SourcePacket
from repovox.evaluation.scoring_v2 import Aggregate, Score
from repovox.evaluation.scoring_v20 import Aggregate as LegacyAggregate
from repovox.evaluation.scoring_v20 import Score as LegacyScore
from repovox.evaluation.v2 import Prediction, Reference, Scope

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1] / "docs/ai"
for model in [
    Reference,
    Prediction,
    Scope,
    Score,
    Aggregate,
    SourcePacket,
    Event,
    LegacyScore,
    LegacyAggregate,
]:
    schema = model.model_json_schema()
    version = schema["properties"]["schema_version"]["const"]
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://repovox.invalid/contracts/" + version
    # Constructors have convenient defaults; serialized packets require explicit versions.
    for definition in [schema, *schema.get("$defs", {}).values()]:
        if "schema_version" in definition.get("properties", {}):
            definition["required"] = sorted({*definition.get("required", []), "schema_version"})
    body = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    path = root / (version + ".schema.json")
    if args.check:
        assert path.read_text(encoding="utf-8") == body, "V2 schema drift: " + path.name
    else:
        path.write_text(body, encoding="utf-8")
print("V2 schemas checked." if args.check else "V2 schemas exported.")

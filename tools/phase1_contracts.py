"""Export or verify deterministic public OpenAPI; no services are contacted."""

import argparse
import json
from pathlib import Path

from repovox.core.config import Settings
from repovox.main import create_app

config = Settings(
    environment="test",
    dev_auth=True,
    fixtures=True,
    database_url="postgresql+psycopg://rv_app@localhost/repovox",
    session_secret="synthetic-contract-secret-never-used-for-sessions",
    storage_access_key="unused",
    storage_secret_key="unused",
)
app = create_app(config)
body = json.dumps(app.openapi(), sort_keys=True, indent=2) + "\n"
destination = Path(__file__).resolve().parents[1] / "packages/contracts/openapi.json"
parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
if args.check:
    assert destination.read_text(encoding="utf-8") == body, "OpenAPI contract drift"
else:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(body, encoding="utf-8")
app.state.engine.dispose()
print("Public OpenAPI contract verified." if args.check else "Public OpenAPI contract exported.")

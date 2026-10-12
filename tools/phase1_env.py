"""Generate ignored local credentials; never display values or overwrite existing configuration."""

import secrets
from pathlib import Path

destination = Path(".env")
keys = (
    "POSTGRES_PASSWORD",
    "MIGRATION_PASSWORD",
    "APP_DATABASE_PASSWORD",
    "WORKER_DATABASE_PASSWORD",
    "SESSION_SECRET",
    "MINIO_ROOT_PASSWORD",
    "STORAGE_SECRET_KEY",
)
with destination.open("x", encoding="utf-8") as file:
    file.write("# Development only; never reuse outside this local environment.\n")
    for key in keys:
        file.write(f"{key}={secrets.token_hex(24)}\n")
    file.write("MINIO_ROOT_USER=repovox-local-admin\nSTORAGE_ACCESS_KEY=repovox-local-service\n")
print("Created ignored .env with distinct random development values.")

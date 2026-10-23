"""Offline SDK trust evidence; optional synthetic client, never network activity."""

import json
import sys
from pathlib import Path

# Also supports the isolated cfn-lint environment without installing RepoVox there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from repovox.sdk_trust import approved_trust as approved_trust  # noqa: E402


def refuse_network(event: str, args: tuple[object, ...]) -> None:
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("offline lint network forbidden")


if __name__ == "__main__":
    result = {"interpreter": sys.executable, **approved_trust()}
    if sys.argv[1:] == ["--synthetic-storage"]:
        sys.addaudithook(refuse_network)
        from repovox.core.config import Settings
        from repovox.sdk_trust import validate_client
        from repovox.storage import S3Storage

        storage = S3Storage(
            Settings(
                environment="test",
                dev_auth=True,
                database_url="postgresql://offline.invalid/db",
                session_secret="synthetic-only" * 4,
                storage_access_key="synthetic",
                storage_secret_key="synthetic",
                storage_endpoint="http://127.0.0.1:9",
            )
        )
        validate_client(storage.client)
        result["synthetic_storage_constructed_without_network"] = True
    elif sys.argv[1:]:
        raise ValueError("unsupported SDK check arguments")
    print(json.dumps(result, indent=2))

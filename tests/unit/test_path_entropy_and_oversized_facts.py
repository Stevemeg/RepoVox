"""Prose file names are not tokens; an oversized syntax fact is dropped, not the repository.

Every fixture is synthetic. Secret-shaped strings are assembled at run time so no credential
literal is committed (the history is scanned by gitleaks in CI).
"""

from pathlib import Path

import pytest
from pydantic import TypeAdapter
from repovox.analysis.common import AnalysisError
from repovox.analysis.contracts import PAYLOADS
from repovox.analysis.filtering import filter_sources
from repovox.analysis.github import Snapshot
from repovox.analysis.parser import FACT_CHARACTERS, parse_file, structure
from repovox.analysis.privacy import path_spans, scan
from repovox.analysis.sandbox import execute

MAIN = b'def main(x):\n    return x\n\n\nif __name__ == "__main__":\n    main(1)\n'


def tree(root: Path, files: dict[str, bytes]) -> Path:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return root


def inventory(root: Path) -> dict:
    return filter_sources(root, "example/prose", "a" * 40, "b" * 64)


@pytest.mark.parametrize(
    "name",
    [
        "docs/adr/ADR-0019-production-observability.md",
        "docs/adr/ADR-0020-multi_region-disaster-recovery-runbook.md",
    ],
)
def test_prose_file_names_are_not_secrets(tmp_path: Path, name: str) -> None:
    assert scan(name)  # the old whole-path rule flagged it as one high-entropy run
    assert path_spans(name) == []
    manifest = inventory(tree(tmp_path, {"main.py": MAIN, name: b"# Decision\n"}))
    assert name in {f["path"] for f in manifest["files"]}


@pytest.mark.parametrize(
    "name",
    [
        "config/Zx9kQ2mP7vR4tL8wN3bY6cH1tK5s.txt",  # one unsegmented mixed token
        "keys/q8Zr4LmW2vXt9KpB/3nYc7HsD1fJ6gQe/key.bin",  # base64 with `/` as directories
        "tokens/aB3dE5fG7hIq-9jK1lM3nO5pQ7rStU.json",  # hyphen-joined token halves
        "certs/Kp4+Xr8/Qz2=Mn6Lw9Vt3Yb7Hc1Jd5.pem",  # `+` and `=` inside the run
    ],
)
def test_token_like_file_names_still_fail_closed(tmp_path: Path, name: str) -> None:
    assert path_spans(name)
    with pytest.raises(AnalysisError, match="secret_detected"):
        inventory(tree(tmp_path, {"main.py": MAIN, name: b"x"}))


def credential_url() -> bytes:
    scheme, user, word = "postgresql+psycopg", "app", "pa" + "ss" + "word123"
    return f'URL = "{scheme}://{user}:{word}@localhost:5432/app"\n'.encode()


def secret_literal() -> bytes:
    return ("se" + "cret = " + '"' + "k" * 25 + '"\n').encode()


def private_key() -> bytes:
    return ("-----BEGIN " + "OPENSSH PRIVATE KEY-----\nAAAA\n").encode()


@pytest.mark.parametrize(
    "name,body",
    [
        ("tests/test_config.py", credential_url()),
        (".github/workflows/quality.yml", b"env:\n  DATABASE_URL: " + credential_url()[7:-2]),
        ("tests/test_production_controls.py", secret_literal()),
        (".env", ("PASS" + "WORD='" + "h" * 12 + "'\n").encode()),
        ("deploy/id_rsa", private_key()),
    ],
)
def test_secret_contents_still_fail_closed(tmp_path: Path, name: str, body: bytes) -> None:
    with pytest.raises(AnalysisError, match="secret_detected"):
        inventory(tree(tmp_path, {"main.py": MAIN, name: body}))


@pytest.mark.parametrize("name", [".env", ".env.local", "deploy/id_rsa", "certs/server.key"])
def test_sensitive_file_names_are_still_excluded(tmp_path: Path, name: str) -> None:
    manifest = inventory(tree(tmp_path, {"main.py": MAIN, name: b"harmless\n"}))
    entry = next(f for f in manifest["files"] if f["path"] == name)
    assert (entry["status"], entry["reason"]) == ("skipped", "sensitive_path")


CONDITION = " and ".join(f"value_{i} > {i}" for i in range(90))
CHAIN = "".join(f".step_{i}(x)" for i in range(120))
OVERSIZED = (
    "import os\n\n\n"
    "def check(value_0=0):\n"
    "    if (\n        " + CONDITION + "\n    ):\n        return True\n"
    "    return os.getcwd()\n\n\n"
    "def build(client, x):\n"
    "    result = client" + CHAIN + "\n"
    "    return result\n\n\n"
    'if __name__ == "__main__":\n'
    "    check()\n"
).encode()


def emitted_texts(symbol: dict) -> list[str]:
    values = [v for v in symbol.values() if isinstance(v, str)]
    values += [item for v in symbol.values() if isinstance(v, list) for item in v]
    return [v for v in values if isinstance(v, str)]


def test_oversized_expressions_drop_only_their_own_facts() -> None:
    assert len(CONDITION) > FACT_CHARACTERS and len(CHAIN) > FACT_CHARACTERS
    symbols, errors = parse_file("service/inputs.py", OVERSIZED, "python")
    assert errors == []
    assert all(len(t) <= FACT_CHARACTERS for s in symbols for t in emitted_texts(s))
    kinds = {(s["kind"], s["name"]) for s in symbols}
    # The rest of the file is kept: declarations, imports, short calls and the main guard.
    assert {("function", "check"), ("function", "build"), ("import", "os")} <= kinds
    assert ("call", "os.getcwd") in kinds and ("entrypoint", "__main__") in kinds
    calls = [s for s in symbols if s["kind"] == "call" and s["name"].startswith("client")]
    assert calls and len(calls) < 120  # short inner calls kept, the oversized outer ones dropped
    assert parse_file("service/inputs.py", OVERSIZED, "python") == (symbols, errors)


def test_oversized_javascript_import_is_dropped() -> None:
    body = (
        'import { a } from "' + "m" * 1100 + '";\n'
        'import { b } from "./local";\n'
        "export function run() { return b(a); }\n"
    ).encode()
    symbols, errors = parse_file("web/app.js", body, "javascript")
    assert errors == []
    imports = [s["name"] for s in symbols if s["kind"] == "import"]
    assert imports == ["./local"]
    assert all(len(t) <= FACT_CHARACTERS for s in symbols for t in emitted_texts(s))


def test_structure_and_verification_accept_a_file_with_dropped_facts(tmp_path: Path) -> None:
    root = tree(tmp_path / "source", {"main.py": MAIN, "service/inputs.py": OVERSIZED})
    manifest = inventory(root)
    structural = structure(root, manifest)
    assert {f["path"]: f["status"] for f in manifest["files"]} == {
        "main.py": "parsed",
        "service/inputs.py": "parsed",
    }
    assert structural["parse_errors"] == []
    request = {
        "snapshot": Snapshot(
            "example/prose",
            "https://github.com/example/prose",
            1,
            "example",
            "prose",
            True,
            "main",
            "a" * 40,
            "2026-11-20T00:00:00Z",
        ).data(),
        "snapshot_id": "11111111-1111-4111-8111-111111111111",
        "archive_hash": "b" * 64,
        "inputs": {},
    }
    stages = [(3, "filter"), (4, "structure"), (5, "entrypoints"), (6, "infer")]
    stages += [(7, "knowledge"), (8, "evidence"), (9, "verify")]
    for ordinal, kind in stages:
        payload = execute(ordinal, root, request)
        TypeAdapter(PAYLOADS[kind]).validate_python(payload)
        request["inputs"][str(ordinal)] = payload
    names = [s["name"] for s in request["inputs"]["4"]["structure"]["symbols"]]
    assert names and max(map(len, names)) <= FACT_CHARACTERS

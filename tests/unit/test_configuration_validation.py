"""C-01 synthetic configuration grammar and original-byte provenance regressions."""

import json
from pathlib import Path

import pytest
from repovox.analysis.common import AnalysisError, digest
from repovox.analysis.configuration import configuration, properties
from repovox.analysis.documentation import context_symbols
from test_analysis import analyze


def rejected_config(tmp_path: Path, body: bytes, path: str = "package.json") -> None:
    (tmp_path / path).write_bytes(body)
    manifest = {
        "files": [
            {
                "path": path,
                "status": "context",
                "classification": "configuration",
                "file_sha256": digest(body),
            }
        ]
    }
    assert configuration(tmp_path, manifest) == {
        "dependencies": [],
        "config_entries": [],
        "config_errors": [path],
    }
    assert context_symbols(tmp_path, manifest) == []


@pytest.mark.parametrize("ws", ["\u00a0", "\u0085", "\u2003", "\u2028", "\u2029", "\v", "\f"])
@pytest.mark.parametrize(
    "template",
    [
        '{WS"main":"entry.js"}',
        '{"main"WS:"entry.js"}',
        '{"main":WS"entry.js"}',
        '{"main":"entry.js"WS}',
        '{"exports":["./a.js",WS"./b.js"]}',
        '{"main":"entry.js"}WS',
    ],
)
def test_non_json_whitespace_rejected(tmp_path: Path, ws: str, template: str) -> None:
    body = template.replace("WS", ws).encode("utf-8")
    with pytest.raises(json.JSONDecodeError):
        json.loads(body)
    rejected_config(tmp_path, body)


@pytest.mark.parametrize(
    "suffix",
    [
        b',"extra":NaN}',
        b',"extra":Infinity}',
        b',"extra":-Infinity}',
        b',"main":"other.js"}',
        b',"ma\\u0069n":"other.js"}',
        b',"exports":{"import":"a","import":"b"}}',
        b",}",
        b',"exports":["a",]}',
        b',"extra":tru}',
        b',"extra":01}',
        b',"extra":1.}',
        b',"extra":}',
        b',"extra":"unterminated}',
        b',"extra":"raw\nnewline"}',
        b',"extra":"\\x20"}',
        b"} false",
        b"",
    ],
)
def test_malformed_config_discards_all_facts(tmp_path: Path, suffix: bytes) -> None:
    # A valid earlier field must not survive any later grammar/duplicate failure.
    rejected_config(tmp_path, b'{"main":"entry.js"' + suffix)


def test_valid_json_whitespace_utf8_and_original_ranges(tmp_path: Path) -> None:
    body = (
        ' \t\r\n{\r\n  "name": "caf\u00e9\u00a0tool",\r\n'
        '  "exports": {\r\n    ".": [\r\n      "./caf\u00e9.js",\r\n'
        '      "./other.js"\r\n    ]\r\n  },\r\n'
        '  "dependencies": {"helper": "^1.0"},\r\n'
        '  "extra": [true, false, null, -12.5e2, {}, []]\r\n}\t\r\n '
    ).encode("utf-8")
    config, spans = properties(body, True)
    assert config == json.loads(body)
    expected = {
        ("exports", ".", "0"): ('"./caf\u00e9.js"'.encode(), 6),
        ("exports", ".", "1"): (b'"./other.js"', 7),
        ("dependencies", "helper"): (b'"helper": "^1.0"', 10),
    }
    request, result = analyze(tmp_path, {"package.json": body, "app.py": b"x = 1\n"})
    assert request["inputs"]["4"]["configuration"]["config_errors"] == []
    symbols = result["knowledge"]["symbols"]
    for key, (excerpt, line) in expected.items():
        start = body.index(excerpt)
        end = start + len(excerpt)
        assert spans[key] == (start, end)
        symbol = next(s for s in symbols if s["syntax"]["qualified_name"] == ".".join(key))
        assert (symbol["start_byte"], symbol["end_byte"]) == (start, end)
        assert (symbol["start_line"], symbol["end_line"]) == (line, line)
        assert symbol["file_sha256"] == digest(body)
    assert all(e["validation_status"] == "valid" for e in result["evidence"]["items"])


def test_invalid_config_pipeline_records_error_without_config_facts(tmp_path: Path) -> None:
    request, result = analyze(
        tmp_path, {"package.json": b'{"main":\xc2\xa0"entry.js"}', "app.py": b"x = 1\n"}
    )
    assert request["inputs"]["4"]["configuration"]["config_errors"] == ["package.json"]
    assert not any(s["path"] == "package.json" for s in result["knowledge"]["symbols"])


def test_toml_unicode_whitespace_already_rejected(tmp_path: Path) -> None:
    rejected_config(tmp_path, b'[project.scripts]\nrun =\xc2\xa0"app:run"', "pyproject.toml")


def test_config_hash_mismatch_still_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_bytes(b'{"main":"changed.js"}')
    with pytest.raises(AnalysisError, match="source_changed"):
        configuration(
            tmp_path,
            {
                "files": [
                    {
                        "path": "package.json",
                        "status": "context",
                        "classification": "configuration",
                        "file_sha256": digest(b"{}"),
                    }
                ]
            },
        )

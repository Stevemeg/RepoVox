"""Offline real-package checks and explicitly synthetic negative controls."""

import ast
import importlib.metadata
import os
import subprocess
import sys
import venv
from pathlib import Path
from unittest.mock import patch

import pytest
from botocore.config import Config
from botocore.stub import Stubber
from repovox import sdk_trust as trust

ROOT = Path(__file__).resolve().parents[2]


def client(**kwargs):
    return trust.create_client(
        "s3",
        endpoint_url="https://offline.invalid",
        aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
        region_name="us-east-1",
        offline=True,
        **kwargs,
    )


def test_real_installed_distribution_and_selection():
    result = trust.approved_trust()
    assert result["active"]["sha256"] == trust.CERTIFI_SHA256
    assert result["active"]["certificates"] == 120
    assert result["fallback"]["sha256"] == trust.FALLBACK_SHA256
    assert result["fallback"]["certificates"] == 126
    assert not trust.BLOCKED.intersection(result["fallback"]["fingerprints"])


@pytest.mark.parametrize(
    "verify", [False, None, "/missing.pem", "tests/fixtures/security/aaa-public-root.pem"]
)
def test_verify_override_rejected_before_transport(verify):
    with patch("botocore.session.Session", side_effect=AssertionError("transport reached")):
        with pytest.raises(trust.SDKTrustError, match="verify must"):
            client(verify=verify)


@pytest.mark.parametrize("name", sorted(trust.OVERRIDES | {"https_proxy", "AWS_ENDPOINT_URL_S3"}))
def test_environment_precedence_cannot_replace_ca(name, monkeypatch):
    monkeypatch.setenv(name, "unreviewed-do-not-open")
    with patch("botocore.session.Session", side_effect=AssertionError("transport reached")):
        with pytest.raises(trust.SDKTrustError, match="environment override"):
            client()


@pytest.mark.parametrize(
    "config",
    [
        Config(proxies_config={"proxy_ca_bundle": "/missing"}),
        Config(proxies_config={"proxy_use_forwarding_for_https": True}),
        Config(proxies={"https": "https://proxy.invalid"}),
        Config(client_cert="/unreviewed-client.pem"),
    ],
)
def test_proxy_and_client_certificate_overrides(config):
    with pytest.raises(trust.SDKTrustError, match="proxy or client"):
        client(config=config)


def test_corrupt_or_reintroduced_actual_anchor():
    with pytest.raises(trust.SDKTrustError, match="missing certificates"):
        trust.validate_bundle(b"corrupt", trust.CERTIFI_SHA256)
    pem = (ROOT / "tests/fixtures/security/aaa-public-root.pem").read_bytes()
    with pytest.raises(trust.SDKTrustError, match="blocked"):
        trust.validate_bundle(pem, trust.CERTIFI_SHA256)
    import certifi

    with pytest.raises(trust.SDKTrustError, match="unapproved CA commitment"):
        trust.validate_bundle(Path(certifi.where()).read_bytes() + b"\n", trust.CERTIFI_SHA256)


def test_aws_ca_bundle_points_to_actual_rejected_root(monkeypatch):
    monkeypatch.setenv("AWS_CA_BUNDLE", str(ROOT / "tests/fixtures/security/aaa-public-root.pem"))
    with patch("botocore.session.Session", side_effect=AssertionError("transport reached")):
        with pytest.raises(trust.SDKTrustError, match="environment override"):
            client()


@pytest.mark.parametrize("corruption", ["missing", "corrupt", "blocked"])
def test_certifi_file_failure_before_client_construction(corruption, monkeypatch):
    import certifi

    target = Path(certifi.where()).resolve()
    original = Path.read_bytes
    good = original(target)
    bad = (ROOT / "tests/fixtures/security/aaa-public-root.pem").read_bytes()

    def read(path):
        if path.resolve() == target:
            if corruption == "missing":
                raise FileNotFoundError("synthetic missing CA")
            return b"corrupt" if corruption == "corrupt" else good + bad
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    expected = {"missing": "unavailable", "corrupt": "missing certificates", "blocked": "blocked"}
    with patch("botocore.session.Session", side_effect=AssertionError("transport reached")):
        with pytest.raises(trust.SDKTrustError, match=expected[corruption]):
            client()


@pytest.mark.parametrize("package", ["botocore", "boto3", "certifi"])
def test_unsupported_packages_rejected(package, monkeypatch):
    original = importlib.metadata.version
    monkeypatch.setattr(
        importlib.metadata, "version", lambda p: "0.0.0" if p == package else original(p)
    )
    with pytest.raises(trust.SDKTrustError, match="unsupported"):
        client()


def test_wrong_interpreter_package_path(tmp_path, monkeypatch):
    monkeypatch.setattr(trust.sysconfig, "get_path", lambda name: str(tmp_path))
    with pytest.raises(trust.SDKTrustError, match="outside selected interpreter"):
        client()


def test_actual_minimal_interpreter_has_no_silent_fallback(tmp_path):
    target = tmp_path / "without-sdk"
    venv.EnvBuilder(with_pip=False).create(target)
    binary = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    script = "from repovox.sdk_trust import approved_trust; approved_trust()"
    result = subprocess.run(
        [str(binary), "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "apps/api")},
        timeout=30,
    )
    assert result.returncode != 0
    assert "required SDK trust material unavailable" in result.stderr


def test_missing_certifi_import_even_if_metadata_exists(monkeypatch):
    import builtins

    original = builtins.__import__

    def absent(name, *args, **kwargs):
        if name == "certifi":
            raise ImportError("synthetic absent certifi")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", absent)
    with pytest.raises(trust.SDKTrustError, match="unavailable"):
        client()


def test_selected_path_and_transport_mutation_rejected(monkeypatch):
    import botocore.httpsession

    with monkeypatch.context() as m:
        m.setattr(botocore.httpsession, "get_cert_path", lambda verify: "/unapproved.pem")
        with pytest.raises(trust.SDKTrustError, match="selected an unapproved"):
            client()
    c = client()
    c._endpoint.http_session._verify = False  # Intentionally adversarial fixture only.
    with pytest.raises(trust.SDKTrustError, match="bypassed"):
        trust.validate_client(c)


def test_shared_default_files_ignored_and_actual_stubber_remains_offline(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".aws").mkdir(parents=True)
    (home / ".aws/config").write_text("[default]\nca_bundle=/unapproved.pem\n")
    (home / ".aws/credentials").write_text("[default]\ncredential_process=never-run\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    c = client()
    trust.validate_client(c)
    with Stubber(c) as stub:
        stub.add_response("list_buckets", {"Buckets": []}, {})
        assert c.list_buckets()["Buckets"] == []
    # No real network request: hook fires before the HTTP session send.
    with patch.object(
        c._endpoint.http_session, "send", side_effect=AssertionError("socket reached")
    ):
        with pytest.raises(trust.SDKTrustError, match="offline transport"):
            c.list_buckets()


def test_only_reviewed_factory_constructs_repo_sdk_transports():
    for directory in [ROOT / "apps/api", ROOT / "tools", ROOT / "tests"]:
        for path in directory.rglob("*.py"):
            if path.name == "sdk_trust.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    assert not (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "boto3"
                        and node.func.attr in {"Session", "client", "resource"}
                    ), str(path)


def test_lint_audit_hook_refuses_socket_without_contact():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys,socket;sys.path.insert(0,'tools');"
            "from security_sdk_lint import refuse_network;"
            "sys.addaudithook(refuse_network);socket.socket().connect(('127.0.0.1',9))",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=10,
    )
    assert result.returncode != 0
    assert "offline lint network forbidden" in result.stderr

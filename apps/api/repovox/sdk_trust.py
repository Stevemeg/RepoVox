"""Versioned, fail-closed SDK trust boundary. No credential discovery or AWS activation.

This module never edits or monkeypatches an SDK. Only create_client constructs
RepoVox transports. The offline adapter remains independently network-disabled.
"""

import hashlib
import importlib.metadata
import os
import re
import ssl
import stat
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Any

CERTIFI_VERSION = "2026.10.19"
SDK_VERSION = "1.43.118"
CERTIFI_SHA256 = "50f79f98dac192b20dbf73f35c56f0b0c557ab267ff5199d1117cc1180b70785"
FALLBACK_SHA256 = "4658f1ddf2d0a9e70c8f760323704c8fb9c0bf2f1f1e7d2dbc5939ca04ea2612"
BLOCKED = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
}
OVERRIDES = {
    "AWS_CA_BUNDLE",
    "AWS_CONFIG_FILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
}


class SDKTrustError(ValueError):
    """Unapproved trust input; error messages never include credentials or values."""


@lru_cache(maxsize=4)
def validate_bundle(body: bytes, expected: str) -> dict[str, object]:
    blocks = re.findall(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", body, re.S)
    if not blocks:
        raise SDKTrustError("missing certificates")
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=body.decode("ascii"))
        hashes = {hashlib.sha256(x).hexdigest() for x in context.get_ca_certs(binary_form=True)}
    except (ValueError, ssl.SSLError, UnicodeError) as exc:
        raise SDKTrustError("invalid CA bytes") from exc
    if not hashes or hashes & BLOCKED:
        raise SDKTrustError("blocked or empty CA roots")
    if hashlib.sha256(body).hexdigest() != expected:
        raise SDKTrustError("unapproved CA commitment")
    return {"sha256": expected, "certificates": len(hashes), "fingerprints": sorted(hashes)}


def _installed_file(package: str, relative: str) -> Path:
    dist = importlib.metadata.distribution(package)
    path = Path(str(dist.locate_file(relative)))
    base = Path(sysconfig.get_path("purelib")).resolve()
    if path.is_symlink() or not path.resolve().is_relative_to(base):
        raise SDKTrustError("package outside selected interpreter")
    if not dist.files or relative not in {str(x).replace("\\", "/") for x in dist.files}:
        raise SDKTrustError("file absent from distribution inventory")
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_nlink != 1:
        raise SDKTrustError("invalid package file")
    return path.resolve()


def approved_trust(*, verify: object = True, config: Any = None) -> dict[str, Any]:
    if verify is not True:
        raise SDKTrustError("verify must be True; custom paths are not authorized")
    if any(
        name.upper() in OVERRIDES or name.upper().startswith("AWS_ENDPOINT_URL")
        for name in os.environ
    ):
        raise SDKTrustError("unreviewed environment override")
    if config is not None and (
        config.proxies or config.proxies_config or config.client_cert is not None
    ):
        raise SDKTrustError("unreviewed proxy or client certificate configuration")
    try:
        if importlib.metadata.version("certifi") != CERTIFI_VERSION:
            raise SDKTrustError("unsupported certifi version")
        if importlib.metadata.version("botocore") != SDK_VERSION:
            raise SDKTrustError("unsupported botocore version")
        if importlib.metadata.version("boto3") not in {"1.43.111", "1.43.116"}:
            raise SDKTrustError("unsupported boto3 version")
        cert_path = _installed_file("certifi", "certifi/cacert.pem")
        fallback = _installed_file("botocore", "botocore/cacert.pem")
        import certifi
        from botocore.httpsession import get_cert_path

        chosen = get_cert_path(True)
        if (
            Path(certifi.where()).resolve() != cert_path
            or chosen is None
            or Path(chosen).resolve() != cert_path
        ):
            raise SDKTrustError("SDK selected an unapproved CA path")
        active = validate_bundle(cert_path.read_bytes(), CERTIFI_SHA256)
        dormant = validate_bundle(fallback.read_bytes(), FALLBACK_SHA256)
    except (ImportError, OSError) as exc:
        raise SDKTrustError("required SDK trust material unavailable") from exc
    return {
        "path": str(cert_path),
        "active": active,
        "fallback": dormant,
        "botocore": SDK_VERSION,
        "boto3": importlib.metadata.version("boto3"),
        "certifi": CERTIFI_VERSION,
        "s3transfer": importlib.metadata.version("s3transfer"),
    }


def validate_client(client: Any) -> None:
    trust = approved_trust(config=client.meta.config)
    # Read-only inspection, pinned to the reviewed SDK version; no monkeypatch.
    transport = client._endpoint.http_session
    if (
        getattr(client, "_repovox_trust", None) != CERTIFI_SHA256
        or transport._verify != trust["path"]
        or transport._proxy_config.settings
        or transport._proxy_config._proxies
    ):
        raise SDKTrustError("client bypassed approved transport construction")


def create_client(
    service: str,
    *,
    endpoint_url: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
    region_name: str,
    config: Any = None,
    verify: object = True,
    offline: bool = False,
) -> Any:
    trust = approved_trust(verify=verify, config=config)
    if not aws_access_key_id or not aws_secret_access_key or not region_name or not endpoint_url:
        raise SDKTrustError("explicit endpoint, identity and region required")
    import boto3.session
    import botocore.session
    from botocore.config import Config

    session = botocore.session.Session()
    # Explicitly ignore default ~/.aws files without opening or inspecting them.
    session.set_config_variable("config_file", os.devnull)
    session.set_config_variable("credentials_file", os.devnull)
    session.set_config_variable("profile", None)
    # Preserve boto3's S3 client customizations; only its underlying trust/session
    # configuration is constrained. No default global boto3 session is used.
    # Generated stubs expose only Literal service overloads, whereas this single
    # trusted factory handles multiple selected services. Keep that dynamic SDK
    # boundary local; application S3 callers retain their existing S3Client type.
    boto_session: Any = boto3.session.Session(botocore_session=session)
    client: Any = boto_session.client(
        service,
        endpoint_url=endpoint_url,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region_name,
        verify=trust["path"],
        config=(config or Config()).merge(Config(proxies={}, proxies_config={})),
    )
    client._repovox_trust = CERTIFI_SHA256

    def before_send(**kwargs: Any) -> None:
        validate_client(client)
        if offline:
            raise SDKTrustError("offline transport network forbidden")

    client.meta.events.register_first("before-send.*.*", before_send)
    validate_client(client)
    return client

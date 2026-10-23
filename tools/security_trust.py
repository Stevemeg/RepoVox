"""Inspect effective and dormant Python CA stores without network access.

Version/audit success alone does not establish trust-store removal. The exact DER
fingerprint below is absent from the reviewed certifi 2026.10.19 wheel. It is the
emSign ECC Root CA - G3 removed from the prior locked 2026.7.22 wheel.
"""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import re
import ssl
import subprocess
import sys
import sysconfig
import zipfile
from pathlib import Path

BLOCKED = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",  # emSign ECC G3
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",  # AAA, DSA-6572-1
}


def inspect_pem(body: bytes) -> dict[str, object]:
    blocks = re.findall(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", body, re.S)
    if not blocks:
        raise ValueError("empty or unrecognized CA store")
    hashes = {
        hashlib.sha256(ssl.PEM_cert_to_DER_cert(p.decode("ascii"))).hexdigest() for p in blocks
    }
    if hashes & BLOCKED:
        raise ValueError("compromised emSign trust anchor remains")
    return {
        "sha256": hashlib.sha256(body).hexdigest(),
        "certificates": len(hashes),
        "blocked_anchors": 0,
    }


def report(
    *, certifi_required: bool = False, uv_required: bool = False, seed_required: bool = False
) -> dict[str, object]:
    result: dict[str, object] = {"python": sys.version, "openssl": ssl.OPENSSL_VERSION}
    for module, required in (("certifi", certifi_required), ("pip._vendor.certifi", False)):
        try:
            spec = importlib.util.find_spec(module)
        except ModuleNotFoundError:
            spec = None
        if spec is None or spec.origin is None:
            if required:
                raise ValueError(f"missing required {module}")
            continue
        path = Path(spec.origin).with_name("cacert.pem")
        result[module] = {"path": str(path), **inspect_pem(path.read_bytes())}
    for package, minimum in (
        ("certifi", (2026, 10, 19)),
        ("pip", (26, 2, 2)),
        ("uv", (0, 13, 4)),
        ("sigstore", (4, 5, 1)),
    ):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            if package == "uv" and uv_required:
                raise ValueError("missing required uv") from None
            continue
        if tuple(int(x) for x in version.split(".")) < minimum:
            raise ValueError(f"unpatched {package}: {version}")
        result[package + "_version"] = version
    # Inspect dormant ensurepip wheel(s), not just the active pip installation.
    spec = importlib.util.find_spec("ensurepip")
    seeds = []
    if spec and spec.origin:
        for wheel in sorted(Path(spec.origin).parent.glob("_bundled/*.whl")):
            with zipfile.ZipFile(wheel) as archive:
                bundle = archive.read("pip/_vendor/certifi/cacert.pem")
            try:
                seed = inspect_pem(bundle)
                clean = True
            except ValueError:
                if seed_required:
                    raise
                seed, clean = {}, False
            seeds.append(
                {
                    "wheel": str(wheel),
                    "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                    "clean": clean,
                    "ca_bundle": seed,
                }
            )
    if seed_required and (
        len(seeds) != 1
        or not seeds[0]["clean"]
        or seeds[0]["wheel_sha256"]
        != "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
    ):
        raise ValueError("missing or ambiguous ensurepip seed")
    result["ensurepip"] = seeds
    context = ssl.create_default_context()
    roots = context.get_ca_certs(binary_form=True)
    if not roots or {hashlib.sha256(x).hexdigest() for x in roots} & BLOCKED:
        raise ValueError("system TLS default roots absent or compromised")
    result["system_roots"] = {"certificates": len(roots), "blocked_anchors": 0}
    # Offline SDK inspection only: no session/client, credentials, API or request.
    spec = importlib.util.find_spec("botocore")
    if spec and spec.origin:
        from botocore.httpsession import get_cert_path

        fallback = Path(spec.origin).with_name("cacert.pem")
        chosen = get_cert_path(True)
        if not chosen:
            raise ValueError("missing SDK selected CA store")
        selected = Path(chosen)
        active = inspect_pem(selected.read_bytes())
        try:
            fallback_store = {"status": "NO_LISTED_ANCHOR", **inspect_pem(fallback.read_bytes())}
        except ValueError:
            fallback_store = {
                "status": "UNRESOLVED_DORMANT_CA",
                "sha256": hashlib.sha256(fallback.read_bytes()).hexdigest(),
            }
        result["botocore"] = {
            "version": importlib.metadata.version("botocore"),
            "selected_bundle": str(selected),
            "selected_inspection": active,
            "fallback_path": str(fallback),
            "fallback_inspection": fallback_store,
        }
        # Exit success here attests active trust checks only, never full bundled
        # store remediation. The unresolved fallback blocks overall acceptance.
        result["all_bundled_stores_remediated"] = (
            fallback_store["status"] != "UNRESOLVED_DORMANT_CA"
        )
    if uv_required:
        import shutil

        binary = shutil.which("uv")
        if binary is None:
            raise ValueError("missing uv binary")
        version = subprocess.check_output([binary, "--version"], text=True).strip()
        if not version.startswith("uv " + importlib.metadata.version("uv") + " "):
            raise ValueError("PATH uv differs from the inspected installed package")
        if Path(binary).resolve().parent != Path(sysconfig.get_path("scripts")).resolve():
            raise ValueError("uv is outside the selected Python environment")
        result["uv_binary"] = {
            "path": binary,
            "sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
            "version": version,
            "bundle_evidence": (
                "hash-pinned upstream patched build; opaque Rust roots, not a Python PEM"
            ),
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certifi", action="store_true")
    parser.add_argument("--uv", action="store_true")
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            report(certifi_required=args.certifi, uv_required=args.uv, seed_required=args.seed),
            indent=2,
        )
    )

"""Offline negative controls; synthetic PEM/layouts are not provider proof."""

import hashlib
import ssl
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import trustme

from tools import security_bootstrap as bootstrap
from tools import security_trust as trust


def test_corrupted_bootstrap_wheel_cannot_be_executed() -> None:
    with pytest.raises(ValueError, match="commitment mismatch"):
        bootstrap.verified_wheel(b"untrusted wheel bytes")


def test_empty_ca_store_is_not_clean() -> None:
    with pytest.raises(ValueError, match="empty"):
        trust.inspect_pem(b"not a certificate")


def test_der_identity_is_checked_independent_of_pem_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pem = trustme.CA().cert_pem.bytes()
    der = ssl.PEM_cert_to_DER_cert(pem.decode("ascii"))
    monkeypatch.setattr(trust, "BLOCKED", {hashlib.sha256(der).hexdigest()})
    with pytest.raises(ValueError, match="compromised"):
        trust.inspect_pem(b"# harmless label\n" + pem)


def test_valid_synthetic_ca_inspection() -> None:
    pem = trustme.CA().cert_pem.bytes()
    report = trust.inspect_pem(pem)
    assert report == {
        "sha256": hashlib.sha256(pem).hexdigest(),
        "certificates": 1,
        "blocked_anchors": 0,
    }


@pytest.fixture
def seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Layout-only fixture: bypass hash here; separate corruption test checks the
    # actual pinned verifier. Real CI bootstrap uses the actual PSF wheel.
    monkeypatch.setattr(bootstrap, "verified_wheel", lambda b: b)
    monkeypatch.setattr(bootstrap.sysconfig, "get_config_var", lambda key: None)
    module = tmp_path / "__init__.py"
    module.write_text('_PIP_VERSION = "25.0.1"\n', encoding="utf-8")
    bundle = tmp_path / "_bundled"
    bundle.mkdir()
    (bundle / "pip-25.0.1-py3-none-any.whl").write_bytes(b"old synthetic seed")
    return module


def test_dormant_seed_replaced_and_idempotent(seed: Path) -> None:
    bootstrap.repair_ensurepip(seed, b"new synthetic seed")
    bootstrap.repair_ensurepip(seed, b"new synthetic seed")
    assert seed.read_text(encoding="utf-8") == '_PIP_VERSION = "26.2.2"\n'
    bundle = seed.parent / "_bundled"
    assert [p.name for p in bundle.iterdir()] == [bootstrap.WHEEL_NAME]
    assert (bundle / bootstrap.WHEEL_NAME).read_bytes() == b"new synthetic seed"


def test_unexpected_seed_inventory_fails_before_mutation(seed: Path) -> None:
    extra = seed.parent / "_bundled/other.whl"
    extra.write_bytes(b"unexpected")
    before = seed.read_bytes()
    with pytest.raises(ValueError, match="inventory"):
        bootstrap.repair_ensurepip(seed, b"new synthetic seed")
    assert seed.read_bytes() == before and extra.read_bytes() == b"unexpected"


def test_unfamiliar_seed_layout_fails(seed: Path) -> None:
    seed.write_text("# unknown layout\n", encoding="utf-8")
    with pytest.raises(ValueError, match="layout"):
        bootstrap.repair_ensurepip(seed, b"new synthetic seed")


def test_external_seed_override_refused(seed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap.sysconfig, "get_config_var", lambda key: "/unreviewed")
    with pytest.raises(ValueError, match="external seed"):
        bootstrap.repair_ensurepip(seed, b"new synthetic seed")


def test_seed_wheel_and_bundle_commitments_remain_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pem = trustme.CA().cert_pem.bytes()
    bundle = tmp_path / "_bundled"
    bundle.mkdir()
    wheel = bundle / "pip-synthetic.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pip/_vendor/certifi/cacert.pem", pem)
    original = trust.importlib.util.find_spec
    monkeypatch.setattr(
        trust.importlib.util,
        "find_spec",
        lambda name: (
            SimpleNamespace(origin=str(tmp_path / "__init__.py"))
            if name == "ensurepip"
            else original(name)
        ),
    )
    result = trust.report()
    observed = result["ensurepip"][0]
    assert observed["wheel_sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert observed["ca_bundle"]["sha256"] == hashlib.sha256(pem).hexdigest()
    with pytest.raises(ValueError, match="ambiguous ensurepip seed"):
        trust.report(seed_required=True)  # A clean synthetic CA is not the PSF wheel.


def test_wrong_path_uv_cannot_pass_using_new_package_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    original = trust.importlib.metadata.version
    monkeypatch.setattr(
        trust.importlib.metadata,
        "version",
        lambda name: "0.13.4" if name == "uv" else original(name),
    )
    monkeypatch.setattr(shutil, "which", lambda name: "synthetic-old-uv")
    monkeypatch.setattr(trust.subprocess, "check_output", lambda *a, **k: "uv 0.11.29 (old)")
    with pytest.raises(ValueError, match="PATH uv differs"):
        trust.report(uv_required=True)


def test_clean_ca_bytes_do_not_waive_old_package_version(monkeypatch: pytest.MonkeyPatch) -> None:
    original = trust.importlib.metadata.version
    monkeypatch.setattr(
        trust.importlib.metadata,
        "version",
        lambda name: "2026.7.22" if name == "certifi" else original(name),
    )
    with pytest.raises(ValueError, match="unpatched certifi"):
        trust.report()

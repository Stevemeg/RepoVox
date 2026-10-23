"""Hash-anchored PSF pip bootstrap; no old package manager makes network requests.

The wheel SHA-256 is published in the 2026-10-20 Python security announcement.
Normal HTTPS validation remains enabled. This modifies only the selected Python.
"""

import argparse
import hashlib
import importlib.util
import re
import subprocess
import sys
import sysconfig
import tempfile
import urllib.request
from pathlib import Path

PIP_VERSION = "26.2.2"
PIP_SHA256 = "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
PIP_URL = (
    "https://files.pythonhosted.org/packages/3f/06/"
    "3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/"
    "pip-26.2.2-py3-none-any.whl"
)
WHEEL_NAME = f"pip-{PIP_VERSION}-py3-none-any.whl"
ROOT = Path(__file__).resolve().parents[1]


def verified_wheel(body: bytes) -> bytes:
    if hashlib.sha256(body).hexdigest() != PIP_SHA256:
        raise ValueError("PSF pip wheel commitment mismatch")
    return body


def repair_ensurepip(module: Path, body: bytes) -> None:
    """Replace the dormant seed too, only in an explicitly disposable base Python.

    Fail the build on an unfamiliar layout. A failed build is never published.
    Host/venv use does not call this without the explicit CLI option.
    """
    verified_wheel(body)
    text = module.read_text(encoding="utf-8")
    matches = re.findall(r'^_PIP_VERSION = "([\d.]+)"$', text, re.M)
    if len(matches) != 1 or sysconfig.get_config_var("WHEEL_PKG_DIR"):
        raise ValueError("unreviewed ensurepip layout or external seed directory")
    old = matches[0]
    bundle = module.parent / "_bundled"
    original = bundle / f"pip-{old}-py3-none-any.whl"
    if module.is_symlink() or bundle.is_symlink() or original.is_symlink():
        raise ValueError("linked ensurepip seed")
    if sorted(p.name for p in bundle.glob("*.whl")) != [original.name]:
        raise ValueError("unexpected ensurepip seed inventory")
    if old == PIP_VERSION:
        verified_wheel(original.read_bytes())
        return
    replacement = bundle / WHEEL_NAME
    with replacement.open("xb") as stream:
        stream.write(body)
    module.write_text(
        text.replace(f'_PIP_VERSION = "{old}"', f'_PIP_VERSION = "{PIP_VERSION}"'), encoding="utf-8"
    )
    original.unlink()
    print(f"ensurepip seed: {old} -> {PIP_VERSION}; SHA-256 {PIP_SHA256}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pip-only", action="store_true")
    parser.add_argument(
        "--repair-ensurepip",
        action="store_true",
        help="disposable CI/container base Python only; never a shared host",
    )
    args = parser.parse_args()
    if args.repair_ensurepip and sys.prefix != sys.base_prefix:
        raise ValueError("refuse changing shared base Python from a virtual environment")
    with urllib.request.urlopen(PIP_URL, timeout=60) as response:
        body = verified_wheel(response.read(2_000_001))
    with tempfile.TemporaryDirectory(prefix="repovox-public-pip-") as directory:
        wheel = Path(directory) / WHEEL_NAME
        wheel.write_bytes(body)
        # Execute only hash-verified pip, installing itself locally without an index.
        code = (
            "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); "
            "runpy.run_module('pip',run_name='__main__')"
        )
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                code,
                str(wheel),
                "--isolated",
                "--disable-pip-version-check",
                "install",
                "--no-index",
                "--no-deps",
                "--upgrade",
                str(wheel),
            ],
            check=True,
        )
        if args.repair_ensurepip:
            spec = importlib.util.find_spec("ensurepip")
            if spec is None or spec.origin is None:
                raise ValueError("missing ensurepip seed")
            repair_ensurepip(Path(spec.origin), body)
    if not args.pip_only:
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-m",
                "pip",
                "--isolated",
                "--disable-pip-version-check",
                "install",
                "--require-hashes",
                "--only-binary=:all:",
                "--no-deps",
                "--index-url",
                "https://pypi.org/simple",
                "-r",
                str(ROOT / "tools/requirements-bootstrap.txt"),
            ],
            check=True,
        )
    subprocess.run([sys.executable, "-I", "-m", "pip", "--version"], check=True)


if __name__ == "__main__":
    main()

import math
import re
from collections import Counter
from pathlib import PurePosixPath

from repovox.analysis.common import AnalysisError

HIGH = re.compile(
    r"-----BEGIN (?:[A-Z ]{0,32}PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----"
    r"|AKIA[0-9A-Z]{16}|(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"
    r"|\b(?:sk_live_|xox[baprs]-)[A-Za-z0-9-]{16,}"
    r"|[a-z][a-z0-9+.-]{0,31}://[^\s/@:]{1,256}:[^\s/@]{1,1024}@",
    re.IGNORECASE,
)
ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|secret|client[_-]?secret)\b"
    r"\s*[:=]\s*[\"']([^\"'\r\n]{8,})[\"']"
)
ENTROPY = re.compile(r"[A-Za-z0-9_+/=-]{24,}")
SAFE_VALUES = {"example", "placeholder", "changeme", "redacted"}


def entropy(value: str) -> float:
    return -sum((n / len(value)) * math.log2(n / len(value)) for n in Counter(value).values())


def sensitive_path(path: str) -> bool:
    p = PurePosixPath(path)
    return any(part.lower() in {".ssh", ".aws", ".azure", ".gnupg"} for part in p.parts) or (
        p.name.lower().startswith(".env")
        or p.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}
        or p.name.lower()
        in {"credentials", "credentials.json", "secrets.json", "id_rsa", ".npmrc", ".pypirc"}
    )


def scan(text: str) -> list[tuple[int, int]]:
    lower = text.lower()
    if any(
        marker in lower
        for marker in [
            "-----begin",
            "akia",
            "ghp_",
            "gho_",
            "ghu_",
            "ghs_",
            "ghr_",
            "github_pat_",
            "sk_live_",
            "xox",
            "://",
        ]
    ) and HIGH.search(text):
        raise AnalysisError("secret_detected")
    spans: list[tuple[int, int]] = []
    for match in ASSIGNMENT.finditer(text):
        value = match.group(1)
        if value.lower() not in SAFE_VALUES:
            # Includes secret-looking test fixtures. No override based on filename.
            raise AnalysisError("secret_detected")
    for match in ENTROPY.finditer(text):
        value = match.group()
        if entropy(value) >= 4.4 and not re.fullmatch(r"[a-fA-F0-9]+", value):
            spans.append(match.span())
    return spans


def redact(text: str) -> tuple[str, list[dict[str, int | str]]]:
    spans = scan(text)
    records: list[dict[str, int | str]] = []
    for start, end in reversed(spans):
        line = text[:start].count("\n") + 1
        records.append({"start_line": line, "end_line": line, "reason": "suspicious_entropy"})
        text = text[:start] + "[REDACTED]" + text[end:]
    return text, list(reversed(records))


def screen_bytes(body: bytes) -> None:
    # All acquired files, including unsupported/binary/oversized ones, are screened.
    # Latin-1 is a byte-preserving view for ASCII credential patterns.
    for offset in range(0, len(body), 64 * 1024):
        scan(body[max(0, offset - 4096) : offset + 64 * 1024].decode("latin-1"))

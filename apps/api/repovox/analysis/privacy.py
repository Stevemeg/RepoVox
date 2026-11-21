"""Fail-closed secret screening of acquired bytes, paths and names (Stage 2, ADR-0033).

Always refused, anywhere in a repository (tests, docs and examples included): a private key
block, a known provider token format, a credential URL whose host is a literal remote name or
address, and any other literal assigned to a password, secret, API key or access token field.

Exempt only when a value is unmistakably not a secret:
- an interpolation template that names a variable: `{password}`, `{settings.DB_PASSWORD}`,
  `${API_KEY}`, `$DB_PASS`, `%(pass)s`, `%s`, `{{ db_password }}`, `env(API_SECRET)` or
  `<your-api-key>`;
- a value made only of placeholder words (`your-api-key-here`, `test-secret-key`, `changeme`),
  a mask (`xxxxxxxx`, `********`) or a digit run (`12345678`);
- for database and queue URLs only, a local host with a short development password or a
  template. Local means loopback (`localhost`, `127.0.0.1`, `::1`) or a single-label name with
  no dot (`postgres`, `db`, `fba_rabbitmq`, a documentation `host`), which no public DNS
  resolves.

A credential URL with a templated password is exempt only when its host is also a template or
local. A dotted host name or an IP address other than loopback is never local. Provider
formats and private keys are checked first and never exempt.
"""

import math
import re
from collections import Counter
from pathlib import PurePosixPath

from repovox.analysis.common import AnalysisError

HIGH = re.compile(
    r"-----BEGIN (?:[A-Z ]{0,32}PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----"
    r"|AKIA[0-9A-Z]{16}|(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"
    r"|\b(?:sk_live_|xox[baprs]-)[A-Za-z0-9-]{16,}",
    re.IGNORECASE,
)
# Provider token formats, case-sensitive as issued. Each needs the character mix every issued
# token has (a digit, or both letter cases), so `sk-xxxxxxxxxxxxxxxxxxxx`, `hf_xxxx...` or a
# kebab-case name written as a placeholder is not taken for a key.
PROVIDERS = re.compile(
    r"\bsk-(?:proj-|ant-|svcacct-|admin-)?(?=[A-Za-z0-9_-]*[0-9])(?=[A-Za-z0-9_-]*[A-Z])"
    r"[A-Za-z0-9_-]{20,}"
    r"|\bASIA(?=[0-9A-Z]{0,15}[0-9])[0-9A-Z]{16}\b"
    r"|\bAIza(?=[0-9A-Za-z_-]{0,34}[0-9])[0-9A-Za-z_-]{35}"
    r"|\bglpat-(?=[0-9A-Za-z_-]*[0-9])[0-9A-Za-z_-]{20,}"
    r"|\brk_live_(?=[0-9A-Za-z]*[0-9])[0-9A-Za-z]{16,}"
    r"|\b(?:hf|npm)_(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*[a-z])[A-Za-z0-9]{34,}"
    r"|\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}"
)
MARKERS = (
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
)
PROVIDER_MARKERS = ("sk-", "asia", "aiza", "glpat-", "rk_live_", "hf_", "npm_", "pypi-")
CREDENTIAL_URL = re.compile(
    r"([a-z][a-z0-9+.-]{0,31})://([^\s/@:]{1,256}):([^\s/@]{1,1024})@([^\s/?#@\"'`,;]{0,256})",
    re.IGNORECASE,
)
ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|secret|client[_-]?secret)\b"
    r"\s*[:=]\s*[\"']([^\"'\r\n]{8,})[\"']"
)
ENTROPY = re.compile(r"[A-Za-z0-9_+/=-]{24,}")
SAFE_VALUES = {"example", "placeholder", "changeme", "redacted"}
# A value is a placeholder only when every one of its words is here.
PLACEHOLDER_WORDS = frozenset(
    """
    your my api key keys here change changeme changethis me this replace replaceme placeholder
    example sample dummy fake mock test testing secret password passwd pass token not a an
    the value insert put enter redacted
    """.split()
)
# A variable name inside a template: snake_case or lower-case dotted, ALL_CAPS, or camelCase
# without digits, with attribute or subscript steps. A mixed-case run with digits, such as a
# random secret in braces, is not one.
NAME = (
    r"(?:[a-z_][a-z0-9_]*|[a-z][a-zA-Z]*|[A-Z_][A-Z0-9_]*)"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*|\[['\"]?[A-Za-z_][A-Za-z0-9_]*['\"]?\])*"
)
# An f-string expression: a name, or a call on names such as `{quote_plus(password)}`.
EXPRESSION = NAME + r"(?:\((?:\s*" + NAME + r"\s*,?)*\))?"
TEMPLATE = re.compile(
    r"\{\{\s*" + NAME + r"(?:\s*\|\s*[a-z_]+)?\s*\}\}"  # Jinja or Mustache: {{ db_password }}
    r"|\$\{" + NAME + r"(?::-?[^{}]{0,40})?\}"  # shell or JavaScript: ${API_KEY}
    r"|(?<![A-Za-z0-9])\$[A-Z_][A-Z0-9_]{1,63}\b"  # shell: $DB_PASS
    r"|%\([a-z_][a-z0-9_]{0,40}\)[sdr]|%[sdr]"  # printf: %(pass)s, %s
    r"|\{" + EXPRESSION + r"(?:![rs])?(?::[^{}]{0,10})?\}|\{\d{0,2}\}"  # f-string, format
    r"|<[A-Za-z][A-Za-z .-]{0,60}>"  # documentation: <your-api-key>
    r"|\benv\([A-Z_][A-Z0-9_]{0,63}\)"  # configuration substitution: env(API_SECRET)
)
# Hosts a development credential may name: the machine itself, or a single-label name such as
# a Compose or Kubernetes service (`postgres`, `fba_rabbitmq`) or a documentation `host`. A
# single label has no dot, so it is never a public domain name or an IP address.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres", "db", "redis", "mysql"})
SERVICE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,62}")
DATABASE_SCHEME = re.compile(
    r"(?:postgres(?:ql)?|mysql|mariadb|redis|rediss|mongodb(?:\+srv)?|amqps?)(?:\+[a-z0-9]+)?",
    re.IGNORECASE,
)
DEV_PASSWORDS = frozenset(
    """
    password passwd pass postgres root admin test dev changeme secret guest 123456 12345678
    """.split()
)
# One plain word of a file or directory name: lowercase, Capitalised, an ACRONYM or a number.
WORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


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


def placeholder(value: str) -> bool:
    """A human placeholder, never a secret: placeholder words only (`your-api-key-here`,
    `test_password`, `not-a-secret`), a mask (`xxxxxxxx`, `********`), or an ascending digit
    run. A run of any other repeated character is a stand-in secret and still fails."""
    text = value.strip().lower()
    if len(text) >= 6 and (set(text) in ({"x"}, {"*"}) or "1234567890".startswith(text)):
        return True
    words = [w for w in re.split(r"[-_ .]+", text) if w]
    return bool(words) and all(w in PLACEHOLDER_WORDS for w in words)


def mixed(piece: str) -> bool:
    """Letters of both cases with digits, or a letter-digit run: how a random secret looks."""
    kinds = sum((any(c.islower() for c in piece), any(c.isupper() for c in piece)))
    return len(piece) >= 3 and any(c.isdigit() for c in piece) and kinds >= 1


def templated(value: str) -> bool:
    """An interpolation template, not a literal: it names a variable and its literal remainder
    is at most a few short plain words (`db_{env}`), never a random run."""
    if TEMPLATE.search(value) is None:
        return False
    pieces = re.findall(r"[A-Za-z0-9]+", TEMPLATE.sub(" ", value))
    return sum(map(len, pieces)) <= 12 and all(
        placeholder(p) or (len(p) <= 4 and not mixed(p)) for p in pieces
    )


def literal_secret(value: str) -> bool:
    """A value assigned to a credential field that is neither a template nor a placeholder."""
    return value.lower() not in SAFE_VALUES and not placeholder(value) and not templated(value)


def host_of(raw: str) -> str:
    """The host of a URL authority after `@`, without its port; `[::1]` becomes `::1`."""
    if raw.startswith("["):
        return raw[1 : raw.find("]")] if "]" in raw else raw
    return raw.split(":", 1)[0]


def local_or_template(raw: str) -> tuple[bool, bool]:
    """(local, templated) for the host part of a credential URL."""
    if TEMPLATE.match(raw) is not None:
        return False, True
    host = host_of(raw)
    return host.lower() in LOCAL_HOSTS or SERVICE_NAME.fullmatch(host) is not None, False


def credential_url_allowed(scheme: str, password: str, host: str) -> bool:
    """A credential URL that carries no secret. A templated password needs a templated or local
    host; a literal password needs a database or queue scheme, a local host and a short
    development value. A literal remote host is never allowed."""
    local, templated_host = local_or_template(host)
    if templated(password) and (local or templated_host):
        return True
    return (
        local
        and DATABASE_SCHEME.fullmatch(scheme) is not None
        and len(password) <= 32
        and (password.lower() in DEV_PASSWORDS or placeholder(password))
    )


def scan(text: str) -> list[tuple[int, int]]:
    lower = text.lower()
    if any(marker in lower for marker in MARKERS) and HIGH.search(text):
        raise AnalysisError("secret_detected")
    if any(marker in lower for marker in PROVIDER_MARKERS) and PROVIDERS.search(text):
        raise AnalysisError("secret_detected")
    if "://" in text:
        for match in CREDENTIAL_URL.finditer(text):
            scheme, _, password, host = match.groups()
            if not credential_url_allowed(scheme, password, host):
                raise AnalysisError("secret_detected")
    spans: list[tuple[int, int]] = []
    for match in ASSIGNMENT.finditer(text):
        if literal_secret(match.group(1)):
            # Includes secret-looking test fixtures. No override based on filename.
            raise AnalysisError("secret_detected")
    for match in ENTROPY.finditer(text):
        value = match.group()
        if entropy(value) >= 4.4 and not re.fullmatch(r"[a-fA-F0-9]+", value):
            spans.append(match.span())
    return spans


def prose_name(value: str) -> bool:
    """Two or more plain words joined by `/`, `-` or `_`, none as long as a token run."""
    words = [word for word in re.split(r"[/_-]", value) if word]
    return len(words) > 1 and all(len(w) < 24 and WORD.fullmatch(w) for w in words)


def path_spans(path: str) -> list[tuple[int, int]]:
    """Suspicious-entropy spans of a repository path; any span fails `secret_detected`.

    `scan` runs on the whole path unchanged, so credential patterns and assignments raise and
    every entropy span is found as before. Only a span made of plain words (such as
    `docs/adr/ADR-0019-production-observability`) is then set aside as a name. A span with a
    mixed-case, letter-and-digit, `+` or `=` word, or a single unsegmented run, still counts.
    """
    return [(start, end) for start, end in scan(path) if not prose_name(path[start:end])]


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

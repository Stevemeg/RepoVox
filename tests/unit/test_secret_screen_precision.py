"""Stage 2 secret screening: templates, placeholders and local development URLs pass; real
secrets still fail closed anywhere in a repository (ADR-0033).

Every secret-shaped value is assembled at run time, so no credential-like literal is committed
and the repository's own history scan stays clean. Nothing here touches a network.
"""

from pathlib import Path

import pytest
from repovox.analysis.common import AnalysisError
from repovox.analysis.filtering import filter_sources
from repovox.analysis.privacy import (
    credential_url_allowed,
    placeholder,
    redact,
    scan,
    screen_bytes,
    sensitive_path,
    templated,
)

SHA = "c" * 40
J = "".join


def refused(text: str) -> bool:
    try:
        scan(text)
    except AnalysisError as error:
        assert error.code == "secret_detected"
        return True
    return False


def assign(field: str, value: str) -> str:
    return J([field, ' = "', value, '"'])


# ------------------------------------------------------------------------------- must pass

TEMPLATES = [
    J(['url = f"postgresql://', "{user}:{password}", '@{host}/db"']),
    J(['url = f"postgresql+asyncpg://', "{settings.DB_USER}:{settings.DB_PASSWORD}", '@{host}"']),
    J(['url = f"mysql://{user}:', "{quote_plus(password)}", '@{host}:3306/app"']),
    J(['url = f"redis://:', "{os.environ['REDIS_PASSWORD']}", '@{host}:6379"']),
    "DATABASE_URL=${DATABASE_URL}",
    J(["postgres://${DB_USER}:", "${DB_PASS}", "@${DB_HOST:-localhost}:5432/app"]),
    J(["amqp://$MQ_USER:", "$MQ_PASS", "@localhost:5672"]),
    assign("password", "{{ db_password }}"),
    assign("password", "%(password)s"),
    assign("api_key", "<your-api-key>"),
    assign("secret", "env(SUPABASE_AUTH_EXTERNAL_APPLE_SECRET)"),
]
PLACEHOLDERS = [
    assign("api_key", "your-api-key-here"),
    assign("api_key", "your_api_key_here"),
    assign("password", "changeme"),
    assign("password", "change_me"),
    assign("password", "replace_me"),
    assign("secret", "test-secret-key"),
    assign("password", "test_password"),
    assign("secret", "not-a-secret"),
    assign("password", "xxxxxxxx"),
    assign("password", "********"),
    assign("password", "12345678"),
    assign("api_key", "placeholder"),
    J(["OPENAI_API_KEY=", "sk-", "x" * 24]),  # a placeholder in the key's own shape
]
LOCAL_URLS = [
    J(["postgresql+psycopg://user:", "password", "@localhost:5432/test"]),
    J(["postgresql://postgres:", "postgres", "@127.0.0.1:5432/app"]),
    J(["redis://:", "password", "@[::1]:6379/0"]),
    J(["mongodb://root:", "root", "@db:27017"]),
    J(["amqp://guest:", "guest", "@localhost:5672//"]),
    J(["mysql+pymysql://user:", "password", "@host:3306/db"]),  # documentation host
    J(["amqp://guest:", "guest", "@fba_rabbitmq:5672//"]),  # Compose service name
]


@pytest.mark.parametrize("text", TEMPLATES + PLACEHOLDERS + LOCAL_URLS)
def test_templates_placeholders_and_local_development_urls_pass(text: str) -> None:
    assert not refused(text)


# ------------------------------------------------------------------------------- must fail

PROVIDERS = [
    J(["sk-proj-", "Ab3dE5fG7hI9jK1lM2nO4pQ6rS8tU0vW"]),
    J(["sk-ant-", "ap", "i03-", "Zx8Yw7Vu", "6Ts5Rq4P", "o3Nm2Lk1", "Ji0Hg9Fe"]),
    J(["sk-", "T3stK3yAbcdEfgh1JklMnoPqrStu2vwxYz34"]),
    J(["gh", "p_", "a" * 36]),
    J(["gh", "o_", "B" * 36]),
    J(["github", "_pat_", "1" * 22, "_", "c" * 59]),
    J(["AK", "IA", "Z" * 16]),
    J(["AS", "IA", "Q7", "W" * 14]),
    J(["AI", "za", "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q"]),
    J(["xo", "xb-", "1234567890-", "abcdefghijklmnop"]),
    J(["xo", "xp-", "1234567890-", "abcdefghijklmnop"]),
    J(["gl", "pat-", "a1B2c3D4e5F6g7H8i9J0"]),
    J(["sk", "_live_", "4eC39HqLyjWDarjtT1zdp7dc"]),
    J(["rk", "_live_", "4eC39HqLyjWDarjtT1zdp7dc"]),
    J(["-----BEGIN ", "PRIVATE KEY-----"]),
    J(["-----BEGIN ", "OPENSSH PRIVATE KEY-----"]),
]
LITERALS = [
    assign("secret", J(["K9x!mP2q", "R7vL4nW8zB3j"])),
    assign("password", J(["canary-secret", "-fixture"])),
    assign("api_key", J(["abc$", "Xyz123defGhi"])),  # a `$` inside a secret is not a template
    assign("password", J(["{", "Kx9mP2qR7vL4", "}"])),  # braces around a secret are not one
    assign("secret", J(["env(", "Kx9mP2qR7vL4", ")"])),
    assign("secret", "k" * 25),  # a repeated non-mask character is a stand-in secret
]
REMOTE_URLS = [
    J(["postgresql://user:", "password", "@prod-db.company.com:5432/app"]),
    J(["postgresql://user:", "${DB_PASS}", "@prod-db.company.com/app"]),  # template, remote
    J(["https://user:", "{password}", "@api.example.com/v1"]),
    J(["postgresql://user:", "password", "@10.0.0.5:5432/app"]),  # IP address
    J(["amqp://guest:", "guest", "@mq.internal.example.com:5672"]),
    J(["postgresql://postgres:", "Xk29fLq8Zr", "@localhost:5432/db"]),  # random, local
    J(["postgresql://app:", "Xk29fLq8Zr", "@proddb:5432/app"]),  # random, service name
    J(["postgresql://user:", "canarypass", "@host/db"]),
    J(["https://user:", "pass", "@localhost/api"]),  # not a database or queue URL
]


@pytest.mark.parametrize("text", PROVIDERS + LITERALS + REMOTE_URLS)
def test_real_secrets_still_fail_closed(text: str) -> None:
    assert refused(text)


@pytest.mark.parametrize("text", PROVIDERS[:4] + LITERALS[:1] + REMOTE_URLS[:1])
@pytest.mark.parametrize("where", ["tests/test_settings.py", "README.md", "docs/setup.md"])
def test_no_path_exempts_a_real_secret(tmp_path: Path, where: str, text: str) -> None:
    (tmp_path / "app.py").write_text("def run() -> None:\n    return None\n")
    target = tmp_path / where
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Example configuration\n" + text + "\n")
    with pytest.raises(AnalysisError, match="secret_detected") as error:
        filter_sources(tmp_path, "example/demo", SHA, "b" * 64)
    assert text not in str(error.value)


def test_templates_and_placeholders_in_tests_and_readme_reach_parsing(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run() -> None:\n    return None\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_settings.py").write_text("\n".join(TEMPLATES[:4] + LOCAL_URLS) + "\n")
    (tmp_path / "README.md").write_text("# Demo\n\n" + "\n".join(PLACEHOLDERS) + "\n")
    (tmp_path / ".env.example").write_text(J(["DATABASE_URL=", LOCAL_URLS[0], "\n"]))
    result = filter_sources(tmp_path, "example/demo", SHA, "b" * 64)
    reasons = {f["path"]: f["reason"] for f in result["files"]}
    assert reasons[".env.example"] == "sensitive_path"  # Still excluded, though it passed.
    assert reasons["tests/test_settings.py"] == "supported_source"


def test_sensitive_files_and_large_bodies_keep_their_rules() -> None:
    assert sensitive_path(".env") and sensitive_path("deploy/.env.production")
    assert sensitive_path("keys/server.pem") and sensitive_path(".ssh/id_rsa")
    with pytest.raises(AnalysisError, match="secret_detected"):
        screen_bytes(b"x" * (64 * 1024 - 8) + J(["gh", "p_", "a" * 36]).encode())
    with pytest.raises(AnalysisError, match="secret_detected"):
        screen_bytes(b"y" * (64 * 1024 - 20) + REMOTE_URLS[0].encode())


def test_the_exemption_rules_are_narrow() -> None:
    assert placeholder("your-api-key-here") and placeholder("********")
    assert placeholder("1234567890") and not placeholder("12345679")
    assert not placeholder("canary-secret-fixture") and not placeholder("hunter2hunter")
    assert templated("{password}") and templated("${API_KEY}") and templated("<your-api-key>")
    assert not templated("Kx9!$ABCDEFG") and not templated("{Kx9mP2qR7vL4}")
    assert credential_url_allowed("postgresql", "password", "localhost:5432")
    assert not credential_url_allowed("postgresql", "password", "db.example.com:5432")
    assert not credential_url_allowed("https", "password", "localhost")
    assert credential_url_allowed("https", "{password}", "{host}")
    assert not credential_url_allowed("https", "{password}", "api.example.com")


def test_exempt_text_redacts_without_failing_and_keeps_entropy_spans() -> None:
    token = J(["aB3dE5fG7hI9jK1l", "M2nO4pQ6rS8tU0vW"])
    shown, records = redact(TEMPLATES[0] + "\n" + PLACEHOLDERS[0] + "\n" + token)
    assert token not in shown and records == [
        {"start_line": 3, "end_line": 3, "reason": "suspicious_entropy"}
    ]

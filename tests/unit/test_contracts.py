import pytest
from pydantic import ValidationError
from repovox.core.config import Settings
from repovox.schemas.requests import FixtureInput, ProjectInput


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://github.com/a/b?x=1",
        "https://github.com/a/b#x",
        "https://github.com:443/a/b",
        "https://user:secret@github.com/a/b",
        "https://127.0.0.1/a/b",
        "https://github.com/a/b/tree/main",
        "https://github.com/a/../b",
        "https://github.com/a/%2e%2e",
        "https://evil.test/a/b",
    ],
)
def test_unsupported_locators(url: str) -> None:
    with pytest.raises(ValidationError):
        ProjectInput(title="Demo", repository_url=url)


def test_canonicalization_and_identity_fields() -> None:
    assert (
        ProjectInput(
            title=" Demo ", repository_url="https://github.com/Owner/Repo.git/"
        ).repository_url
        == "https://github.com/owner/repo"
    )
    with pytest.raises(ValidationError):
        ProjectInput(title="Demo", repository_url="https://github.com/a/b", owner_id="forged")
    with pytest.raises(ValidationError):
        FixtureInput(fixture="normal", commit_sha="a" * 40)


@pytest.mark.parametrize(
    "environment,dev_auth,fixtures",
    [("production", True, True), ("production", False, False), ("development", False, False)],
)
def test_production_fail_closed(environment: str, dev_auth: bool, fixtures: bool) -> None:
    with pytest.raises(ValidationError) as failure:
        Settings(
            environment=environment,
            dev_auth=dev_auth,
            fixtures=fixtures,
            database_url="postgresql+psycopg://rv_app@localhost/repovox",
            session_secret="x" * 40,
            storage_access_key="local",
            storage_secret_key="local",
        )
    assert "postgresql+psycopg://" not in str(failure.value)
    assert "x" * 40 not in str(failure.value)

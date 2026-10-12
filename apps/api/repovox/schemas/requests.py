import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignIn(StrictRequest):
    subject: Literal["alex", "sam"]


class ProjectInput(StrictRequest):
    repository_url: str = Field(max_length=250)
    title: str = Field(min_length=1, max_length=100)

    @field_validator("repository_url")
    @classmethod
    def canonical_url(cls, value: str) -> str:
        match = re.fullmatch(
            r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9_.-]{1,100})/?",
            value,
        )
        if not match:
            raise ValueError("Only canonical GitHub repository locators are accepted")
        owner, repo = match.groups()
        if repo.endswith(".git"):
            repo = repo[:-4]
        if not repo or repo in {".", ".."} or owner.endswith("-") or "--" in owner:
            raise ValueError("Invalid GitHub repository locator")
        return f"https://github.com/{owner.lower()}/{repo.lower()}"

    @field_validator("title")
    @classmethod
    def title_text(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("A plain title is required")
        return value


class ProjectUpdate(StrictRequest):
    title: str = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def title_text(cls, value: str) -> str:
        return ProjectInput.title_text(value)


class FixtureInput(StrictRequest):
    fixture: Literal["normal", "transient_once", "permanent_failure"] = "normal"

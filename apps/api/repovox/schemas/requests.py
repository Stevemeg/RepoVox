from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from repovox.analysis.common import AnalysisError
from repovox.analysis.github import repository_url


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
        try:
            return repository_url(value).url
        except AnalysisError:
            raise ValueError("Only canonical GitHub repository locators are accepted") from None

    @field_validator("title")
    @classmethod
    def title_text(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("A plain title is required")
        return value


class AnalysisInput(StrictRequest):
    processing_acknowledged: Literal[True]


class ProjectUpdate(StrictRequest):
    title: str = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def title_text(cls, value: str) -> str:
        return ProjectInput.title_text(value)


class FixtureInput(StrictRequest):
    fixture: Literal["normal", "transient_once", "permanent_failure"] = "normal"

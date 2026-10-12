from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ProjectView(BaseModel):
    id: UUID
    title: str
    repository_url: str
    status: str
    created_at: datetime


class StageView(BaseModel):
    id: UUID
    ordinal: int
    stage_key: str
    state: str
    attempt_count: int
    error_code: str | None
    next_attempt_at: datetime | None


class AttemptView(BaseModel):
    stage_id: UUID
    attempt_no: int
    started_at: datetime
    ended_at: datetime | None
    outcome: str
    error_code: str | None


class HistoryView(BaseModel):
    version: int
    state: str
    error_code: str | None
    created_at: datetime


class UsageView(BaseModel):
    event_type: str
    units: float
    measurements: dict[str, Any]
    created_at: datetime


class JobSummary(BaseModel):
    id: UUID
    project_id: UUID
    project_title: str | None = None
    state: str
    version: int
    synthetic: bool
    fixture: str
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    deadline: datetime
    commit_sha: str | None = None
    repository_url: str | None = None
    pipeline_version: str | None = None


class JobView(JobSummary):
    prior_job_id: UUID | None
    stages: list[StageView]
    attempts: list[AttemptView]
    history: list[HistoryView]
    usage: list[UsageView]

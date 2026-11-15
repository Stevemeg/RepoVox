import os
from functools import lru_cache
from pathlib import Path
from typing import cast
from uuid import UUID

from celery import Celery

from repovox.analysis.runner import AnalysisRunner
from repovox.analysis.transport import GitHubHTTP
from repovox.core.config import Settings
from repovox.db.database import make_engine, verify_role
from repovox.services.jobs import Jobs
from repovox.services.media_jobs import MediaJobs
from repovox.storage import S3Storage
from repovox.synthetic_source import SyntheticSource
from repovox.workers.runtime import Orchestrator

celery = Celery("repovox", broker=os.environ.get("REPOVOX_REDIS_URL", "redis://redis:6379/0"))
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 900},
    broker_connection_timeout=3,
    task_publish_retry=False,
    task_soft_time_limit=110,
    task_time_limit=120,
)


@lru_cache
def runtime() -> Orchestrator:
    settings = Settings()  # type: ignore[call-arg]
    if settings.worker_database_url is None:
        raise RuntimeError("Worker database URL required")
    engine = make_engine(settings.worker_database_url.get_secret_value())
    verify_role(engine, "rv_worker")
    storage = S3Storage(settings)
    token = settings.github_token.get_secret_value() if settings.github_token else None
    # Development and test only: a locally authored synthetic source instead of GitHub.
    source = (
        cast(GitHubHTTP, SyntheticSource(Path(settings.synthetic_source_dir)))
        if settings.synthetic_source_dir
        else GitHubHTTP(token)
    )
    analysis = AnalysisRunner(engine, storage, source) if settings.analysis else None
    return Orchestrator(engine, storage, analysis)


@lru_cache
def media_handoff_service() -> MediaJobs | None:
    """The analysis-to-media handoff for worker maintenance, or None where video is not set up.

    It is the API's own idempotent pass, so waiting video jobs advance with no API process
    running. It uses only existing interfaces: `mv.awaiting`, `mv.attach` and
    `mv.analysis_failed` as `rvm_app`, and owner-scoped tenant reads of the core database as
    `rv_app`, because `rv_worker` reads no tables. Both roles are checked before any use.
    """
    settings = Settings()  # type: ignore[call-arg]
    if not settings.video or settings.media_database_url is None:
        return None
    from repovox.media.worker import make_media_engine  # Media code loads only when used.

    core = make_engine(settings.database_url.get_secret_value())
    try:
        verify_role(core, "rv_app")
        media = make_media_engine(settings.media_database_url.get_secret_value(), "rvm_app")
    except BaseException:
        core.dispose()
        raise
    return MediaJobs(media, core, Jobs(core, settings.fixtures), settings)


def media_handoff() -> int:
    """One handoff pass; without video settings it connects to nothing and returns 0."""
    service = media_handoff_service()
    return 0 if service is None else service.handoff()


def close_media_handoff() -> None:
    if media_handoff_service.cache_info().currsize:
        service = media_handoff_service()
        if service is not None:
            service.engine.dispose()
            service.core.dispose()
    media_handoff_service.cache_clear()


@celery.task(name="repovox.stage")
def stage_task(stage_id: str) -> None:
    runtime().run(UUID(stage_id), f"celery-{os.getpid()}")


@celery.task(name="repovox.cleanup")
def cleanup_task(deletion_id: str) -> None:
    runtime().cleanup(UUID(deletion_id))

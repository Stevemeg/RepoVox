import os
from functools import lru_cache
from uuid import UUID

from celery import Celery

from repovox.analysis.runner import AnalysisRunner
from repovox.analysis.transport import GitHubHTTP
from repovox.core.config import Settings
from repovox.db.database import make_engine, verify_role
from repovox.storage import S3Storage
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
    analysis = AnalysisRunner(engine, storage, GitHubHTTP(token)) if settings.analysis else None
    return Orchestrator(engine, storage, analysis)


@celery.task(name="repovox.stage")
def stage_task(stage_id: str) -> None:
    runtime().run(UUID(stage_id), f"celery-{os.getpid()}")


@celery.task(name="repovox.cleanup")
def cleanup_task(deletion_id: str) -> None:
    runtime().cleanup(UUID(deletion_id))

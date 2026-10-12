import logging
import signal
import threading
from typing import Any

from celery import Celery
from sqlalchemy import Engine, text

from repovox.db.database import rows
from repovox.workers.tasks import celery, runtime

logger = logging.getLogger("repovox.dispatcher")


def dispatch(engine: Engine, delivery: Celery) -> int:
    with engine.connect() as connection:
        batch = rows(connection, "SELECT * FROM rv.dispatch_batch()")
    sent = 0
    for event in batch:
        task = "repovox.stage" if event["event_type"] == "stage" else "repovox.cleanup"
        identifier = event["stage_id"] if event["event_type"] == "stage" else event["event_id"]
        try:
            delivery.send_task(task, args=[str(identifier)], retry=False)
        except Exception:
            logger.warning('{"event":"broker_unavailable"}')
            break  # Leave every unacknowledged event durable. Retry on next bounded poll.
        with engine.begin() as connection:
            connection.execute(text("SELECT rv.published(:id)"), {"id": event["event_id"]})
        sent += 1
    return sent


def main() -> None:
    stop = threading.Event()

    def shutdown(signum: int, frame: Any) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    orchestrator = runtime()
    try:
        while not stop.is_set():
            try:
                orchestrator.reconcile()
                dispatch(orchestrator.engine, celery)
            except Exception:
                logger.warning('{"event":"reconciliation_dependency_unavailable"}')
            stop.wait(5)
    finally:
        orchestrator.engine.dispose()


if __name__ == "__main__":
    main()

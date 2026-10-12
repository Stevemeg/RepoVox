"""Trusted integration fault probe. Parent test kills this process; no source code runs."""

import argparse
import os
import time
from uuid import UUID, uuid4

from repovox.analysis.common import canonical, digest
from repovox.analysis.runner import AnalysisRunner
from repovox.core.config import Settings
from repovox.db.database import make_engine
from repovox.storage import ObjectRef, S3Storage
from repovox.workers.runtime import Orchestrator

parser = argparse.ArgumentParser()
parser.add_argument("stage", type=UUID)
parser.add_argument("--mode", choices=["acquire", "uploaded"], required=True)
args = parser.parse_args()
config = Settings()
assert config.environment == "test" and config.worker_database_url is not None
engine = make_engine(config.worker_database_url.get_secret_value())
storage = S3Storage(config)
orchestrator = Orchestrator(engine, storage)
lease = orchestrator.claim(args.stage, f"actual-fault-process-{os.getpid()}")
assert lease is not None


class InterruptedDownload:
    def download(self, path: str, target: object, limit: int, checkpoint: object) -> None:
        target.write(b"controlled partial archive bytes")
        target.flush()
        print(
            canonical({"ready": True, "mode": "acquire", "pid": os.getpid()}).decode(), flush=True
        )
        while True:
            checkpoint()
            time.sleep(0.2)


if args.mode == "acquire":
    AnalysisRunner(engine, storage, InterruptedDownload()).run(
        lease, lambda: orchestrator.heartbeat(args.stage, lease["fence"])
    )
else:
    body = b"Controlled uploaded orphan; no customer content."
    ref = ObjectRef(
        lease["owner_id"], lease["snapshot_id"], lease["job_id"], uuid4(), digest(body), "analysis"
    )
    storage.write(ref, body)
    print(
        canonical(
            {
                "ready": True,
                "mode": "uploaded",
                "pid": os.getpid(),
                "artifact": str(ref.artifact),
                "checksum": ref.checksum,
            }
        ).decode(),
        flush=True,
    )
    while True:
        time.sleep(0.2)

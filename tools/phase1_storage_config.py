"""Local S3 credential file in a private Docker volume, never in Git."""

import json
import os
from pathlib import Path

config = {
    "identities": [
        {
            "name": "local-admin",
            "credentials": [
                {
                    "accessKey": os.environ["MINIO_ROOT_USER"],
                    "secretKey": os.environ["MINIO_ROOT_PASSWORD"],
                }
            ],
            "actions": ["Admin", "Read", "Write", "List"],
        },
        {
            "name": "local-service",
            "credentials": [
                {
                    "accessKey": os.environ["STORAGE_ACCESS_KEY"],
                    "secretKey": os.environ["STORAGE_SECRET_KEY"],
                }
            ],
            "actions": ["Read:repovox-private", "Write:repovox-private", "List:repovox-private"],
        },
    ]
}
Path("/storage-config/s3.json").write_text(json.dumps(config), encoding="utf-8")

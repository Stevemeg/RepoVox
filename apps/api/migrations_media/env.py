"""Media database migrations. A separate database and version table from the core schema."""

import os

from alembic import context
from sqlalchemy import create_engine

url = os.environ["REPOVOX_MEDIA_MIGRATION_DATABASE_URL"]
engine = create_engine(url)
with engine.connect() as connection:
    if connection.exec_driver_sql("SELECT to_regclass('public.generation_jobs')").scalar():
        raise RuntimeError("media_migration_refuses_core_database")
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()

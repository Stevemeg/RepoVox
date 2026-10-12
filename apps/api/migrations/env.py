import os

from alembic import context
from sqlalchemy import create_engine

url = os.environ["REPOVOX_MIGRATION_DATABASE_URL"]
engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()

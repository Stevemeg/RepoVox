import os
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url


def test_accepted_database_upgrade_preserves_data(admin: Engine) -> None:
    # A separate randomly named disposable database; never downgrades/reset application data.
    database = "repovox_upgrade_test_" + uuid4().hex
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f'CREATE DATABASE "{database}" OWNER rv_migrator'))
    previous = os.environ.get("REPOVOX_MIGRATION_DATABASE_URL")
    migrator_url = make_url(os.environ["REPOVOX_TEST_MIGRATION_URL"]).set(database=database)
    engine = create_engine(make_url(os.environ["REPOVOX_TEST_ADMIN_URL"]).set(database=database))
    config = Config("apps/api/alembic.ini")
    try:
        os.environ["REPOVOX_MIGRATION_DATABASE_URL"] = migrator_url.render_as_string(
            hide_password=False
        )
        command.upgrade(config, "0001")
        project_id = uuid4()
        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO projects(id,owner_id,repository_url,title) VALUES(:id,"
                    "'11111111-1111-4111-8111-111111111111','https://github.com/example/demo',"
                    "'Accepted Phase 1 data')"
                ),
                {"id": project_id},
            )
        command.upgrade(config, "0002")
        with engine.connect() as c:
            legacy = c.scalar(
                text(
                    "SELECT pg_get_functiondef('rv.finish_analysis(uuid,bigint,uuid,"
                    "text,text,bigint,text,jsonb)'::regprocedure)"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as c:
            assert (
                c.scalar(text("SELECT title FROM projects WHERE id=:id"), {"id": project_id})
                == "Accepted Phase 1 data"
            )
            assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0004"
            assert (
                c.scalar(
                    text(
                        "SELECT pg_get_functiondef('rv.cp_original_finish_analysis"
                        "(uuid,bigint,uuid,"
                        "text,text,bigint,text,jsonb)'::regprocedure)"
                    )
                ).replace("rv.cp_original_finish_analysis(", "rv.finish_analysis(")
                == legacy
            )
            assert c.scalar(text("SELECT count(*) FROM users")) == 2
            assert c.scalar(
                text("SELECT relforcerowsecurity FROM pg_class WHERE relname='analysis_results'")
            )
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("REPOVOX_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["REPOVOX_MIGRATION_DATABASE_URL"] = previous
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))

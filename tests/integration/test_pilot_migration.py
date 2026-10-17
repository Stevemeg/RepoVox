"""Upgrade/empty rollback proof uses a separate disposable PostgreSQL database."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


def test_pilot_migration_upgrade_rollback_and_populated_ledger_guard(admin):
    name = "repovox_cp_migration_" + uuid4().hex
    assert name.startswith("repovox_cp_migration_")
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f'CREATE DATABASE "{name}" OWNER rv_migrator'))
    previous = os.environ.get("REPOVOX_MIGRATION_DATABASE_URL")
    url = make_url(os.environ["REPOVOX_TEST_MIGRATION_URL"]).set(database=name)
    check = create_engine(make_url(os.environ["REPOVOX_TEST_ADMIN_URL"]).set(database=name))
    config = Config("apps/api/alembic.ini")
    try:
        os.environ["REPOVOX_MIGRATION_DATABASE_URL"] = url.render_as_string(hide_password=False)
        command.upgrade(config, "0003")
        with check.connect() as c:
            original = c.scalar(
                text("SELECT pg_get_functiondef('rv.claim(uuid,text)'::regprocedure)")
            )
        command.upgrade(config, "head")
        with check.connect() as c:
            assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0004"
            assert not c.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_proc p,"
                    "LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                    "WHERE p.oid='rv.pilot_claim(uuid,uuid,bigint,text,text)'::regprocedure "
                    "AND a.grantee=0 AND a.privilege_type='EXECUTE')"
                )
            )
            assert c.scalar(
                text("SELECT relforcerowsecurity FROM pg_class WHERE relname='pilot_attempts'")
            )
        command.downgrade(config, "0003")
        with check.connect() as c:
            assert (
                c.scalar(text("SELECT pg_get_functiondef('rv.claim(uuid,text)'::regprocedure)"))
                == original
            )
            assert c.scalar(text("SELECT to_regclass('public.pilot_attempts')")) is None
            assert c.scalar(text("SELECT count(*) FROM users")) == 2
        command.upgrade(config, "head")
        identity = uuid4()
        with check.begin() as c:
            c.execute(
                text(
                    "INSERT INTO pilot_attempts(id,owner_id,manifest_body,manifest_sha,expires_at) "
                    "VALUES(:id,'11111111-1111-4111-8111-111111111111',"
                    "'{}',repeat('a',64),now()+interval '1 minute')"
                ),
                {"id": identity},
            )
        with pytest.raises(DBAPIError, match="pilot_rollback_requires_empty_ledger"):
            command.downgrade(config, "0003")
        with check.connect() as c:
            assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0004"
            assert (
                c.scalar(text("SELECT count(*) FROM pilot_attempts WHERE id=:id"), {"id": identity})
                == 1
            )
    finally:
        check.dispose()
        if previous is None:
            os.environ.pop("REPOVOX_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["REPOVOX_MIGRATION_DATABASE_URL"] = previous
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))

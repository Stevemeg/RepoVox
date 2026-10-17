from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text


def make_engine(url: str) -> Engine:
    return create_engine(
        url,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=5000 -c idle_in_transaction_session_timeout=10000",
        },
    )


def verify_role(engine: Engine, expected: str) -> None:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        if row.rolname != expected or row.rolsuper or row.rolbypassrls:
            raise RuntimeError("Unsafe database role")
        if connection.scalar(
            text(
                "SELECT count(*) FROM pg_class "
                "WHERE relnamespace='public'::regnamespace "
                "AND relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
            )
        ):
            raise RuntimeError("Runtime role must not own application tables")
        if connection.scalar(text("SELECT version_num FROM alembic_version")) not in {
            "0003",
            "0004",
        }:
            raise RuntimeError("Database migration required")


@contextmanager
def tenant(engine: Engine, owner: UUID) -> Iterator[Connection]:
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('repovox.owner_id', :owner, true)"), {"owner": str(owner)}
        )
        yield connection


def rows(connection: Connection, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(text(sql), params).mappings()]

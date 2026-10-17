"""Additive attempt fencing. Apply only with separately authorized database scope."""

import re
from pathlib import Path

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

WRAPPED = (
    "admit",
    "admit_analysis",
    "delete_project",
    "claim",
    "valid_lease",
    "fail_analysis",
    "reconcile",
    "dispatch_batch",
    "published",
    "cancel",
    "finish_analysis",
    "finish_analysis_v23",
)


def originals() -> dict[str, str]:
    result = {}
    for name in ("foundation.sql", "phase2.sql", "canonical_facts.sql"):
        sql = (Path(__file__).parents[1] / name).read_text(encoding="utf-8")
        for function in WRAPPED:
            match = re.search(rf"CREATE FUNCTION rv\.{function}\(.*?\$\$;", sql, re.DOTALL)
            if match:
                result[function] = match[0]
    if set(result) != set(WRAPPED):
        raise RuntimeError("pilot_original_function_missing")
    return result


def execute(sql: str) -> None:
    op.get_bind().exec_driver_sql(sql.replace("%", "%%"))


def upgrade() -> None:
    execute("GRANT CREATE ON SCHEMA rv TO rv_executor; SET LOCAL ROLE rv_executor;")
    for name, sql in originals().items():
        execute(sql.replace(f"rv.{name}(", f"rv.cp_original_{name}(", 1))
    execute((Path(__file__).parents[1] / "pilot_control.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    # Never delete an attempt/evidence ledger to make rollback appear successful.
    execute(
        "GRANT CREATE ON SCHEMA rv TO rv_executor; SET LOCAL ROLE rv_executor; "
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM pilot_attempts) THEN "
        "RAISE EXCEPTION 'pilot_rollback_requires_empty_ledger'; END IF; END $$;"
    )
    for sql in originals().values():
        execute(sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    execute((Path(__file__).parents[1] / "pilot_control_down.sql").read_text(encoding="utf-8"))
    for name in WRAPPED:
        execute(
            "DO $$ DECLARE f regprocedure; BEGIN FOR f IN SELECT oid::regprocedure "
            "FROM pg_proc WHERE pronamespace='rv'::regnamespace "
            f"AND proname='cp_original_{name}' LOOP EXECUTE 'DROP FUNCTION '||f; "
            "END LOOP; END $$;"
        )
    execute(
        "RESET ROLE; DROP TABLE pilot_audit,pilot_validations,pilot_bindings,pilot_attempts; "
        "REVOKE CREATE ON SCHEMA rv FROM rv_executor;"
    )

"""Owner isolation, durable workflow and future persistence boundaries."""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).parents[1] / "foundation.sql").read_text(encoding="utf-8")
    # exec_driver_sql passes a parameter mapping to psycopg; escape SQL format() markers.
    op.get_bind().exec_driver_sql(sql.replace("%", "%%"))


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled: restore a local backup or explicitly reset")

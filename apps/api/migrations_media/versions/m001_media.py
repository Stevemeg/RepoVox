"""Initial media schema: video jobs on stages 10-15, fenced leases, publication, expiry."""

from pathlib import Path

from alembic import op

revision = "m001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).parents[1] / "media.sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql.replace("%", "%%"))


def downgrade() -> None:
    # Never discard published media or job history to make a rollback appear clean. Row security
    # is forced on these tables and the migrator has no policy, so the check counts as the
    # internal role; counted as the migrator it would see no rows and always pass.
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL ROLE rvm_executor")
    bind.exec_driver_sql(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM media_jobs) THEN "
        "RAISE EXCEPTION 'media_rollback_requires_empty_database'; END IF; END $$;"
    )
    bind.exec_driver_sql("RESET ROLE")
    # Functions depend on the table row types and triggers depend on the functions, so the
    # schema goes first.
    bind.exec_driver_sql(
        "DROP SCHEMA mv CASCADE; DROP TABLE media_videos,media_artifacts,media_history,"
        "media_attempts,media_stages,media_jobs;"
    )

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
    # Never discard published media or job history to make a rollback appear clean.
    op.get_bind().exec_driver_sql(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM media_jobs) THEN "
        "RAISE EXCEPTION 'media_rollback_requires_empty_database'; END IF; END $$;"
    )
    op.get_bind().exec_driver_sql(
        "DROP TABLE media_videos,media_artifacts,media_history,media_attempts,media_stages,"
        "media_jobs; DROP SCHEMA mv CASCADE;"
    )

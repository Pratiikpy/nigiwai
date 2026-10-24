"""atlas: the opt-in neighbourhood roll-up and the function that rebuilds it

Revision ID: 0016
Revises: 0015
"""

from pathlib import Path

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0016_atlas.sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "DROP FUNCTION IF EXISTS atlas_rebuild(); DROP TABLE IF EXISTS atlas_cell;"
        " ALTER TABLE business DROP COLUMN IF EXISTS atlas_opt_in_at, DROP COLUMN IF EXISTS atlas_opt_in;"
    )

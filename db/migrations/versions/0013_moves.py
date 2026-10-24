"""moves: the slot a move was aimed at, its end date and a note

Revision ID: 0013
Revises: 0012
"""

from pathlib import Path

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0013_moves.sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE move DROP CONSTRAINT IF EXISTS move_weekdays_valid, DROP CONSTRAINT IF EXISTS move_ended,"
        " DROP CONSTRAINT IF EXISTS move_hours_order, DROP CONSTRAINT IF EXISTS move_hours_pair,"
        " DROP COLUMN IF EXISTS note, DROP COLUMN IF EXISTS hour_to, DROP COLUMN IF EXISTS hour_from,"
        " DROP COLUMN IF EXISTS weekdays, DROP COLUMN IF EXISTS ended_on;"
    )

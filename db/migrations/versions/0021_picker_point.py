"""picker point: the venue's position for a guest's place search, through one definer function

Revision ID: 0021
Revises: 0020
"""

from pathlib import Path

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0021_picker_point.sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP FUNCTION IF EXISTS public_survey_point(uuid)")

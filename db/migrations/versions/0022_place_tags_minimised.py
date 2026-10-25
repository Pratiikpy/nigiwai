"""place tags minimised: only the tags that say what a place is, serves and feels like stay stored

Revision ID: 0022
Revises: 0021
"""

from pathlib import Path

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0022_place_tags_minimised.sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    # The tags that were removed are not kept anywhere, on purpose: they cannot be put back. The function goes; the data stays minimised.
    op.get_bind().exec_driver_sql("DROP FUNCTION IF EXISTS minimise_place_tags(text[])")

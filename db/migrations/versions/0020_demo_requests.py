"""demo requests: venues a visitor asks for, built from public lineups and kept for a week

Revision ID: 0020
Revises: 0019
"""

from pathlib import Path

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0020_demo_requests.sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "REVOKE DELETE ON demo_venue FROM nigiwai_app; DROP INDEX IF EXISTS demo_venue_place_idx;"
        " ALTER TABLE demo_venue DROP COLUMN IF EXISTS requested_at, DROP COLUMN IF EXISTS place_mbid, DROP COLUMN IF EXISTS requested;"
    )

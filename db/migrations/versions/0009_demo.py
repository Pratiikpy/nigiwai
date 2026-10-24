"""demo: the public demo venues for judge mode

Revision ID: 0009
Revises: 0008
"""

from pathlib import Path

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0009_demo.sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP TABLE IF EXISTS demo_venue CASCADE;")
    bind.exec_driver_sql("DELETE FROM tenant WHERE id = '6e1c0de0-0000-4000-8000-00000000d3a0';")

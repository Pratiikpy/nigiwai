"""onboarding: the interview, the confirmed profile and the dashboard plan

Revision ID: 0012
Revises: 0011
"""

from pathlib import Path

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0012_onboarding.sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "DROP TABLE IF EXISTS dashboard_plan CASCADE; DROP TABLE IF EXISTS business_profile CASCADE;"
        " DROP TABLE IF EXISTS onboarding_session CASCADE;"
    )

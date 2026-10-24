"""login tables: row-level security, with definer functions for the lookups made before anyone is signed in

Revision ID: 0019
Revises: 0018
"""

from pathlib import Path

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0019_login_rls.sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE app_session DISABLE ROW LEVEL SECURITY; DROP POLICY IF EXISTS own_sessions ON app_session;"
        " ALTER TABLE app_user DISABLE ROW LEVEL SECURITY; DROP POLICY IF EXISTS own_login ON app_user;"
        " DROP FUNCTION IF EXISTS auth_session(bytea); DROP FUNCTION IF EXISTS auth_user_by_email(text);"
    )

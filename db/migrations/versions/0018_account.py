"""account: a recovery code instead of an email reset, and deleting an account and its data

Revision ID: 0018
Revises: 0017
"""

from pathlib import Path

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0018_account.sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "DROP FUNCTION IF EXISTS sole_owner_of(uuid); DROP FUNCTION IF EXISTS delete_tenant(uuid, uuid);"
        " ALTER TABLE app_user DROP COLUMN IF EXISTS recovery_set_at, DROP COLUMN IF EXISTS recovery_hash;"
    )

"""team: invitations by link, the member list, and an account that always keeps an owner

Revision ID: 0017
Revises: 0016
"""

from pathlib import Path

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0017_team.sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "DROP TRIGGER IF EXISTS keep_one_owner_upd ON membership; DROP TRIGGER IF EXISTS keep_one_owner_del ON membership;"
        " DROP FUNCTION IF EXISTS keep_one_owner(); DROP FUNCTION IF EXISTS team_members(uuid);"
        " DROP FUNCTION IF EXISTS invitation_accept(bytea, uuid); DROP FUNCTION IF EXISTS invitation_peek(bytea);"
        " DROP TABLE IF EXISTS invitation CASCADE;"
    )

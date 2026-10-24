"""tribes: tribe versions, the job queue, recomputation triggers and the card lookup

Revision ID: 0003
Revises: 0002
"""

from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0003_tribes.sql"


def upgrade() -> None:
    # A raw cursor with no parameters: psycopg would treat a % in the SQL as a placeholder otherwise.
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    """Restore the two public functions exactly as 0001 defined them, then drop what this revision added."""
    original = (SQL.parent / "0001_foundation.sql").read_text(encoding="utf-8")
    start = original.index("CREATE OR REPLACE FUNCTION public_insert_response(")
    end = original.index("REVOKE ALL ON FUNCTION public_resolve_qr(bytea) FROM PUBLIC;")
    cursor = op.get_bind().connection.cursor()
    cursor.execute(original[start:end])
    op.get_bind().exec_driver_sql(
        """
        DROP FUNCTION IF EXISTS public_card_tribes(uuid);
        DROP FUNCTION IF EXISTS public_card_context(bytea);
        DROP FUNCTION IF EXISTS enqueue_recompute(uuid, uuid, interval);
        DROP TABLE IF EXISTS job, tribe_version CASCADE;
        """
    )

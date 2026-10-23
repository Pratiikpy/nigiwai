"""foundation: accounts, tenancy, surveys, responses, Qloo cache, traces, quota, audit

Revision ID: 0001
Revises:
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0001_foundation.sql"


def upgrade() -> None:
    # A raw cursor with no parameters: psycopg would treat the %I in format() calls as placeholders otherwise.
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP FUNCTION IF EXISTS public_delete_response(bytea);
        DROP FUNCTION IF EXISTS public_insert_response(uuid, uuid, integer, text, text, text, smallint, text, text[], text[], bytea);
        DROP FUNCTION IF EXISTS public_resolve_qr(bytea);
        DROP TABLE IF EXISTS audit_log, quota_ledger, qloo_call, trace, qloo_response, qloo_entity, pick, response,
          survey, consent_text, qr_point, location, business, membership, tenant, app_session, app_user CASCADE;
        DROP FUNCTION IF EXISTS current_tenant();
        DROP FUNCTION IF EXISTS current_app_user();
        """
    )

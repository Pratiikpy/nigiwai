"""consent text v1 (English)

Revision ID: 0002
Revises: 0001
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

BODY = Path(__file__).resolve().parents[3] / "apps" / "api" / "src" / "nigiwai_api" / "consent" / "v1.en.md"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO consent_text (version, language, body) VALUES ('v1', 'en', :body) ON CONFLICT (version) DO NOTHING"
        ),
        {"body": BODY.read_text(encoding="utf-8").strip()},
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM consent_text WHERE version = 'v1'"))

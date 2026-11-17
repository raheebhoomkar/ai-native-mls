"""media redacted kind

Revision ID: 74839bf69e55
Revises: 0a9be0054641
Create Date: 2026-11-17 12:06:55.830258

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "74839bf69e55"
down_revision: str | Sequence[str] | None = "0a9be0054641"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow redacted copies as media derivatives (Sprint 9)."""
    op.drop_constraint("ck_media_assets_kind", "media_assets", type_="check")
    op.create_check_constraint(
        "ck_media_assets_kind", "media_assets", "kind IN ('original', 'thumbnail', 'redacted')"
    )


def downgrade() -> None:
    """Fails while redacted rows exist; remove them first."""
    op.drop_constraint("ck_media_assets_kind", "media_assets", type_="check")
    op.create_check_constraint(
        "ck_media_assets_kind", "media_assets", "kind IN ('original', 'thumbnail')"
    )

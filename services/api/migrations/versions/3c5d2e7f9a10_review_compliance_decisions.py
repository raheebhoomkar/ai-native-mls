"""review compliance decisions

Revision ID: 3c5d2e7f9a10
Revises: fbc1f17e77ed
Create Date: 2026-11-17 20:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c5d2e7f9a10"
down_revision: str | Sequence[str] | None = "fbc1f17e77ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "decision IN ('accepted', 'edited', 'rejected')"
NEW = (
    "decision IN ('accepted', 'edited', 'rejected', 'dismissed', 'edits_requested', "
    "'appealed', 'upheld', 'overturned')"
)


def upgrade() -> None:
    """Allow compliance review decisions and the appeal trail (Sprint 11)."""
    op.drop_constraint("ck_review_decisions_decision", "review_decisions", type_="check")
    op.create_check_constraint("ck_review_decisions_decision", "review_decisions", NEW)


def downgrade() -> None:
    """Fails while compliance decisions exist; remove them first."""
    op.drop_constraint("ck_review_decisions_decision", "review_decisions", type_="check")
    op.create_check_constraint("ck_review_decisions_decision", "review_decisions", OLD)

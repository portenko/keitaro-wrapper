"""widen offer_changes.action for share edits

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    with op.batch_alter_table("offer_changes") as b:
        b.alter_column("action", existing_type=sa.String(10), type_=sa.String(20), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("offer_changes") as b:
        b.alter_column("action", existing_type=sa.String(20), type_=sa.String(10), existing_nullable=False)

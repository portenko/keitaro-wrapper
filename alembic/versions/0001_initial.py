"""initial tables

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "campaign_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("keitaro_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("geo", sa.String(2), nullable=False),
        sa.Column("offer_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_campaign_records_keitaro_id", "campaign_records", ["keitaro_id"], unique=True)
    op.create_table(
        "offer_changes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("campaign_id", sa.Integer, nullable=False),
        sa.Column("offer_id", sa.Integer, nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_offer_changes_campaign_id", "offer_changes", ["campaign_id"])


def downgrade() -> None:
    op.drop_table("offer_changes")
    op.drop_table("campaign_records")

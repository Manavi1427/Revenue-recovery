"""add payment health fields

Revision ID: 7f2c9e4a1d63
Revises: 3d1f4a6c8b20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7f2c9e4a1d63"
down_revision: Union[str, Sequence[str], None] = "3d1f4a6c8b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recovery_cases", sa.Column("payment_method", sa.String(50), nullable=True))
    op.add_column("payment_events", sa.Column("batch_id", sa.String(64), nullable=True))
    op.create_index("ix_payment_events_batch_id", "payment_events", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_events_batch_id", table_name="payment_events")
    op.drop_column("payment_events", "batch_id")
    op.drop_column("recovery_cases", "payment_method")

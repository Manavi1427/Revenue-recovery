"""add demo experiment metadata

Revision ID: 3d1f4a6c8b20
Revises: bd7ef6f65355
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "3d1f4a6c8b20"
down_revision: Union[str, Sequence[str], None] = "bd7ef6f65355"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recovery_cases", sa.Column("batch_id", sa.String(64), nullable=True))
    op.add_column("recovery_cases", sa.Column("experiment_group", sa.String(20), nullable=True))
    op.create_index("ix_recovery_cases_batch_id", "recovery_cases", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_recovery_cases_batch_id", table_name="recovery_cases")
    op.drop_column("recovery_cases", "experiment_group")
    op.drop_column("recovery_cases", "batch_id")

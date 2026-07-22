"""enable pgvector extension

Revision ID: 674b237a9014
Revises: e2d55a7263fe
Create Date: 2026-07-21 19:21:50.358081

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '674b237a9014'
down_revision: Union[str, Sequence[str], None] = 'e2d55a7263fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")

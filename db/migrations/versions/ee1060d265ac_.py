"""...

Revision ID: ee1060d265ac
Revises: 66c3d3bd2fdc
Create Date: 2026-09-15 10:43:06.666327

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee1060d265ac'
down_revision: Union[str, Sequence[str], None] = '66c3d3bd2fdc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

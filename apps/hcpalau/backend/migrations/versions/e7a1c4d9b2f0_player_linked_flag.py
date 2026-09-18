"""Track players marked as linked in the club roster CSV."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7a1c4d9b2f0"
down_revision: Union[str, None] = "d6f2a9b4c7e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("player", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("linked", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("player", recreate="always") as batch_op:
        batch_op.drop_column("linked")

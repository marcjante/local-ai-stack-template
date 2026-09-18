"""Add teams, team memberships and optional event ownership.

Existing events remain valid with a NULL team_id until the import step assigns
them to the legacy Infantil D team.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e8a1f2b6d0"
down_revision: Union[str, None] = "8b5e3f1a2c7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "team",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_team_slug", "team", ["slug"], unique=True)
    op.create_table(
        "teamplayer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "player_id"),
    )
    op.create_index("ix_teamplayer_team_id", "teamplayer", ["team_id"])
    op.create_index("ix_teamplayer_player_id", "teamplayer", ["player_id"])
    # SQLite cannot ALTER TABLE to add a foreign-key constraint. Batch mode
    # keeps this migration valid for both the local SQLite and managed DBs.
    with op.batch_alter_table("event", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("team_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_event_team_id", ["team_id"])
        batch_op.create_foreign_key("fk_event_team_id_team", "team", ["team_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("event", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_event_team_id_team", type_="foreignkey")
        batch_op.drop_index("ix_event_team_id")
        batch_op.drop_column("team_id")
    op.drop_index("ix_teamplayer_player_id", table_name="teamplayer")
    op.drop_index("ix_teamplayer_team_id", table_name="teamplayer")
    op.drop_table("teamplayer")
    op.drop_index("ix_team_slug", table_name="team")
    op.drop_table("team")

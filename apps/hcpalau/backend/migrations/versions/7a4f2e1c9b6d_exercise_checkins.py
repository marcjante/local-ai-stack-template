"""track daily home exercise completion."""

from alembic import op
import sqlalchemy as sa


revision = "7a4f2e1c9b6d"
down_revision = "3d2f7e0a1c4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercisecheckin",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"]),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercise.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "exercise_id", "activity_date"),
    )
    op.create_index("ix_exercisecheckin_player_id", "exercisecheckin", ["player_id"])
    op.create_index("ix_exercisecheckin_exercise_id", "exercisecheckin", ["exercise_id"])
    op.create_index("ix_exercisecheckin_activity_date", "exercisecheckin", ["activity_date"])


def downgrade() -> None:
    op.drop_index("ix_exercisecheckin_activity_date", table_name="exercisecheckin")
    op.drop_index("ix_exercisecheckin_exercise_id", table_name="exercisecheckin")
    op.drop_index("ix_exercisecheckin_player_id", table_name="exercisecheckin")
    op.drop_table("exercisecheckin")

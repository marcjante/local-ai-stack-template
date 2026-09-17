"""store coach-selected weekly exercise lists."""

from alembic import op
import sqlalchemy as sa

revision = "8b5e3f1a2c7d"
down_revision = "7a4f2e1c9b6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weeklyexercise",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"]),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercise.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "week_start", "exercise_id"),
    )
    op.create_index("ix_weeklyexercise_player_id", "weeklyexercise", ["player_id"])
    op.create_index("ix_weeklyexercise_exercise_id", "weeklyexercise", ["exercise_id"])
    op.create_index("ix_weeklyexercise_week_start", "weeklyexercise", ["week_start"])


def downgrade() -> None:
    op.drop_index("ix_weeklyexercise_week_start", table_name="weeklyexercise")
    op.drop_index("ix_weeklyexercise_exercise_id", table_name="weeklyexercise")
    op.drop_index("ix_weeklyexercise_player_id", table_name="weeklyexercise")
    op.drop_table("weeklyexercise")

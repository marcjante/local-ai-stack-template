"""Persist human-reviewable Thesis chapter placement suggestions (Phase 1B2b)."""

from alembic import op
import sqlalchemy as sa

revision = "d3e4f12b9c07"
down_revision = "c2d9e11a04f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_thesis_fragments_project_id", "thesis_fragments", ["project_id", "id"])
    op.create_table(
        "thesis_placement_suggestions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("fragment_id", sa.Text(), nullable=False),
        sa.Column("chapter_id", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("model", sa.Text()),
        sa.Column("prompt_version", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("corrected_chapter_id", sa.Text()),
        sa.Column("reviewer_id", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id", "fragment_id"], ["thesis_fragments.project_id", "thesis_fragments.id"],
                                name="fk_thesis_placement_fragment", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id", "chapter_id"], ["thesis_chapters.project_id", "thesis_chapters.id"],
                                name="fk_thesis_placement_chapter", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id", "corrected_chapter_id"], ["thesis_chapters.project_id", "thesis_chapters.id"],
                                name="fk_thesis_placement_corrected_chapter"),
        sa.UniqueConstraint("project_id", "fragment_id", "chapter_id", name="uq_thesis_placement_target"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_thesis_placement_confidence"),
        sa.CheckConstraint("status IN ('pending','approved','corrected','rejected')", name="ck_thesis_placement_status"),
    )
    op.create_index("idx_thesis_placements_review", "thesis_placement_suggestions", ["project_id", "status", "created_at"])
    op.create_index("idx_thesis_placements_fragment", "thesis_placement_suggestions", ["project_id", "fragment_id"])


def downgrade():
    op.drop_index("idx_thesis_placements_fragment", table_name="thesis_placement_suggestions")
    op.drop_index("idx_thesis_placements_review", table_name="thesis_placement_suggestions")
    op.drop_table("thesis_placement_suggestions")
    op.drop_constraint("uq_thesis_fragments_project_id", "thesis_fragments", type_="unique")

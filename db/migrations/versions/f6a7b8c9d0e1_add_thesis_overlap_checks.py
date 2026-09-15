"""Persist deterministic overlap checks for Thesis versions (Phase 4)."""

from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "thesis_overlap_checks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="completed"),
        sa.Column("max_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("matches", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("checked_by", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id", "version_id"], ["thesis_section_versions.project_id", "thesis_section_versions.id"], ondelete="CASCADE", name="fk_thesis_overlap_version"),
        sa.UniqueConstraint("project_id", "version_id", name="uq_thesis_overlap_version"),
        sa.CheckConstraint("status IN ('pending','completed','failed')", name="ck_thesis_overlap_status"),
        sa.CheckConstraint("max_score >= 0 AND max_score <= 1", name="ck_thesis_overlap_score"),
    )
    op.create_index("idx_thesis_overlap_project", "thesis_overlap_checks", ["project_id", "status"])


def downgrade():
    op.drop_index("idx_thesis_overlap_project", table_name="thesis_overlap_checks")
    op.drop_table("thesis_overlap_checks")

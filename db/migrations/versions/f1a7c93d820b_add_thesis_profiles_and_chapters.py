"""Add the Thesis profile and chapter tree (Phase 1A).

Revision ID: f1a7c93d820b
Revises: ee1060d265ac
"""

from alembic import op
import sqlalchemy as sa


revision = "f1a7c93d820b"
down_revision = "ee1060d265ac"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column(name, sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP"))
        for name in ("created_at", "updated_at")
    ]


def upgrade():
    op.create_table(
        "thesis_profiles",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("author", sa.Text()),
        sa.Column("supervisors", sa.Text()),
        sa.Column("university", sa.Text()),
        sa.Column("program", sa.Text()),
        sa.Column("language", sa.Text(), nullable=False, server_default="es"),
        sa.Column("citation_style", sa.Text()),
        sa.Column("template", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("project_id", name="uq_thesis_profiles_project"),
        sa.CheckConstraint("length(trim(language)) > 0", name="ck_thesis_profile_language"),
    )
    op.create_table(
        "thesis_chapters",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(),
                  sa.ForeignKey("thesis_profiles.project_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("parent_id", sa.Text()),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("chapter_type", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="empty"),
        # The versions domain and its foreign key belong to a later phase.
        sa.Column("approved_version_id", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "id", name="uq_thesis_chapters_project_id"),
        sa.UniqueConstraint("project_id", "code", name="uq_thesis_chapters_project_code"),
        sa.ForeignKeyConstraint(
            ["project_id", "parent_id"], ["thesis_chapters.project_id", "thesis_chapters.id"],
            name="fk_thesis_chapters_parent_project", ondelete="CASCADE",
        ),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_thesis_chapter_parent"),
        sa.CheckConstraint("order_index >= 0", name="ck_thesis_chapter_order"),
        sa.CheckConstraint(
            "length(trim(code)) > 0 AND length(trim(title)) > 0 "
            "AND length(trim(chapter_type)) > 0", name="ck_thesis_chapter_labels",
        ),
        sa.CheckConstraint(
            "status IN ('empty', 'materials_ready', 'draft', 'under_review', 'approved', 'exported')",
            name="ck_thesis_chapter_status",
        ),
    )
    op.create_index("idx_thesis_chapters_structure", "thesis_chapters",
                    ["project_id", "parent_id", "order_index"])


def downgrade():
    op.drop_index("idx_thesis_chapters_structure", table_name="thesis_chapters")
    op.drop_table("thesis_chapters")
    op.drop_table("thesis_profiles")

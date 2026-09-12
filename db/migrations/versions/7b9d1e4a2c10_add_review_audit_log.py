"""add review audit log

Revision ID: 7b9d1e4a2c10
Revises: 503c6cf26eee
Create Date: 2026-09-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7b9d1e4a2c10"
down_revision: Union[str, Sequence[str], None] = "503c6cf26eee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Text(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "review_id",
            sa.Text(),
            sa.ForeignKey("systematic_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            sa.Text(),
            sa.ForeignKey("review_articles.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "extraction_id",
            sa.Text(),
            sa.ForeignKey("review_extractions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column(
            "before_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "after_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "idx_review_audit_project",
        "review_audit_log",
        ["project_id"],
    )
    op.create_index(
        "idx_review_audit_review",
        "review_audit_log",
        ["review_id"],
    )
    op.create_index(
        "idx_review_audit_article",
        "review_audit_log",
        ["article_id"],
    )
    op.create_index(
        "idx_review_audit_extraction",
        "review_audit_log",
        ["extraction_id"],
    )
    op.create_index(
        "idx_review_audit_created_at",
        "review_audit_log",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_review_audit_created_at",
        table_name="review_audit_log",
    )
    op.drop_index(
        "idx_review_audit_extraction",
        table_name="review_audit_log",
    )
    op.drop_index(
        "idx_review_audit_article",
        table_name="review_audit_log",
    )
    op.drop_index(
        "idx_review_audit_review",
        table_name="review_audit_log",
    )
    op.drop_index(
        "idx_review_audit_project",
        table_name="review_audit_log",
    )
    op.drop_table("review_audit_log")

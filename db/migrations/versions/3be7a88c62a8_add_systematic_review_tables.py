"""add systematic review tables

Revision ID: 3be7a88c62a8
Revises: ed4c953f47f2
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa


revision = "3be7a88c62a8"
down_revision = "ed4c953f47f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "systematic_reviews",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Text(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("review_type", sa.Text(), nullable=True),

        sa.Column("research_question", sa.Text(), nullable=True),

        sa.Column("population", sa.Text(), nullable=True),
        sa.Column("intervention", sa.Text(), nullable=True),
        sa.Column("comparator", sa.Text(), nullable=True),
        sa.Column("outcomes", sa.Text(), nullable=True),

        sa.Column("inclusion_criteria", sa.Text(), nullable=True),
        sa.Column("exclusion_criteria", sa.Text(), nullable=True),

        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_index(
        "idx_systematic_reviews_project",
        "systematic_reviews",
        ["project_id"],
    )

    op.create_table(
        "review_searches",
        sa.Column("id", sa.Text(), primary_key=True),

        sa.Column(
            "review_id",
            sa.Text(),
            sa.ForeignKey("systematic_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),

        sa.Column("database_name", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),

        sa.Column("total_found", sa.Integer(), nullable=True),
        sa.Column("imported_count", sa.Integer(), nullable=True),

        sa.Column(
            "searched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_index(
        "idx_review_searches_review",
        "review_searches",
        ["review_id"],
    )

    op.create_table(
        "review_articles",
        sa.Column("id", sa.Text(), primary_key=True),

        sa.Column(
            "review_id",
            sa.Text(),
            sa.ForeignKey("systematic_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),

        sa.Column(
            "search_id",
            sa.Text(),
            sa.ForeignKey("review_searches.id", ondelete="SET NULL"),
            nullable=True,
        ),

        sa.Column("pmid", sa.Text(), nullable=True),
        sa.Column("doi", sa.Text(), nullable=True),

        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=True),
        sa.Column("journal", sa.Text(), nullable=True),
        sa.Column("year", sa.Text(), nullable=True),

        sa.Column(
            "screening_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),

        sa.Column("screening_stage", sa.Text(), nullable=True),

        sa.Column("ai_decision", sa.Text(), nullable=True),
        sa.Column("ai_reason", sa.Text(), nullable=True),
        sa.Column("ai_confidence", sa.Float(), nullable=True),

        sa.Column("human_decision", sa.Text(), nullable=True),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_index(
        "idx_review_articles_review",
        "review_articles",
        ["review_id"],
    )

    op.create_index(
        "idx_review_articles_pmid",
        "review_articles",
        ["pmid"],
    )

    op.create_index(
        "idx_review_articles_doi",
        "review_articles",
        ["doi"],
    )


def downgrade():
    op.drop_index("idx_review_articles_doi", table_name="review_articles")
    op.drop_index("idx_review_articles_pmid", table_name="review_articles")
    op.drop_index("idx_review_articles_review", table_name="review_articles")

    op.drop_table("review_articles")

    op.drop_index("idx_review_searches_review", table_name="review_searches")
    op.drop_table("review_searches")

    op.drop_index(
        "idx_systematic_reviews_project",
        table_name="systematic_reviews",
    )
    op.drop_table("systematic_reviews")

"""add review search strategies

Revision ID: 9f4c7b2a1d8e
Revises: 3be7a88c62a8
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa


revision = "9f4c7b2a1d8e"
down_revision = "3be7a88c62a8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "review_search_strategies",

        sa.Column(
            "id",
            sa.Text(),
            primary_key=True,
        ),

        sa.Column(
            "review_id",
            sa.Text(),
            sa.ForeignKey(
                "systematic_reviews.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),

        sa.Column(
            "database_name",
            sa.Text(),
            nullable=False,
            server_default="PubMed",
        ),

        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),

        sa.Column(
            "query",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "is_valid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),

        sa.Column(
            "accepted_by_database",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),

        sa.Column(
            "total_found",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "query_translation",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "warnings",
            sa.JSON(),
            nullable=True,
        ),

        sa.Column(
            "errors",
            sa.JSON(),
            nullable=True,
        ),

        sa.Column(
            "removed_terms",
            sa.JSON(),
            nullable=True,
        ),

        sa.Column(
            "concepts",
            sa.JSON(),
            nullable=True,
        ),

        sa.Column(
            "model",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "provider",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "human_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),

        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "idx_review_search_strategies_review",
        "review_search_strategies",
        ["review_id"],
    )

    op.create_index(
        "idx_review_search_strategies_database",
        "review_search_strategies",
        ["database_name"],
    )


def downgrade():
    op.drop_index(
        "idx_review_search_strategies_database",
        table_name="review_search_strategies",
    )

    op.drop_index(
        "idx_review_search_strategies_review",
        table_name="review_search_strategies",
    )

    op.drop_table(
        "review_search_strategies"
    )

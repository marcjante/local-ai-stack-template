"""add structured review data extraction

Revision ID: 495645ff5787
Revises: 610bd16b1271
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa


revision = "495645ff5787"
down_revision = "610bd16b1271"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "review_extraction_fields",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "review_id",
            sa.Text(),
            sa.ForeignKey("systematic_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "value_type",
            sa.Text(),
            nullable=False,
            server_default="text",
        ),
        sa.Column(
            "required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
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
        sa.UniqueConstraint(
            "review_id",
            "field_key",
            name="uq_review_extraction_fields_review_key",
        ),
    )

    op.create_index(
        "idx_review_extraction_fields_review",
        "review_extraction_fields",
        ["review_id"],
    )

    op.create_table(
        "review_extractions",
        sa.Column("id", sa.Text(), primary_key=True),
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
            nullable=False,
        ),
        sa.Column(
            "field_id",
            sa.Text(),
            sa.ForeignKey("review_extraction_fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ai_value", sa.JSON(), nullable=True),
        sa.Column("ai_reason", sa.Text(), nullable=True),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("source_location", sa.Text(), nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("human_value", sa.JSON(), nullable=True),
        sa.Column(
            "validation_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewer_id", sa.Text(), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("skills_used", sa.JSON(), nullable=True),
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
        sa.UniqueConstraint(
            "article_id",
            "field_id",
            name="uq_review_extractions_article_field",
        ),
    )

    op.create_index(
        "idx_review_extractions_review",
        "review_extractions",
        ["review_id"],
    )
    op.create_index(
        "idx_review_extractions_article",
        "review_extractions",
        ["article_id"],
    )
    op.create_index(
        "idx_review_extractions_field",
        "review_extractions",
        ["field_id"],
    )
    op.create_index(
        "idx_review_extractions_validation",
        "review_extractions",
        ["validation_status"],
    )

def downgrade():
    op.drop_index(
        "idx_review_extractions_validation",
        table_name="review_extractions",
    )
    op.drop_index(
        "idx_review_extractions_field",
        table_name="review_extractions",
    )
    op.drop_index(
        "idx_review_extractions_article",
        table_name="review_extractions",
    )
    op.drop_index(
        "idx_review_extractions_review",
        table_name="review_extractions",
    )

    op.drop_table("review_extractions")

    op.drop_index(
        "idx_review_extraction_fields_review",
        table_name="review_extraction_fields",
    )

    op.drop_table("review_extraction_fields")

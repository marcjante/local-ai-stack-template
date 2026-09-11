"""add systematic review screening workflow

Revision ID: a7e7e2e6f782
Revises: 495645ff5787
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa


revision = "a7e7e2e6f782"
down_revision = "495645ff5787"
branch_labels = None
depends_on = None


def upgrade():
    # Review articles: normalized identifiers and screening state
    op.add_column("review_articles", sa.Column("doi_normalized", sa.Text(), nullable=True))
    op.add_column("review_articles", sa.Column("pmid_normalized", sa.Text(), nullable=True))
    op.add_column(
        "review_articles",
        sa.Column("title_abstract_status", sa.Text(), nullable=False, server_default="pending"),
    )
    op.add_column(
        "review_articles",
        sa.Column("full_text_status", sa.Text(), nullable=False, server_default="not_started"),
    )
    op.add_column(
        "review_articles",
        sa.Column("full_text_available", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("review_articles", sa.Column("exclusion_reason_code", sa.Text(), nullable=True))
    op.add_column("review_articles", sa.Column("final_decision", sa.Text(), nullable=True))
    op.add_column(
        "review_articles",
        sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "review_articles",
        sa.Column(
            "duplicate_of_article_id",
            sa.Text(),
            sa.ForeignKey("review_articles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("review_articles", sa.Column("duplicate_reason", sa.Text(), nullable=True))

    op.create_index(
        "idx_review_articles_doi_normalized",
        "review_articles",
        ["doi_normalized"],
    )
    op.create_index(
        "idx_review_articles_pmid_normalized",
        "review_articles",
        ["pmid_normalized"],
    )
    op.create_index(
        "idx_review_articles_title_abstract_status",
        "review_articles",
        ["title_abstract_status"],
    )
    op.create_index(
        "idx_review_articles_full_text_status",
        "review_articles",
        ["full_text_status"],
    )
    op.create_index(
        "idx_review_articles_final_decision",
        "review_articles",
        ["final_decision"],
    )
    op.create_index(
        "idx_review_articles_duplicate",
        "review_articles",
        ["is_duplicate"],
    )

    # Partial unique indexes allow duplicate records to be retained when explicitly
    # marked as duplicates while preventing multiple active copies in one review.
    op.create_index(
        "uq_review_articles_review_pmid_normalized",
        "review_articles",
        ["review_id", "pmid_normalized"],
        unique=True,
        postgresql_where=sa.text(
            "pmid_normalized IS NOT NULL AND is_duplicate = false"
        ),
    )
    op.create_index(
        "uq_review_articles_review_doi_normalized",
        "review_articles",
        ["review_id", "doi_normalized"],
        unique=True,
        postgresql_where=sa.text(
            "doi_normalized IS NOT NULL AND is_duplicate = false"
        ),
    )

    # Independent reviewer decisions
    op.create_table(
        "review_screening_decisions",
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
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("exclusion_reason_code", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "stage",
            "reviewer_id",
            name="uq_review_screening_article_stage_reviewer",
        ),
    )

    op.create_index(
        "idx_review_screening_decisions_review",
        "review_screening_decisions",
        ["review_id"],
    )
    op.create_index(
        "idx_review_screening_decisions_article",
        "review_screening_decisions",
        ["article_id"],
    )
    op.create_index(
        "idx_review_screening_decisions_stage",
        "review_screening_decisions",
        ["stage"],
    )
    op.create_index(
        "idx_review_screening_decisions_reviewer",
        "review_screening_decisions",
        ["reviewer_id"],
    )

    # Conflicts between reviewers and their resolution
    op.create_table(
        "review_screening_conflicts",
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
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "article_id",
            "stage",
            name="uq_review_screening_conflict_article_stage",
        ),
    )

    op.create_index(
        "idx_review_screening_conflicts_review",
        "review_screening_conflicts",
        ["review_id"],
    )
    op.create_index(
        "idx_review_screening_conflicts_article",
        "review_screening_conflicts",
        ["article_id"],
    )
    op.create_index(
        "idx_review_screening_conflicts_status",
        "review_screening_conflicts",
        ["status"],
    )


def downgrade():
    op.drop_index(
        "idx_review_screening_conflicts_status",
        table_name="review_screening_conflicts",
    )
    op.drop_index(
        "idx_review_screening_conflicts_article",
        table_name="review_screening_conflicts",
    )
    op.drop_index(
        "idx_review_screening_conflicts_review",
        table_name="review_screening_conflicts",
    )
    op.drop_table("review_screening_conflicts")

    op.drop_index(
        "idx_review_screening_decisions_reviewer",
        table_name="review_screening_decisions",
    )
    op.drop_index(
        "idx_review_screening_decisions_stage",
        table_name="review_screening_decisions",
    )
    op.drop_index(
        "idx_review_screening_decisions_article",
        table_name="review_screening_decisions",
    )
    op.drop_index(
        "idx_review_screening_decisions_review",
        table_name="review_screening_decisions",
    )
    op.drop_table("review_screening_decisions")

    op.drop_index(
        "uq_review_articles_review_doi_normalized",
        table_name="review_articles",
    )
    op.drop_index(
        "uq_review_articles_review_pmid_normalized",
        table_name="review_articles",
    )
    op.drop_index(
        "idx_review_articles_duplicate",
        table_name="review_articles",
    )
    op.drop_index(
        "idx_review_articles_final_decision",
        table_name="review_articles",
    )
    op.drop_index(
        "idx_review_articles_full_text_status",
        table_name="review_articles",
    )
    op.drop_index(
        "idx_review_articles_title_abstract_status",
        table_name="review_articles",
    )
    op.drop_index(
        "idx_review_articles_pmid_normalized",
        table_name="review_articles",
    )
    op.drop_index(
        "idx_review_articles_doi_normalized",
        table_name="review_articles",
    )

    op.drop_column("review_articles", "duplicate_reason")
    op.drop_column("review_articles", "duplicate_of_article_id")
    op.drop_column("review_articles", "is_duplicate")
    op.drop_column("review_articles", "final_decision")
    op.drop_column("review_articles", "exclusion_reason_code")
    op.drop_column("review_articles", "full_text_available")
    op.drop_column("review_articles", "full_text_status")
    op.drop_column("review_articles", "title_abstract_status")
    op.drop_column("review_articles", "pmid_normalized")
    op.drop_column("review_articles", "doi_normalized")

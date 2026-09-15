"""Add Thesis chapter sources, versions and claim traceability (Phase 3A)."""

from alembic import op
import sqlalchemy as sa

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f12b9c07"
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))
            for name in ("created_at", "updated_at")]


def upgrade():
    op.create_table(
        "thesis_section_sources",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("chapter_id", sa.Text(), nullable=False),
        sa.Column("fragment_id", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.Text()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id", "chapter_id"], ["thesis_chapters.project_id", "thesis_chapters.id"], ondelete="CASCADE", name="fk_thesis_source_chapter"),
        sa.ForeignKeyConstraint(["project_id", "fragment_id"], ["thesis_fragments.project_id", "thesis_fragments.id"], ondelete="CASCADE", name="fk_thesis_source_fragment"),
        sa.UniqueConstraint("project_id", "chapter_id", "fragment_id", name="uq_thesis_section_source"),
        sa.CheckConstraint("purpose IN ('data','evidence','method','context','appendix','style_rule')", name="ck_thesis_source_purpose"),
    )
    op.create_index("idx_thesis_sources_chapter", "thesis_section_sources", ["project_id", "chapter_id"])
    op.create_table(
        "thesis_section_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("chapter_id", sa.Text(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("instructions", sa.Text()),
        sa.Column("model", sa.Text()),
        sa.Column("provider", sa.Text()),
        sa.Column("created_by", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id", "chapter_id"], ["thesis_chapters.project_id", "thesis_chapters.id"], ondelete="CASCADE", name="fk_thesis_version_chapter"),
        sa.UniqueConstraint("project_id", "chapter_id", "version_number", name="uq_thesis_version_number"),
        sa.UniqueConstraint("project_id", "id", name="uq_thesis_version_project_id"),
        sa.CheckConstraint("version_number > 0", name="ck_thesis_version_number"),
        sa.CheckConstraint("status IN ('draft','under_review','approved')", name="ck_thesis_version_status"),
    )
    op.create_index("idx_thesis_versions_chapter", "thesis_section_versions", ["project_id", "chapter_id", "version_number"])
    op.create_foreign_key("fk_thesis_chapter_approved_version", "thesis_chapters", "thesis_section_versions", ["project_id", "approved_version_id"], ["project_id", "id"])
    op.create_table(
        "thesis_claims",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("section_version_id", sa.Text(), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.Text(), nullable=False, server_default="interpretation"),
        sa.Column("verification_status", sa.Text(), nullable=False, server_default="pending"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id", "section_version_id"], ["thesis_section_versions.project_id", "thesis_section_versions.id"], ondelete="CASCADE", name="fk_thesis_claim_version"),
        sa.UniqueConstraint("project_id", "id", name="uq_thesis_claim_project_id"),
        sa.CheckConstraint("claim_type IN ('own_result','literature','interpretation','limitation','recommendation')", name="ck_thesis_claim_type"),
        sa.CheckConstraint("verification_status IN ('pending','verified','partial','unsupported')", name="ck_thesis_claim_verification"),
    )
    op.create_index("idx_thesis_claims_version", "thesis_claims", ["project_id", "section_version_id"])
    op.create_table(
        "thesis_claim_sources",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("fragment_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("source_quote", sa.Text()),
        sa.Column("source_locator", sa.JSON()),
        sa.Column("verification_result", sa.Text()),
        sa.Column("verification_score", sa.Float()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id", "claim_id"], ["thesis_claims.project_id", "thesis_claims.id"], ondelete="CASCADE", name="fk_thesis_claim_source_claim"),
        sa.ForeignKeyConstraint(["project_id", "fragment_id"], ["thesis_fragments.project_id", "thesis_fragments.id"], name="fk_thesis_claim_source_fragment"),
        # documents.doc_id is the existing global primary key; project ownership
        # is checked by the service before insertion.
        sa.ForeignKeyConstraint(["document_id"], ["documents.doc_id"], name="fk_thesis_claim_source_document"),
        sa.UniqueConstraint("project_id", "claim_id", "fragment_id", name="uq_thesis_claim_source"),
        sa.CheckConstraint("verification_score IS NULL OR (verification_score >= 0 AND verification_score <= 1)", name="ck_thesis_claim_source_score"),
    )
    op.create_index("idx_thesis_claim_sources_claim", "thesis_claim_sources", ["project_id", "claim_id"])


def downgrade():
    op.drop_index("idx_thesis_claim_sources_claim", table_name="thesis_claim_sources")
    op.drop_table("thesis_claim_sources")
    op.drop_index("idx_thesis_claims_version", table_name="thesis_claims")
    op.drop_table("thesis_claims")
    op.drop_constraint("fk_thesis_chapter_approved_version", "thesis_chapters", type_="foreignkey")
    op.drop_index("idx_thesis_versions_chapter", table_name="thesis_section_versions")
    op.drop_table("thesis_section_versions")
    op.drop_index("idx_thesis_sources_chapter", table_name="thesis_section_sources")
    op.drop_table("thesis_section_sources")

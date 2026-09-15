"""Add deterministic Thesis fragment classification metadata (Phase 1B2a)."""

from alembic import op
import sqlalchemy as sa

revision = "c2d9e11a04f6"
down_revision = "b1b18d204a61"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("thesis_fragments", sa.Column("content_type", sa.Text()))
    op.add_column("thesis_fragments", sa.Column("classification_status", sa.Text(), nullable=False, server_default="pending"))
    op.add_column("thesis_fragments", sa.Column("classification_confidence", sa.Float()))
    op.add_column("thesis_fragments", sa.Column("classification_reason", sa.Text()))
    op.add_column("thesis_fragments", sa.Column("classifier_version", sa.Text()))
    op.add_column("thesis_fragments", sa.Column("classified_at", sa.DateTime(timezone=True)))
    op.create_index("idx_thesis_fragments_classification", "thesis_fragments", ["project_id", "classification_status"])
    op.create_check_constraint(
        "ck_thesis_fragment_classification_status", "thesis_fragments",
        "classification_status IN ('pending','classified','failed')",
    )
    op.create_check_constraint(
        "ck_thesis_fragment_classification_confidence", "thesis_fragments",
        "classification_confidence IS NULL OR (classification_confidence >= 0 AND classification_confidence <= 1)",
    )


def downgrade():
    op.drop_constraint("ck_thesis_fragment_classification_confidence", "thesis_fragments", type_="check")
    op.drop_constraint("ck_thesis_fragment_classification_status", "thesis_fragments", type_="check")
    op.drop_index("idx_thesis_fragments_classification", table_name="thesis_fragments")
    for name in ("classified_at", "classifier_version", "classification_reason",
                 "classification_confidence", "classification_status", "content_type"):
        op.drop_column("thesis_fragments", name)

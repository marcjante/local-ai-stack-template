"""link review articles to full text documents

Revision ID: 503c6cf26eee
Revises: d69cc3b03cd6
Create Date: 2026-09-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "503c6cf26eee"
down_revision: Union[str, Sequence[str], None] = "d69cc3b03cd6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "review_articles",
        sa.Column(
            "full_text_document_id",
            sa.Text(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_review_articles_full_text_document",
        "review_articles",
        "documents",
        ["full_text_document_id"],
        ["doc_id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "idx_review_articles_full_text_document_id",
        "review_articles",
        ["full_text_document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_review_articles_full_text_document_id",
        table_name="review_articles",
    )

    op.drop_constraint(
        "fk_review_articles_full_text_document",
        "review_articles",
        type_="foreignkey",
    )

    op.drop_column(
        "review_articles",
        "full_text_document_id",
    )

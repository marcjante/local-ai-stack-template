"""add full text retrieval status

Revision ID: d69cc3b03cd6
Revises: a7e7e2e6f782
Create Date: 2026-09-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d69cc3b03cd6"
down_revision: Union[str, Sequence[str], None] = "a7e7e2e6f782"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ALLOWED_RETRIEVAL_STATUSES = (
    "not_sought",
    "sought",
    "retrieved",
    "not_retrieved",
)


def upgrade() -> None:
    op.add_column(
        "review_articles",
        sa.Column(
            "full_text_retrieval_status",
            sa.Text(),
            nullable=False,
            server_default="not_sought",
        ),
    )

    op.create_check_constraint(
        "ck_review_articles_full_text_retrieval_status",
        "review_articles",
        "full_text_retrieval_status IN "
        "('not_sought', 'sought', 'retrieved', 'not_retrieved')",
    )

    # Backfill conservador para datos históricos.
    #
    # Si ya constaba full_text_available=True, el texto fue recuperado.
    # Si ya existe una decisión/conflicto de texto completo, necesariamente
    # el texto tuvo que estar disponible para poder evaluarlo.
    #
    # No convertimos automáticamente full_text_status='pending' en 'sought':
    # actualmente 'pending' se genera al incluir un artículo tras el cribado
    # título/resumen y no demuestra que el texto completo ya se haya buscado.
    op.execute(
        """
        UPDATE review_articles
        SET full_text_retrieval_status = 'retrieved'
        WHERE full_text_available = TRUE
           OR full_text_status IN ('include', 'exclude', 'conflict')
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_review_articles_full_text_retrieval_status",
        "review_articles",
        type_="check",
    )

    op.drop_column(
        "review_articles",
        "full_text_retrieval_status",
    )

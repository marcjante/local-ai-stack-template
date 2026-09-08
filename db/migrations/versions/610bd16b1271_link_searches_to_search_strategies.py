"""link searches to search strategies

Revision ID: 610bd16b1271
Revises: 9f4c7b2a1d8e
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "610bd16b1271"
down_revision = "9f4c7b2a1d8e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "review_searches",
        sa.Column(
            "strategy_id",
            sa.Text(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "review_searches_strategy_id_fkey",
        "review_searches",
        "review_search_strategies",
        ["strategy_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "idx_review_searches_strategy",
        "review_searches",
        ["strategy_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "idx_review_searches_strategy",
        table_name="review_searches",
    )

    op.drop_constraint(
        "review_searches_strategy_id_fkey",
        "review_searches",
        type_="foreignkey",
    )

    op.drop_column(
        "review_searches",
        "strategy_id",
    )

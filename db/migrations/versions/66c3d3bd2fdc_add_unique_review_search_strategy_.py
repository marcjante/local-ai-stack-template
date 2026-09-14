"""add unique review search strategy version

Revision ID: 66c3d3bd2fdc
Revises: bd3e1384b704
Create Date: 2026-09-14
"""

from alembic import op


revision = "66c3d3bd2fdc"
down_revision = "bd3e1384b704"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_review_search_strategies_review_database_version",
        "review_search_strategies",
        [
            "review_id",
            "database_name",
            "version",
        ],
    )


def downgrade():
    op.drop_constraint(
        "uq_review_search_strategies_review_database_version",
        "review_search_strategies",
        type_="unique",
    )

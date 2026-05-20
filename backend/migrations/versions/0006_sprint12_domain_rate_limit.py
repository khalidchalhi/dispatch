"""Add per-domain hourly rate limit column.

Revision ID: 0006_domain_rate_limit
Revises: 0005_msg_status_guard
Create Date: 2026-04-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "0006_domain_rate_limit"
down_revision: str | None = "0005_msg_status_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {column["name"] for column in inspect(bind).get_columns("domains")}
    if "rate_limit_per_hour" not in existing_columns:
        op.add_column(
            "domains",
            sa.Column(
                "rate_limit_per_hour",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("150"),
            ),
        )
    op.alter_column("domains", "rate_limit_per_hour", server_default=None)


def downgrade() -> None:
    op.drop_column("domains", "rate_limit_per_hour")

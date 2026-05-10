"""Add reset_by/reset_at fields to circuit_breaker_state.

Revision ID: 0010_cb_reset_fields
Revises: 0009_warmup_postmaster
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_cb_reset_fields"
down_revision: str | None = "0009_warmup_postmaster"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "circuit_breaker_state",
        sa.Column("reset_by", sa.Uuid(as_uuid=False), nullable=True),
    )
    op.add_column(
        "circuit_breaker_state",
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_circuit_breaker_state_reset_by_user",
        "circuit_breaker_state",
        "users",
        ["reset_by"],
        ["id"],
        ondelete=None,
    )
    op.execute(
        """
        UPDATE circuit_breaker_state
        SET reset_by = manually_reset_by
        WHERE manually_reset_by IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_circuit_breaker_state_reset_by_user",
        "circuit_breaker_state",
        type_="foreignkey",
    )
    op.drop_column("circuit_breaker_state", "reset_at")
    op.drop_column("circuit_breaker_state", "reset_by")

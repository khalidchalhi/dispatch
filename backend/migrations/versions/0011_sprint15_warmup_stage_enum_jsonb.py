"""Align warmup columns with Sprint 15 (enum stage + JSONB schedule).

Revision ID: 0011_warmup_stage_enum_jsonb
Revises: 0010_cb_reset_fields
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_warmup_stage_enum_jsonb"
down_revision: str | None = "0010_cb_reset_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


WARMUP_STAGE_ENUM_NAME = "domain_warmup_stage"
WARMUP_STAGE_VALUES = ("none", "warming", "graduated")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    stage_enum = postgresql.ENUM(*WARMUP_STAGE_VALUES, name=WARMUP_STAGE_ENUM_NAME)
    stage_enum.create(bind, checkfirst=True)

    op.execute(
        """
        ALTER TABLE domains
        ALTER COLUMN warmup_stage
        TYPE domain_warmup_stage
        USING warmup_stage::domain_warmup_stage
        """
    )
    op.execute(
        """
        ALTER TABLE domains
        ALTER COLUMN warmup_schedule
        TYPE jsonb
        USING warmup_schedule::jsonb
        """
    )
    op.alter_column(
        "domains",
        "warmup_stage",
        existing_type=stage_enum,
        nullable=False,
    )
    op.alter_column(
        "domains",
        "warmup_schedule",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        ALTER TABLE domains
        ALTER COLUMN warmup_stage
        TYPE varchar(20)
        USING warmup_stage::text
        """
    )
    op.execute(
        """
        ALTER TABLE domains
        ALTER COLUMN warmup_schedule
        TYPE json
        USING warmup_schedule::json
        """
    )
    stage_enum = postgresql.ENUM(*WARMUP_STAGE_VALUES, name=WARMUP_STAGE_ENUM_NAME)
    stage_enum.drop(bind, checkfirst=True)

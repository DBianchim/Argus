"""initial schema — servers e metrics

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "servers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("os_family", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("api_token_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_servers_hostname", "servers", ["hostname"])
    op.create_index("ix_servers_api_token_hash", "servers", ["api_token_hash"], unique=True)

    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("server_id", sa.Integer(),
                  sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pilar", sa.String(length=20), nullable=False),
        sa.Column("os_family", sa.String(length=16), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_metrics_server_id", "metrics", ["server_id"])
    op.create_index("ix_metrics_pilar", "metrics", ["pilar"])
    op.create_index(
        "ix_metrics_server_pilar_collected",
        "metrics",
        ["server_id", "pilar", "collected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_metrics_server_pilar_collected", table_name="metrics")
    op.drop_index("ix_metrics_pilar", table_name="metrics")
    op.drop_index("ix_metrics_server_id", table_name="metrics")
    op.drop_table("metrics")
    op.drop_index("ix_servers_api_token_hash", table_name="servers")
    op.drop_index("ix_servers_hostname", table_name="servers")
    op.drop_table("servers")

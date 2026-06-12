"""notification_log + estado de status nos servidores

Revision ID: 0004_notifications
Revises: 0003_users_sessions
Create Date: 2026-06-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_notifications"
down_revision: Union[str, None] = "0003_users_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("last_status", sa.String(length=20), nullable=True))
    op.add_column(
        "servers",
        sa.Column("last_status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("server_id", sa.Integer(),
                  sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("pilar", sa.String(length=20), nullable=True),
        sa.Column("item", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("status_from", sa.String(length=20), nullable=True),
        sa.Column("status_to", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_log_server_id", "notification_log", ["server_id"])
    op.create_index("ix_notification_log_created_at", "notification_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notification_log_created_at", table_name="notification_log")
    op.drop_index("ix_notification_log_server_id", table_name="notification_log")
    op.drop_table("notification_log")
    op.drop_column("servers", "last_status_changed_at")
    op.drop_column("servers", "last_status")

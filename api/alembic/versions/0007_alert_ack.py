"""alert_ack — reconhecimento de alertas (Tela de Alertas / Detalhe de Servidor)

Revision ID: 0007_alert_ack
Revises: 0006_user_roles
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_alert_ack"
down_revision: Union[str, None] = "0006_user_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_ack",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "server_id", sa.Integer(),
            sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("pilar", sa.String(length=20), nullable=False),
        sa.Column("item", sa.String(length=80), nullable=False),
        sa.Column("acked_by", sa.String(length=255), nullable=False),
        sa.Column(
            "acked_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_alert_ack_server_id", "alert_ack", ["server_id"])
    op.create_index(
        "ix_alert_ack_server_pilar_item", "alert_ack",
        ["server_id", "pilar", "item"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_alert_ack_server_pilar_item", table_name="alert_ack")
    op.drop_index("ix_alert_ack_server_id", table_name="alert_ack")
    op.drop_table("alert_ack")

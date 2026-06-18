"""config por servidor: servers.config + servers.config_version

Revision ID: 0005_server_config
Revises: 0004_notifications
Create Date: 2026-06-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0005_server_config"
down_revision: Union[str, None] = "0004_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# JSONB no Postgres, JSON no SQLite (testes) — mesmo padrão de models.py
_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    # config fica NULL até a primeira edição; a API trata NULL como default
    # (config_defaults.default_config) ao servir ao agente e ao editor.
    op.add_column("servers", sa.Column("config", _JSON, nullable=True))
    op.add_column(
        "servers",
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("servers", "config_version")
    op.drop_column("servers", "config")

"""role em users — controle de permissões (admin/operator/viewer)

Revision ID: 0006_user_roles
Revises: 0005_server_config
Create Date: 2026-07-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_user_roles"
down_revision: Union[str, None] = "0005_server_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Default 'admin': usuários existentes já tinham acesso irrestrito antes
    # deste conceito existir — não regride o acesso de ninguém na migração.
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=16), nullable=False, server_default="admin"),
    )


def downgrade() -> None:
    op.drop_column("users", "role")

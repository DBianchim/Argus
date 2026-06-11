"""agent_version + indice GIN no JSONB

Adiciona:
  - metrics.agent_version: versao do agente que gerou cada payload (NULL = agente
    antigo). Permite depurar frotas com versoes misturadas (ver CONTRATO.md).
  - Indice GIN (jsonb_path_ops) sobre metrics.metrics: consultas dentro do JSON
    (ex.: backup.status = 'SLA_BREACH') deixam de varrer a tabela inteira.
    jsonb_path_ops e a variante compacta, otimizada para operadores de
    containment (@>) — o caso tipico do dashboard.

Revision ID: 0002_agent_version_gin
Revises: 0001_initial
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_agent_version_gin"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "metrics",
        sa.Column("agent_version", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_metrics_metrics_gin",
        "metrics",
        ["metrics"],
        postgresql_using="gin",
        postgresql_ops={"metrics": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_metrics_metrics_gin", table_name="metrics")
    op.drop_column("metrics", "agent_version")

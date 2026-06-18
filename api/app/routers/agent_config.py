"""
agent_config.py — GET /api/v1/agent-config

O agente busca aqui a sua configuração (serviços críticos, caminhos de backup,
thresholds, intervalo, pilares ligados), autenticado pelo PRÓPRIO token (mesma
identidade do ingest). Devolve a config + a versão atual; o agente cacheia e só
rebaixa quando o `config_version` da resposta do ingest mudar.

Se o servidor ainda não tem config salva, devolve o default do seu os_family
(determinístico) — a versão permanece a registrada.
"""

from fastapi import APIRouter, Depends

from .. import crud
from ..auth import authenticate_agent
from ..models import Server
from ..schemas import AgentConfigOut

router = APIRouter(prefix="/api/v1", tags=["agent-config"])


@router.get("/agent-config", response_model=AgentConfigOut)
async def agent_config(server: Server = Depends(authenticate_agent)):
    return AgentConfigOut(
        config=crud.effective_config(server),
        config_version=server.config_version,
    )

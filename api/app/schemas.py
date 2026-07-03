"""
schemas.py — Modelos Pydantic (validação de entrada e saída)

IngestEnvelope reflete o contrato do agente (agents/core/sender.py): se o corpo não
casar com este schema, o FastAPI responde 422 — exatamente o código que faz o agente
descartar o payload (não retentar).
"""

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Pilar = Literal["operacional", "backup", "acesso", "logs"]
OsFamily = Literal["windows", "linux"]


# ── entrada (ingest) ──────────────────────────────────────────────────────────

class IngestEnvelope(BaseModel):
    """Envelope enviado pelos agentes em POST /api/v1/ingest."""
    timestamp: datetime.datetime
    hostname:  str = Field(min_length=1, max_length=255)
    os_family: OsFamily
    pilar:     Pilar
    # Opcional: tolera agentes antigos que ainda não enviam a versão (CONTRATO.md §1).
    agent_version: str | None = Field(default=None, max_length=20)
    metrics:   dict[str, Any]

    @field_validator("metrics")
    @classmethod
    def _metrics_not_empty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("metrics não pode ser vazio")
        return v


class IngestResponse(BaseModel):
    status:    str = "accepted"
    metric_id: int
    # Versão atual da config do servidor na central. O agente compara com a sua;
    # se diferir, rebaixa a config nova (GET /agent-config) e aplica.
    config_version: int = 1


class IngestStatsOut(BaseModel):
    """Estatísticas de desempenho da ingestão (GET /api/v1/ingest/stats)."""
    uptime_seconds:     float
    total_received:     int
    total_persisted:    int
    total_failed:       int
    per_pilar:          dict[str, int]
    throughput_per_min: int            # payloads persistidos nos últimos 60s
    sample_size:        int            # eventos na janela de latência
    persist_ms_avg:     float
    persist_ms_p50:     float
    persist_ms_p95:     float
    persist_ms_max:     float


# ── configuração do agente (gerenciada pela central) ──────────────────────────

class AgentConfigOut(BaseModel):
    """Resposta de GET /agent-config (consumida pelo agente)."""
    config:         dict[str, Any]
    config_version: int


class ServerConfigOut(BaseModel):
    """Config de um servidor para o editor do dashboard."""
    config:         dict[str, Any]
    config_version: int


class ServerConfigUpdate(BaseModel):
    """Substitui a config inteira do servidor (PUT)."""
    config: dict[str, Any]


class ServerPatch(BaseModel):
    """Edição de metadados do servidor (apelido, ativar/desativar)."""
    display_name: str | None = Field(default=None, max_length=255)
    is_active:    bool | None = None


# ── saída (consultas) ─────────────────────────────────────────────────────────

class ServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:           int
    hostname:     str
    os_family:    str
    display_name: str | None
    is_active:    bool
    created_at:   datetime.datetime
    last_seen_at: datetime.datetime | None


class MetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:            int
    server_id:     int
    pilar:         str
    os_family:     str
    collected_at:  datetime.datetime
    received_at:   datetime.datetime
    request_id:    str | None
    agent_version: str | None
    metrics:       dict[str, Any]


class MetricPage(BaseModel):
    """Página de resultados do histórico de métricas."""
    total:  int
    limit:  int
    offset: int
    items:  list[MetricOut]


class HealthOut(BaseModel):
    status:   str
    database: str


# ── autenticação de usuários ──────────────────────────────────────────────────

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=255)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username:     str
    display_name: str | None


class LoginOut(BaseModel):
    token:      str
    expires_at: datetime.datetime
    user:       UserOut


# ── overview (motor de análise) ───────────────────────────────────────────────

class AlertOut(BaseModel):
    severity:     str            # 'warn' | 'crit'
    pilar:        str
    item:         str
    title:        str
    detail:       str
    server_id:    int
    hostname:     str


class ServerOverview(BaseModel):
    id:             int
    hostname:       str
    os_family:      str
    display_name:   str | None
    status:         str          # ok | warn | crit | offline | unknown
    pilar_statuses: dict[str, str]
    last_seen_at:   datetime.datetime | None
    agent_version:  str | None


class OverviewKpis(BaseModel):
    servers_total:  int
    online:         int
    offline:        int
    crit:           int
    warn:           int
    backups_ok_pct: float | None   # None quando nenhum servidor tem dado de backup


class OverviewOut(BaseModel):
    kpis:         OverviewKpis
    servers:      list[ServerOverview]
    alerts:       list[AlertOut]
    generated_at: datetime.datetime


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:          int
    server_id:   int
    severity:    str          # warn | crit | info
    pilar:       str | None
    item:        str | None
    title:       str
    detail:      str
    status_from: str | None
    status_to:   str
    created_at:  datetime.datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]


class ServerHealthOut(BaseModel):
    """Saúde de um servidor específico (header do detalhe)."""
    id:             int
    hostname:       str
    status:         str
    pilar_statuses: dict[str, str]
    alerts:         list[AlertOut]
    last_seen_at:   datetime.datetime | None
    agent_version:  str | None

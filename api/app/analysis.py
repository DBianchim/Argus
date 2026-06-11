"""
analysis.py — Motor de análise da central

Transforma métricas brutas dos agentes em julgamento: status por pilar,
status do servidor e alertas. É a materialização do princípio
"o agente coleta, a central analisa" — nenhuma regra de análise vive
nos agentes nem no frontend.

Funções puras (recebem dicts, retornam dataclasses) — testáveis sem banco.
Conformidade com CONTRATO.md: toda leitura usa .get() e tolera chaves
ausentes; payloads de agentes antigos nunca quebram o motor.
"""

import datetime
from dataclasses import dataclass, field
from enum import Enum


# ── status ────────────────────────────────────────────────────────────────────

class Status(str, Enum):
    OK      = "ok"
    UNKNOWN = "unknown"   # pilar sem dados — pior que OK, melhor que WARN
    WARN    = "warn"
    CRIT    = "crit"
    OFFLINE = "offline"   # servidor sem contato — calculado fora dos pilares


_SEVERITY = {Status.OK: 0, Status.UNKNOWN: 1, Status.WARN: 2, Status.CRIT: 3}

PILARES = ("operacional", "backup", "acesso", "logs")


def worst(statuses: list[Status]) -> Status:
    """Retorna o pior status da lista (CRIT > WARN > UNKNOWN > OK)."""
    if not statuses:
        return Status.UNKNOWN
    return max(statuses, key=lambda s: _SEVERITY[s])


# ── alertas ───────────────────────────────────────────────────────────────────

@dataclass
class Alert:
    severity: str          # 'warn' | 'crit'
    pilar:    str
    item:     str
    title:    str
    detail:   str = ""


@dataclass
class ServerHealth:
    status:         Status
    pilar_statuses: dict[str, Status] = field(default_factory=dict)
    alerts:         list[Alert] = field(default_factory=list)


# ── limiares da central ───────────────────────────────────────────────────────
# A central define seus próprios limiares (os thresholds do config.toml dos
# agentes não viajam no payload — e a análise é responsabilidade daqui).

CPU_WARN,  CPU_CRIT  = 75.0, 90.0
MEM_WARN,  MEM_CRIT  = 80.0, 90.0
DISK_WARN, DISK_CRIT = 80.0, 90.0

_BAD_SERVICE_STATES = {"stopped", "inactive", "failed", "not_found", "not-found"}
_BACKUP_CRIT = {"NO_BACKUP_FOUND", "SLA_BREACH", "INTEGRITY_FAIL"}


def _pct_status(value, warn: float, crit: float) -> Status:
    if not isinstance(value, (int, float)):
        return Status.UNKNOWN
    if value >= crit:
        return Status.CRIT
    if value >= warn:
        return Status.WARN
    return Status.OK


# ── regras por pilar ──────────────────────────────────────────────────────────

def evaluate_operacional(metrics: dict) -> tuple[Status, list[Alert]]:
    statuses: list[Status] = [Status.OK]
    alerts: list[Alert] = []

    def alert(severity: str, item: str, title: str, detail: str = ""):
        alerts.append(Alert(severity, "operacional", item, title, detail))

    cpu = metrics.get("cpu") or {}
    if "error" in cpu:
        statuses.append(Status.WARN)
        alert("warn", "cpu", "Falha na coleta de CPU", str(cpu.get("error", "")))
    else:
        s = _pct_status(cpu.get("usage_pct"), CPU_WARN, CPU_CRIT)
        statuses.append(s if s != Status.UNKNOWN else Status.OK)
        if s in (Status.WARN, Status.CRIT):
            alert(s.value, "cpu", f"CPU em {cpu.get('usage_pct')}%",
                  f"Limite: aviso ≥{CPU_WARN:.0f}%, crítico ≥{CPU_CRIT:.0f}%")

    mem = metrics.get("memory") or {}
    if "error" in mem:
        statuses.append(Status.WARN)
        alert("warn", "memory", "Falha na coleta de memória", str(mem.get("error", "")))
    else:
        s = _pct_status(mem.get("usage_pct"), MEM_WARN, MEM_CRIT)
        statuses.append(s if s != Status.UNKNOWN else Status.OK)
        if s in (Status.WARN, Status.CRIT):
            alert(s.value, "memory", f"Memória em {mem.get('usage_pct')}%",
                  f"Limite: aviso ≥{MEM_WARN:.0f}%, crítico ≥{MEM_CRIT:.0f}%")

    for disk in metrics.get("disk") or []:
        s = _pct_status(disk.get("usage_pct"), DISK_WARN, DISK_CRIT)
        if s in (Status.WARN, Status.CRIT):
            statuses.append(s)
            alert(s.value, "disk", f"Disco {disk.get('mount', '?')} em {disk.get('usage_pct')}%",
                  f"Limite: aviso ≥{DISK_WARN:.0f}%, crítico ≥{DISK_CRIT:.0f}%")

    for svc in metrics.get("services") or []:
        if str(svc.get("status", "")).lower() in _BAD_SERVICE_STATES:
            statuses.append(Status.CRIT)
            alert("crit", "service",
                  f"Serviço crítico parado: {svc.get('name', '?')}",
                  f"Estado: {svc.get('status')}")

    return worst(statuses), alerts


def evaluate_backup(metrics: dict) -> tuple[Status, list[Alert]]:
    backup = metrics.get("backup") or {}
    status_str = backup.get("status")
    if status_str is None:
        return Status.UNKNOWN, []

    titles = {
        "NO_BACKUP_FOUND": "Nenhum backup encontrado",
        "SLA_BREACH":      "Backup fora do SLA",
        "INTEGRITY_FAIL":  "Falha de integridade no backup",
        "WARN":            "Backup possivelmente estagnado",
    }

    if status_str in _BACKUP_CRIT:
        age = backup.get("age_hours")
        sla = backup.get("sla_hours")
        detail = (f"Último backup há {age}h (SLA: {sla}h)"
                  if status_str == "SLA_BREACH" and age is not None
                  else str(backup.get("path") or ""))
        return Status.CRIT, [Alert("crit", "backup", "status",
                                   titles[status_str], detail)]
    if status_str == "WARN":
        return Status.WARN, [Alert("warn", "backup", "status", titles["WARN"],
                                   "Hash idêntico ao backup anterior")]
    return Status.OK, []


def evaluate_findings(pilar: str, metrics: dict) -> tuple[Status, list[Alert]]:
    """Pilares acesso e logs: derivado dos findings (status error/warning)."""
    statuses: list[Status] = [Status.OK]
    alerts: list[Alert] = []

    for f in metrics.get("findings") or []:
        f_status = f.get("status")
        item = str(f.get("item", "?"))

        # Limpeza manual do log de segurança (EID 1102) é incidente crítico —
        # eleva acima do tratamento padrão de finding 'error'.
        if "audit_log_cleared" in item and f_status == "error":
            statuses.append(Status.CRIT)
            alerts.append(Alert("crit", pilar, item,
                                "Log de segurança foi limpo manualmente (EID 1102)",
                                str(f.get("detail", ""))))
            continue

        if f_status == "error":
            statuses.append(Status.WARN)
            alerts.append(Alert("warn", pilar, item,
                                f"Falha no coletor: {item}",
                                str(f.get("detail", ""))))
        elif f_status == "warning":
            statuses.append(Status.WARN)
            alerts.append(Alert("warn", pilar, item,
                                str(f.get("detail") or f"Aviso em {item}")))

    return worst(statuses), alerts


def evaluate_pilar(pilar: str, metrics: dict) -> tuple[Status, list[Alert]]:
    if pilar == "operacional":
        return evaluate_operacional(metrics)
    if pilar == "backup":
        return evaluate_backup(metrics)
    if pilar in ("acesso", "logs"):
        return evaluate_findings(pilar, metrics)
    return Status.UNKNOWN, []


# ── servidor ──────────────────────────────────────────────────────────────────

def _ensure_aware(dt: datetime.datetime | None) -> datetime.datetime | None:
    """SQLite (testes) devolve datetimes naive — assume UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def is_offline(
    last_seen_at: datetime.datetime | None,
    offline_after_seconds: int,
    now: datetime.datetime | None = None,
) -> bool:
    last_seen_at = _ensure_aware(last_seen_at)
    if last_seen_at is None:
        return False   # nunca reportou → UNKNOWN, não OFFLINE
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - last_seen_at).total_seconds() > offline_after_seconds


def evaluate_server(
    pilar_metrics: dict[str, dict],
    last_seen_at: datetime.datetime | None,
    offline_after_seconds: int = 600,
    now: datetime.datetime | None = None,
) -> ServerHealth:
    """
    Avalia um servidor a partir do último payload de cada pilar.

    Args:
        pilar_metrics: {pilar: bloco metrics do último payload}. Pilares
                       ausentes recebem UNKNOWN.
        last_seen_at:  último contato do servidor (servers.last_seen_at).
        offline_after_seconds: sem contato além disso → OFFLINE.

    Returns:
        ServerHealth com status do servidor, status por pilar e alertas.
    """
    pilar_statuses: dict[str, Status] = {}
    alerts: list[Alert] = []

    for pilar in PILARES:
        if pilar in pilar_metrics:
            status, pilar_alerts = evaluate_pilar(pilar, pilar_metrics[pilar])
            pilar_statuses[pilar] = status
            alerts.extend(pilar_alerts)
        else:
            pilar_statuses[pilar] = Status.UNKNOWN

    if last_seen_at is None:
        # Registrado mas nunca enviou nada
        return ServerHealth(Status.UNKNOWN, pilar_statuses, [])

    if is_offline(last_seen_at, offline_after_seconds, now):
        last_aware = _ensure_aware(last_seen_at)
        alerts.insert(0, Alert(
            "crit", "geral", "offline",
            "Servidor sem contato",
            f"Último contato: {last_aware.isoformat()}",
        ))
        return ServerHealth(Status.OFFLINE, pilar_statuses, alerts)

    # Pilar UNKNOWN não rebaixa o servidor se houver dados de outros pilares
    com_dados = [s for s in pilar_statuses.values() if s != Status.UNKNOWN]
    status = worst(com_dados) if com_dados else Status.UNKNOWN
    return ServerHealth(status, pilar_statuses, alerts)

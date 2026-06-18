"""
agent_logs.py — Agente de Integridade e Qualidade de Logs
==========================================================
Pilar: logs
Compatível: Linux e Windows

Interface do framework:
    collect(config: AgentConfig) -> dict
    Chamada pelo scheduler em cada ciclo de monitoramento.

Uso standalone (debug):
    python agent_logs.py
    python agent_logs.py --output meu_relatorio.json
    python agent_logs.py --os linux
    python agent_logs.py -v
"""

import argparse
import datetime
import json
import logging
import platform
import time
from pathlib import Path

from core.config_loader import AgentConfig
# Utilitarios compartilhados (DRY) — re-exportados abaixo para compatibilidade
# com os imports dos testes (from agent_logs import run_cmd, now_iso, ...).
from core.sysutils import AGENT_VERSION, now_iso, detect_os, run_cmd, run_powershell
from core.sysutils import finding as _finding

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilitários internos
# ---------------------------------------------------------------------------

# Parametros vindos da config por servidor (populados por collect() a cada ciclo).
_PARAMS = {"max_log_age_hours": 24, "min_retention_rotations": 90, "min_channel_size_mb": 256}


def finding(item: str, value, status: str, detail: str = "") -> dict:
    """Achado padronizado do pilar 'logs' (wrapper de core.sysutils.finding)."""
    return _finding("logs", item, value, status, detail)


# ---------------------------------------------------------------------------
# Coleta — Linux
# ---------------------------------------------------------------------------

def _linux_syslog_service() -> list:
    results = []
    for svc in ["rsyslog", "syslog-ng"]:
        stdout, _, rc = run_cmd(["systemctl", "is-active", svc])
        active = stdout.strip() == "active"
        results.append(finding(
            f"service_{svc}", stdout.strip(),
            "ok" if active else "warning",
            f"Serviço de syslog '{svc}': {stdout.strip()}",
        ))
    return results


def _linux_journald_integrity() -> dict:
    stdout, stderr, rc = run_cmd(["journalctl", "--verify"], timeout=60)
    passed = rc == 0 and "PASS" in (stdout + stderr).upper()
    return finding(
        "journald_integrity",
        {"returncode": rc, "output": (stdout + stderr)[:500]},
        "ok" if passed else "warning",
        "Verificação de integridade HMAC do journald",
    )


def _linux_log_files() -> list:
    critical_files = [
        "/var/log/auth.log",
        "/var/log/syslog",
        "/var/log/secure",
        "/var/log/messages",
        "/var/log/audit/audit.log",
    ]
    results = []
    for lf in critical_files:
        p = Path(lf)
        if not p.exists():
            results.append(finding(
                f"log_file_{p.name}", None, "warning",
                f"Arquivo de log esperado não encontrado: {lf}",
            ))
            continue
        stat = p.stat()
        age_hours = (time.time() - stat.st_mtime) / 3600
        size_mb = stat.st_size / (1024 * 1024)
        results.append(finding(
            f"log_file_{p.name}",
            {"path": lf, "size_mb": round(size_mb, 2),
             "last_modified_hours_ago": round(age_hours, 1)},
            "warning" if age_hours > _PARAMS["max_log_age_hours"] else "ok",
            f"{lf} | {size_mb:.1f} MB | último evento há {age_hours:.1f}h",
        ))
    return results


def _linux_logrotate() -> list:
    results = []
    cfg = Path("/etc/logrotate.conf")
    if cfg.exists():
        stdout, _, _ = run_cmd(["cat", str(cfg)])
        rotate_line = next(
            (l for l in stdout.splitlines() if l.strip().startswith("rotate")), None
        )
        if rotate_line:
            try:
                days = int(rotate_line.split()[-1])
                _min = _PARAMS["min_retention_rotations"]
                results.append(finding(
                    "logrotate_retention_days", days,
                    "ok" if days >= _min else "warning",
                    f"Retenção configurada: {days} rotações (mínimo recomendado: {_min})",
                ))
            except Exception:
                pass

    d = Path("/etc/logrotate.d/")
    if d.exists():
        count = len(list(d.iterdir()))
        results.append(finding(
            "logrotate_configs_count", count, "info",
            f"{count} arquivos de configuração em /etc/logrotate.d/",
        ))
    return results


def _linux_auditd_backlog() -> list:
    stdout, _, rc = run_cmd(["auditctl", "-s"])
    if rc != 0:
        return [finding("auditd_status", None, "error",
                        "auditctl -s falhou — auditd pode estar inativo")]
    results = []
    for line in stdout.splitlines():
        if "backlog" in line.lower() and "wait" not in line.lower():
            val = line.split()[-1]
            results.append(finding(
                "auditd_backlog", val, "info",
                f"Fila de backlog do auditd: {val} eventos",
            ))
        if "lost" in line.lower():
            val = line.split()[-1]
            lost = int(val) if val.isdigit() else -1
            results.append(finding(
                "auditd_events_lost", lost,
                "warning" if lost > 0 else "ok",
                f"Eventos auditd descartados por backpressure: {lost}",
            ))
    return results


def _linux_last_log_entry() -> dict:
    for log_file in ["/var/log/auth.log", "/var/log/secure"]:
        if not Path(log_file).exists():
            continue
        stdout, _, _ = run_cmd(["tail", "-1", log_file])
        return finding(
            "last_log_entry", stdout.strip(), "info",
            f"Último registro em {log_file} — usar para detecção de gaps",
        )
    return finding("last_log_entry", None, "warning",
                   "Nenhum arquivo auth.log/secure encontrado")


# ---------------------------------------------------------------------------
# Coleta — Windows
# ---------------------------------------------------------------------------

def _windows_eventlog_service() -> dict:
    stdout, _, rc = run_powershell("(Get-Service EventLog).Status")
    running = "running" in stdout.lower()
    return finding(
        "windows_eventlog_service", stdout.strip(),
        "ok" if running else "error",
        f"Serviço Windows Event Log: {stdout.strip()}",
    )


def _windows_log_channel_sizes() -> list:
    ps = (
        "Get-WinEvent -ListLog Security,System,Application | "
        "Select-Object LogName,MaximumSizeInBytes,RecordCount,IsEnabled | "
        "ConvertTo-Json"
    )
    stdout, _, rc = run_powershell(ps)
    results = []
    if rc == 0 and stdout.strip():
        try:
            channels = json.loads(stdout)
            if not isinstance(channels, list):
                channels = [channels]
            for ch in channels:
                max_mb = (ch.get("MaximumSizeInBytes") or 0) / (1024 * 1024)
                _min = _PARAMS["min_channel_size_mb"]
                results.append(finding(
                    f"windows_channel_{ch.get('LogName', 'unknown')}_size_mb",
                    {"max_mb": round(max_mb, 1),
                     "records": ch.get("RecordCount"),
                     "enabled": ch.get("IsEnabled")},
                    "warning" if max_mb < _min else "ok",
                    f"Canal {ch.get('LogName')}: {max_mb:.0f} MB "
                    f"(mínimo recomendado: {_min} MB)",
                ))
        except Exception as exc:
            results.append(finding("windows_channel_sizes", None, "error", str(exc)))
    return results


def _windows_wec_subscriptions() -> dict:
    stdout, _, rc = run_cmd(["wecutil", "es"])
    subs = [s.strip() for s in stdout.splitlines() if s.strip()]
    return finding(
        "wec_subscriptions", subs,
        "ok" if subs else "warning",
        f"{len(subs)} subscriptions WEC ativas",
    )


def _windows_log_gaps() -> dict:
    ps = (
        "Get-WinEvent -LogName Security -MaxEvents 1 "
        "-ErrorAction SilentlyContinue | "
        "Select-Object TimeCreated | ConvertTo-Json"
    )
    stdout, _, rc = run_powershell(ps)
    ts = None
    if rc == 0 and stdout.strip():
        try:
            data = json.loads(stdout)
            if isinstance(data, list):
                data = data[0]
            ts = data.get("TimeCreated")
        except Exception:
            pass
    return finding(
        "windows_security_log_last_event", ts, "info",
        "Último evento no canal Security — usar para detecção de gaps",
    )


def _windows_audit_log_cleared() -> dict:
    """EID 1102 = log de segurança foi limpo manualmente — alto risco."""
    ps = (
        "Get-WinEvent -FilterHashtable @{LogName='Security';Id=1102} "
        "-MaxEvents 10 -ErrorAction SilentlyContinue | "
        "Select-Object TimeCreated,Message | ConvertTo-Json"
    )
    stdout, _, rc = run_powershell(ps)
    events = []
    if rc == 0 and stdout.strip():
        try:
            events = json.loads(stdout)
            if not isinstance(events, list):
                events = [events]
        except Exception:
            pass
    return finding(
        "windows_audit_log_cleared_1102", events,
        "error" if events else "ok",
        f"{len(events)} ocorrências de limpeza manual do log de segurança (EID 1102)",
    )


# ---------------------------------------------------------------------------
# Interface interna de coleta
# ---------------------------------------------------------------------------

def _collect_findings(target_os: str) -> list:
    """Executa todos os coletores do pilar logs para o OS informado."""
    collectors_linux = [
        _linux_syslog_service,
        _linux_journald_integrity,
        _linux_log_files,
        _linux_logrotate,
        _linux_auditd_backlog,
        _linux_last_log_entry,
    ]
    collectors_windows = [
        _windows_eventlog_service,
        _windows_log_channel_sizes,
        _windows_wec_subscriptions,
        _windows_log_gaps,
        _windows_audit_log_cleared,
    ]

    results = []
    fns = collectors_linux if target_os == "linux" else collectors_windows
    for fn in fns:
        try:
            data = fn()
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
            logger.debug("Coletor '%s' concluído", fn.__name__)
        except Exception as exc:
            name = getattr(fn, "__name__", repr(fn))
            results.append(finding(
                name, None, "error",
                f"Falha inesperada no coletor: {exc}",
            ))
            logger.warning("Erro no coletor '%s': %s", name, exc)
    return results


# ---------------------------------------------------------------------------
# Interface do framework
# ---------------------------------------------------------------------------

def collect(config: AgentConfig) -> dict:
    """
    Ponto de entrada chamado pelo scheduler em cada ciclo.

    Detecta o OS, coleta os achados de integridade de logs e retorna
    o payload padronizado do contrato de API.

    Args:
        config: Objeto AgentConfig carregado pelo runner.

    Returns:
        Dicionario com timestamp, hostname, os_family, pilar e metrics.
    """
    target_os = detect_os()
    timestamp = now_iso()
    start = datetime.datetime.now(datetime.timezone.utc)

    # Aplica os parametros da config por servidor (thresholds de logs)
    _PARAMS["max_log_age_hours"] = config.logs.max_log_age_hours
    _PARAMS["min_retention_rotations"] = config.logs.min_retention_rotations
    _PARAMS["min_channel_size_mb"] = config.logs.min_channel_size_mb

    findings = _collect_findings(target_os)

    summary = {"ok": 0, "warning": 0, "error": 0, "info": 0}
    for f in findings:
        key = f.get("status", "info")
        summary[key] = summary.get(key, 0) + 1

    duration = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()

    return {
        "timestamp":     timestamp,
        "hostname":      config.global_.hostname,
        "os_family":     target_os,
        "pilar":         "logs",
        "agent_version": AGENT_VERSION,
        "metrics": {
            "summary":          summary,
            "total_findings":   len(findings),
            "findings":         findings,
            "duration_seconds": round(duration, 2),
        },
    }


# ---------------------------------------------------------------------------
# Relatório standalone (uso via CLI)
# ---------------------------------------------------------------------------

def _build_standalone_report(target_os: str) -> dict:
    collected_at = now_iso()
    start = datetime.datetime.now(datetime.timezone.utc)
    logger.info("Iniciando agent_logs | OS: %s", target_os)

    findings = _collect_findings(target_os)

    summary = {"ok": 0, "warning": 0, "error": 0, "info": 0}
    for f in findings:
        summary[f.get("status", "info")] = summary.get(f.get("status", "info"), 0) + 1

    duration = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
    logger.info(
        "Concluído em %.1fs | %d achados | OK:%d WARN:%d ERR:%d",
        duration, len(findings),
        summary["ok"], summary["warning"], summary["error"],
    )

    return {
        "agent": "agent_logs",
        "version": "1.0.0",
        "pilar": "logs",
        "collected_at": collected_at,
        "duration_seconds": round(duration, 2),
        "hostname": platform.node(),
        "os_family": target_os,
        "summary": summary,
        "total_findings": len(findings),
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# CLI (modo standalone para debug)
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="agent_logs.py — coleta dados do pilar de Integridade e Qualidade de Logs"
    )
    parser.add_argument(
        "--os", dest="target_os",
        choices=["linux", "windows", "auto"], default="auto",
        help="Sistema operacional alvo (default: auto-detect)",
    )
    parser.add_argument(
        "--output", default="logs_report.json",
        help="Arquivo de saída JSON (default: logs_report.json)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    target_os = detect_os() if args.target_os == "auto" else args.target_os
    report = _build_standalone_report(target_os)

    Path(args.output).write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Relatório salvo em: %s", args.output)

    s = report["summary"]
    print("\n" + "=" * 55)
    print(f"  AGENT_LOGS — {report['collected_at']}")
    print("=" * 55)
    print(f"  Host    : {report['hostname']}")
    print(f"  OS      : {report['os_family']}")
    print(f"  Achados : {report['total_findings']}")
    print(f"  OK:{s['ok']}  WARN:{s['warning']}  ERR:{s['error']}  INFO:{s['info']}")
    print(f"  Arquivo : {args.output}")
    print("=" * 55)

    import sys
    sys.exit(1 if s["error"] > 0 else 0)


if __name__ == "__main__":
    main()

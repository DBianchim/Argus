"""
agent_acesso.py — Agente de Segurança de Acesso
================================================
Pilar: acesso
Compatível: Linux e Windows

Interface do framework:
    collect(config: AgentConfig) -> dict
    Chamada pelo scheduler em cada ciclo de monitoramento.

Uso standalone (debug):
    python agent_acesso.py
    python agent_acesso.py --output meu_relatorio.json
    python agent_acesso.py --os linux
    python agent_acesso.py -v
"""

import argparse
import datetime
import json
import logging
import platform
import re
from collections import Counter
from pathlib import Path

from core.config_loader import AgentConfig
# Utilitarios compartilhados (DRY) — re-exportados abaixo para compatibilidade
# com os imports dos testes (from agent_acesso import run_cmd, now_iso, ...).
from core.sysutils import AGENT_VERSION, now_iso, detect_os, run_cmd, run_powershell
from core.sysutils import journal_readable as _journal_readable
from core.sysutils import finding as _finding

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilitários internos
# ---------------------------------------------------------------------------

# Parametros vindos da config por servidor (populados por collect() a cada ciclo).
# Defaults preservam o comportamento historico se a config nao trouxer os campos.
_PARAMS = {"failed_login_threshold": 10, "alert_on_account_change": True}


def finding(item: str, value, status: str, detail: str = "") -> dict:
    """Achado padronizado do pilar 'acesso' (wrapper de core.sysutils.finding)."""
    return _finding("acesso", item, value, status, detail)


# ---------------------------------------------------------------------------
# Coleta — Linux
# ---------------------------------------------------------------------------

# Sistemas so com journald (ex.: Ubuntu minimo) nao tem auth.log/secure: o SSH
# registra apenas no journal. O nome da unit varia por distro (ssh x sshd).
_JOURNAL_SSH_UNITS = ["ssh", "sshd"]
_JOURNAL_WINDOW = "24 hours ago"

# Cache do journal por ciclo: falhas e sucessos de logon leem a mesma saida, e
# so um journalctl deve rodar (zerado no inicio de _collect_findings).
_journal_cache: dict = {}


def _journal_ssh_messages():
    """
    Mensagens (sem timestamp/host) do SSH nas ultimas 24h, lidas do journald.

    Returns:
        Lista de linhas; None se o journal nao esta acessivel (sem journalctl,
        sem permissao de leitura ou erro do comando). As linhas ficam no host:
        os coletores extraem apenas contagens e IPs agregados.
    """
    if "ssh" in _journal_cache:
        return _journal_cache["ssh"]
    messages = None
    if _journal_readable():
        args = ["journalctl", "--no-pager", "-o", "cat", "--since", _JOURNAL_WINDOW]
        for unit in _JOURNAL_SSH_UNITS:
            args += ["-u", unit]
        stdout, _, rc = run_cmd(args, timeout=30)
        if rc == 0:
            messages = stdout.splitlines()
    _journal_cache["ssh"] = messages
    return messages


def _top_ips(lines) -> list:
    """Top 5 IPs de origem ("from <ip>") das linhas, agregados."""
    ips = []
    for line in lines:
        parts = line.split()
        if "from" in parts:
            idx = parts.index("from")
            if idx + 1 < len(parts):
                ips.append(parts[idx + 1])
    return [{"ip": ip, "count": c} for ip, c in Counter(ips).most_common(5)]


def _journal_failed_logins(messages: list) -> list:
    # Privacidade: so contagem e IPs agregados; as linhas do journal nao saem do host.
    # "Invalid user" cobre hosts sem PasswordAuthentication, onde nao ha "Failed password".
    failed = [m for m in messages if "Failed password" in m or m.startswith("Invalid user")]
    count = len(failed)
    results = [finding(
        "failed_logins_count", count,
        "warning" if count > _PARAMS["failed_login_threshold"] else "ok",
        f"{count} tentativas de login SSH falhas (Failed password/Invalid user) "
        f"nas ultimas 24h, lidas do journald",
    )]
    top = _top_ips(failed)
    if top:
        results.append(finding(
            "top_failed_ips", top, "info",
            "Top 5 IPs com mais falhas de autenticação",
        ))
    return results


def _linux_failed_logins() -> list:
    results = []
    for log_file in ["/var/log/auth.log", "/var/log/secure"]:
        if not Path(log_file).exists():
            continue
        stdout, _, rc = run_cmd(["grep", "-c", "Failed password", log_file])
        if rc > 1:
            # grep: 2 = erro (ex.: auth.log e root:adm 640 e o agente nao esta em adm).
            # Nao vira "0 falhas": a fonte segue para o journald / aviso de indisponibilidade.
            logger.warning("Nao foi possivel ler %s (grep rc=%d)", log_file, rc)
            continue
        count = int(stdout.strip()) if rc == 0 and stdout.strip().isdigit() else 0
        results.append(finding(
            "failed_logins_count", count,
            "warning" if count > _PARAMS["failed_login_threshold"] else "ok",
            f"{count} tentativas de login com senha falhas em {log_file}",
        ))
        stdout, _, rc = run_cmd(["grep", "Failed password", log_file])
        if rc == 0 and stdout:
            results.append(finding(
                "top_failed_ips",
                _top_ips(stdout.splitlines()),
                "info",
                "Top 5 IPs com mais falhas de autenticação",
            ))
    if results:
        return results

    # Sem auth.log/secure legivel: journald. Se tambem nao ha como ler, o achado
    # explicito evita que "nada coletado" seja lido como "nenhuma falha".
    messages = _journal_ssh_messages()
    if messages is not None:
        return _journal_failed_logins(messages)
    return [finding(
        "failed_logins_unavailable", None, "warning",
        "Deteccao de falhas de logon indisponivel: nem /var/log/auth.log, "
        "/var/log/secure nem o journald (grupo systemd-journal) sao legiveis "
        "pelo agente. Reinstale/atualize o agente (ver install/INSTALL.md).",
    )]


def _linux_successful_logins() -> list:
    # Privacidade: coletamos apenas a CONTAGEM de logins bem-sucedidos, nunca
    # as linhas completas (que expoem usuario, IP de origem e metodo de auth).
    # Picos anomalos na contagem ja sao suficientes para detectar incidentes.
    results = []
    for log_file in ["/var/log/auth.log", "/var/log/secure"]:
        if not Path(log_file).exists():
            continue
        stdout, _, rc = run_cmd(["grep", "-c", "Accepted", log_file])
        if rc > 1:   # erro de leitura (ver _linux_failed_logins)
            continue
        count = int(stdout.strip()) if rc == 0 and stdout.strip().isdigit() else 0
        results.append(finding(
            "successful_ssh_logins",
            {"count": count},
            "info",
            f"{count} logins SSH bem-sucedidos em {log_file}",
        ))
    if not results:
        messages = _journal_ssh_messages()
        if messages is not None:
            count = sum(1 for m in messages if m.startswith("Accepted"))
            results.append(finding(
                "successful_ssh_logins",
                {"count": count},
                "info",
                f"{count} logins SSH bem-sucedidos nas ultimas 24h, lidos do journald",
            ))
    return results


def _linux_sudo_usage() -> list:
    # Privacidade: coletamos a contagem e os usuarios unicos, nunca os comandos
    # completos (que expoem caminhos, argumentos e dados sensiveis). Um usuario
    # novo usando sudo ou um pico de uso ja sinaliza anomalia.
    results = []
    for log_file in ["/var/log/auth.log", "/var/log/secure"]:
        if not Path(log_file).exists():
            continue
        stdout, _, _ = run_cmd(["grep", "sudo:", log_file])
        lines = [l.strip() for l in stdout.splitlines() if "COMMAND=" in l]

        # Extrai apenas o username (campo logo apos "sudo:"), sem o comando.
        unique_users = set()
        for line in lines:
            parts = line.split("sudo:")
            if len(parts) > 1:
                user_part = parts[1].strip().split()
                if user_part:
                    unique_users.add(user_part[0])

        results.append(finding(
            "sudo_commands",
            {"count": len(lines), "unique_users": sorted(unique_users)},
            "info" if lines else "ok",
            f"{len(lines)} comandos sudo por {len(unique_users)} usuario(s) unico(s)",
        ))
    return results


def _linux_ssh_config() -> list:
    cfg = "/etc/ssh/sshd_config"
    if not Path(cfg).exists():
        return [finding("sshd_config", None, "error", f"{cfg} não encontrado")]

    checks = {
        "PermitRootLogin":       ("no",  "Login root direto via SSH"),
        "PasswordAuthentication":("no",  "Autenticação por senha"),
        "PermitEmptyPasswords":  ("no",  "Senhas em branco"),
        "MaxAuthTries":          ("4",   "Máximo de tentativas"),
        "Protocol":              ("2",   "Versão do protocolo SSH"),
    }
    stdout, _, _ = run_cmd(["cat", cfg])
    config = {
        line.split()[0].lower(): line.split()[1]
        for line in stdout.splitlines()
        if line and not line.startswith("#") and len(line.split()) >= 2
    }
    results = []
    for key, (expected, desc) in checks.items():
        current = config.get(key.lower(), "não configurado")
        ok = current.lower() == expected.lower()
        results.append(finding(
            f"sshd_{key.lower()}", current,
            "ok" if ok else "warning",
            f"{desc} — esperado: '{expected}', encontrado: '{current}'",
        ))
    return results


def _linux_root_direct_logins() -> dict:
    stdout, _, _ = run_cmd(["last", "root", "-n", "20"])
    entries = [l for l in stdout.splitlines() if l.startswith("root")]
    return finding(
        "root_direct_logins", entries,
        "warning" if entries else "ok",
        f"{len(entries)} logins diretos como root encontrados",
    )


def _linux_locked_accounts() -> dict:
    stdout, _, rc = run_cmd(["awk", "-F:", '$2 ~ /^!/ {print $1}', "/etc/shadow"])
    locked = [u.strip() for u in stdout.splitlines() if u.strip()]
    return finding(
        "locked_accounts", locked, "info",
        f"{len(locked)} contas bloqueadas em /etc/shadow",
    )


def _linux_privileged_groups() -> dict:
    groups = []
    for group in ["sudo", "wheel", "admin"]:
        stdout, _, rc = run_cmd(["getent", "group", group])
        if rc == 0 and stdout.strip():
            parts = stdout.strip().split(":")
            members = [m for m in parts[-1].split(",") if m]
            groups.append({"group": group, "members": members})
    return finding(
        "privileged_groups", groups, "info",
        "Membros dos grupos privilegiados (sudo/wheel/admin)",
    )


def _linux_auditd() -> list:
    results = []
    stdout, _, rc = run_cmd(["systemctl", "is-active", "auditd"])
    active = stdout.strip() == "active"
    results.append(finding(
        "auditd_service", stdout.strip(),
        "ok" if active else "error",
        "Serviço auditd deve estar ativo",
    ))
    stdout, _, rc = run_cmd(["auditctl", "-s"])
    if rc == 0:
        for line in stdout.splitlines():
            if "lost" in line.lower():
                val = line.split()[-1]
                lost = int(val) if val.isdigit() else -1
                results.append(finding(
                    "auditd_events_lost", lost,
                    "warning" if lost > 0 else "ok",
                    f"Eventos auditd descartados por backpressure: {lost}",
                ))
    return results


# ---------------------------------------------------------------------------
# Coleta — Windows
# ---------------------------------------------------------------------------

def _parse_events(stdout: str, rc: int) -> list:
    """Converte a saida JSON do Get-WinEvent em lista, sem levantar excecao."""
    if rc != 0 or not stdout.strip():
        return []
    try:
        events = json.loads(stdout)
        return events if isinstance(events, list) else [events]
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("Falha ao parsear eventos do Windows: %s", exc)
        return []


def _windows_failed_logins() -> dict:
    # Privacidade: extraimos o IP de origem LOCALMENTE e enviamos apenas a
    # contagem + IPs agregados. O campo 'Message' bruto (usuario, workstation,
    # dominio) nunca sai do host.
    ps = (
        "Get-WinEvent -FilterHashtable @{LogName='Security';Id=4625} "
        "-MaxEvents 100 -ErrorAction SilentlyContinue | "
        "Select-Object Message | ConvertTo-Json"
    )
    stdout, _, rc = run_powershell(ps)
    events = _parse_events(stdout, rc)

    ips: list[str] = []
    for ev in events:
        msg = ev.get("Message", "") if isinstance(ev, dict) else ""
        match = re.search(r"Source Network Address:\s*(\S+)", msg)
        if match:
            ips.append(match.group(1))

    from collections import Counter
    top = [{"ip": ip, "count": c} for ip, c in Counter(ips).most_common(5)]

    count = len(events)
    return finding(
        "windows_failed_logins_4625",
        {"count": count, "top_source_ips": top},
        "warning" if count > _PARAMS["failed_login_threshold"] else "ok",
        f"{count} falhas de logon (EID 4625)",
    )


def _windows_successful_logins() -> dict:
    # Privacidade: apenas a contagem. Linhas completas de logon expoem
    # usuario, IP e tipo de logon — desnecessario para deteccao de anomalia.
    ps = (
        "Get-WinEvent -FilterHashtable @{LogName='Security';Id=4624} "
        "-MaxEvents 50 -ErrorAction SilentlyContinue | "
        "Select-Object Id | ConvertTo-Json"
    )
    stdout, _, rc = run_powershell(ps)
    count = len(_parse_events(stdout, rc))
    return finding(
        "windows_successful_logins_4624",
        {"count": count},
        "info",
        f"{count} logons bem-sucedidos (EID 4624)",
    )


def _windows_account_changes() -> dict:
    # Privacidade: contagem + quebra por tipo de evento, sem o 'Message' bruto
    # (que detalha qual conta/grupo foi alterado).
    ps = (
        "Get-WinEvent -FilterHashtable @{LogName='Security';Id=4720,4722,4732} "
        "-MaxEvents 50 -ErrorAction SilentlyContinue | "
        "Select-Object Id | ConvertTo-Json"
    )
    stdout, _, rc = run_powershell(ps)
    events = _parse_events(stdout, rc)

    by_event_id: dict[str, int] = {"4720": 0, "4722": 0, "4732": 0}
    for ev in events:
        eid = str(ev.get("Id", "")) if isinstance(ev, dict) else ""
        if eid in by_event_id:
            by_event_id[eid] += 1

    count = len(events)
    alert = _PARAMS["alert_on_account_change"] and count > 0
    return finding(
        "windows_account_changes",
        {"count": count, "by_event_id": by_event_id},
        "warning" if alert else "ok",
        f"{count} alterações de conta (EID 4720/4722/4732)",
    )


def _windows_audit_policy() -> list:
    stdout, _, rc = run_cmd(["auditpol", "/get", "/category:*"])
    if rc != 0:
        return [finding("windows_audit_policy", None, "error",
                        "Falha ao executar auditpol")]
    results = []
    for policy in ["Logon", "Account Logon", "Account Management",
                   "Privilege Use", "Process Creation"]:
        enabled = policy in stdout and "Success and Failure" in stdout
        results.append(finding(
            f"audit_policy_{policy.replace(' ', '_').lower()}",
            "enabled" if enabled else "not_configured",
            "ok" if enabled else "warning",
            f"Política '{policy}' — recomendado: Success and Failure",
        ))
    return results


# ---------------------------------------------------------------------------
# Interface interna de coleta
# ---------------------------------------------------------------------------

def _collect_findings(target_os: str) -> list:
    """Executa todos os coletores do pilar acesso para o OS informado."""
    _journal_cache.clear()
    collectors_linux = [
        _linux_failed_logins,
        _linux_successful_logins,
        _linux_sudo_usage,
        _linux_ssh_config,
        _linux_root_direct_logins,
        _linux_locked_accounts,
        _linux_privileged_groups,
        _linux_auditd,
    ]
    collectors_windows = [
        _windows_failed_logins,
        _windows_successful_logins,
        _windows_account_changes,
        _windows_audit_policy,
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

    Detecta o OS, coleta os achados de segurança de acesso e retorna
    o payload padronizado do contrato de API.

    Args:
        config: Objeto AgentConfig carregado pelo runner.

    Returns:
        Dicionario com timestamp, hostname, os_family, pilar e metrics.
    """
    target_os = detect_os()
    timestamp = now_iso()
    start = datetime.datetime.now(datetime.timezone.utc)

    # Aplica os parametros da config por servidor (thresholds de acesso)
    _PARAMS["failed_login_threshold"] = config.acesso.failed_login_threshold
    _PARAMS["alert_on_account_change"] = config.acesso.alert_on_account_change

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
        "pilar":         "acesso",
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
    logger.info("Iniciando agent_acesso | OS: %s", target_os)

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
        "agent": "agent_acesso",
        "version": "1.0.0",
        "pilar": "acesso",
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
        description="agent_acesso.py — coleta dados do pilar de Segurança de Acesso"
    )
    parser.add_argument(
        "--os", dest="target_os",
        choices=["linux", "windows", "auto"], default="auto",
        help="Sistema operacional alvo (default: auto-detect)",
    )
    parser.add_argument(
        "--output", default="access_report.json",
        help="Arquivo de saída JSON (default: access_report.json)",
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
    print(f"  AGENT_ACESSO — {report['collected_at']}")
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

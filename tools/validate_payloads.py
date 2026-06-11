#!/usr/bin/env python3
"""
validate_payloads.py — Validação estática dos payloads dos agentes Argus

Executa collect() de cada agente diretamente e verifica a estrutura,
tipos e consistência do payload retornado. Não requer rede nem servidor.

Uso:
    cd D:\\Desenvolvimento\\Argus\\agents
    python ..\\tools\\validate_payloads.py
"""

import datetime
import json
import platform
import sys
from pathlib import Path

# Garante que agents/ está no path independentemente de onde o script é executado
AGENTS_DIR = Path(__file__).parent.parent / "agents"
sys.path.insert(0, str(AGENTS_DIR))

from core.config_loader import (
    AgentConfig, GlobalConfig, ScheduleConfig, RetryConfig,
    OperacionalConfig, BackupConfig, AcessoConfig, LogsConfig,
)

# ── paleta de saída ───────────────────────────────────────────────────────────

OK   = "[OK]  "
WARN = "[AVISO]"
FAIL = "[ERRO] "
INFO = "[INFO] "

def _ts() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ── config de teste ───────────────────────────────────────────────────────────

def _make_config() -> AgentConfig:
    """
    Constrói um AgentConfig mínimo diretamente via dataclasses.
    Evita o bloqueio do token placeholder no load_config().
    """
    os_family = "windows" if platform.system() == "Windows" else "linux"

    # Serviços que provavelmente existem no ambiente de dev atual
    services_win = ["WinRM", "LanmanServer"]
    services_lin = ["sshd", "cron"]

    return AgentConfig(
        global_=GlobalConfig(
            api_url="http://localhost:8000",
            api_token="argus-dev-token-2026",
            hostname=platform.node() or "localhost",
        ),
        schedule=ScheduleConfig(interval_seconds=30),
        retry=RetryConfig(
            max_attempts=3,
            backoff_seconds=5,
            http_timeout=10,
            queue_path=str(Path.home() / "argus_test_queue"),
            queue_max_size=100,
        ),
        operacional=OperacionalConfig(
            enabled=True,
            cpu_threshold=90,
            mem_threshold=85,
            disk_threshold=90,
            critical_services_linux=services_lin,
            critical_services_windows=services_win,
        ),
        backup=BackupConfig(
            enabled=True,
            sla_hours=24,
            min_size_mb=5,
            extensions=[".tar.gz", ".zip", ".dump", ".vhd", ".vhdx"],
            paths_linux=["/mnt/backups", "/var/backups"],
            paths_windows=["E:\\Backups", "D:\\Backups"],
        ),
        acesso=AcessoConfig(enabled=True),
        logs=LogsConfig(enabled=True),
    )


# ── verificações genéricas ────────────────────────────────────────────────────

class _Result:
    def __init__(self):
        self.checks: list[tuple[str, str, str]] = []  # (status, label, detail)

    def ok(self, label: str, detail: str = "") -> None:
        self.checks.append((OK, label, detail))

    def warn(self, label: str, detail: str = "") -> None:
        self.checks.append((WARN, label, detail))

    def fail(self, label: str, detail: str = "") -> None:
        self.checks.append((FAIL, label, detail))

    def info(self, label: str, detail: str = "") -> None:
        self.checks.append((INFO, label, detail))

    @property
    def has_fail(self) -> bool:
        return any(s == FAIL for s, _, _ in self.checks)

    def print(self) -> None:
        for status, label, detail in self.checks:
            suffix = f" — {detail}" if detail else ""
            print(f"  {status} {label}{suffix}")


def _check_envelope(payload: dict, expected_pilar: str, r: _Result) -> None:
    required = ["timestamp", "hostname", "os_family", "pilar", "metrics"]
    missing = [k for k in required if k not in payload]
    if missing:
        r.fail("Campos obrigatórios", f"ausentes: {missing}")
    else:
        r.ok("Campos obrigatórios presentes")

    ts = payload.get("timestamp", "")
    try:
        datetime.datetime.fromisoformat(ts.rstrip("Z"))
        if not ts.endswith("Z"):
            r.warn("Timestamp", "não termina em 'Z'")
        else:
            r.ok("Timestamp", ts)
    except Exception:
        r.fail("Timestamp", f"formato inválido: '{ts}'")

    pilar = payload.get("pilar")
    if pilar != expected_pilar:
        r.fail("Pilar", f"esperado '{expected_pilar}', recebido '{pilar}'")
    else:
        r.ok("Pilar", pilar)

    metrics = payload.get("metrics")
    if not metrics:
        r.fail("Metrics", "vazio ou None")
    else:
        r.ok("Metrics", "presente")

    version = payload.get("agent_version")
    if version:
        r.ok("Versao do agente", version)
    else:
        r.warn("Versao do agente", "campo agent_version ausente (agente antigo?)")

    try:
        json.dumps(payload)
        r.ok("JSON-serializável")
    except (TypeError, ValueError) as e:
        r.fail("JSON-serializável", str(e))


# ── verificações por agente ───────────────────────────────────────────────────

def _validate_operacional(payload: dict, r: _Result) -> None:
    m = payload.get("metrics", {})

    # CPU
    cpu = m.get("cpu", {})
    if "error" in cpu:
        r.warn("CPU", f"erro de coleta: {cpu['error']}")
    else:
        pct = cpu.get("usage_pct")
        if pct is None:
            r.fail("CPU usage_pct", "ausente")
        elif not (0 <= pct <= 100):
            r.fail("CPU usage_pct", f"fora do range 0-100: {pct}")
        else:
            cores = cpu.get("cores", "?")
            r.ok("CPU", f"usage_pct={pct}% cores={cores}")

    # Memória
    mem = m.get("memory", {})
    if "error" in mem:
        r.warn("Memória", f"erro de coleta: {mem['error']}")
    else:
        total = mem.get("total_mb", 0)
        used = mem.get("used_mb", 0)
        pct = mem.get("usage_pct", 0)
        if total <= 0:
            r.fail("Memória", "total_mb <= 0")
        else:
            r.ok("Memória", f"total={total} MB  usado={used} MB  ({pct}%)")

    # Disco
    disk = m.get("disk", [])
    if not isinstance(disk, list):
        r.fail("Disco", "não é uma lista")
    elif not disk:
        r.warn("Disco", "lista vazia — nenhum volume encontrado")
    else:
        summary = " | ".join(
            f"{d.get('mount', '?')}: {d.get('usage_pct', '?')}%"
            for d in disk
        )
        r.ok("Disco", f"{len(disk)} volume(s) — {summary}")

    # Serviços
    svc = m.get("services", [])
    if not isinstance(svc, list):
        r.fail("Serviços", "não é uma lista")
    else:
        for s in svc:
            if "name" not in s or "status" not in s:
                r.fail("Serviços", f"entrada sem 'name'/'status': {s}")
                return
        statuses = ", ".join(f"{s['name']}={s['status']}" for s in svc)
        r.ok("Serviços", f"{len(svc)} verificado(s): {statuses}")

    # Uptime (Linux apenas)
    if payload.get("os_family") == "linux":
        uptime = m.get("uptime_seconds")
        if uptime is None:
            r.warn("Uptime", "ausente em Linux")
        elif uptime < 0:
            r.fail("Uptime", f"valor negativo: {uptime}")
        else:
            r.ok("Uptime", f"{uptime}s ({uptime // 3600}h)")


def _validate_backup(payload: dict, r: _Result) -> None:
    bk = payload.get("metrics", {}).get("backup", {})
    if not bk:
        r.fail("Backup", "metrics.backup ausente")
        return

    valid_statuses = {"NO_BACKUP_FOUND", "SLA_BREACH", "INTEGRITY_FAIL", "WARN", "OK"}
    status = bk.get("status")
    if status not in valid_statuses:
        r.fail("Backup status", f"valor inválido: '{status}'")
    elif status == "NO_BACKUP_FOUND":
        r.warn("Backup status", "NO_BACKUP_FOUND — paths de dev não existem (esperado)")
    else:
        r.ok("Backup status", status)

    # Se backup foi encontrado, verifica campos adicionais
    if status != "NO_BACKUP_FOUND":
        path = bk.get("path")
        if path is None:
            r.fail("Backup path", "None quando backup foi encontrado")
        else:
            r.ok("Backup path", path)

        age = bk.get("age_hours")
        if age is None or age < 0:
            r.fail("Backup age_hours", f"inválido: {age}")
        else:
            r.ok("Backup idade", f"{age}h | SLA={bk.get('sla_hours')}h | ok={bk.get('sla_ok')}")

        integrity = bk.get("integrity", {})
        if "integrity_check" not in integrity:
            r.fail("Integrity check", "campo ausente")
        else:
            r.ok("Integrity check", integrity["integrity_check"])

        log_info = bk.get("log", {})
        if "log_found" not in log_info:
            r.fail("Log info", "campo log_found ausente")
        else:
            r.ok("Log info", f"log_found={log_info['log_found']}")


def _validate_findings_agent(payload: dict, pilar: str, r: _Result) -> None:
    m = payload.get("metrics", {})

    total = m.get("total_findings")
    findings = m.get("findings", [])
    summary = m.get("summary", {})
    duration = m.get("duration_seconds")

    # Consistência total_findings vs len(findings)
    if total is None:
        r.fail("total_findings", "ausente")
    elif total != len(findings):
        r.fail("total_findings", f"total={total} mas len(findings)={len(findings)}")
    else:
        r.ok("total_findings", str(total))

    # Consistência summary
    expected_keys = {"ok", "warning", "error", "info"}
    if not expected_keys.issubset(summary.keys()):
        r.fail("Summary keys", f"incompleto: {summary}")
    else:
        count_from_list = {"ok": 0, "warning": 0, "error": 0, "info": 0}
        for f in findings:
            s = f.get("status", "info")
            if s in count_from_list:
                count_from_list[s] += 1
        if count_from_list != {k: summary[k] for k in count_from_list}:
            r.fail("Summary consistência",
                   f"summary={dict(summary)} mas contagem real={count_from_list}")
        else:
            ok = summary["ok"]
            warn = summary["warning"]
            err = summary["error"]
            info = summary["info"]
            r.ok("Summary", f"ok={ok} warn={warn} err={err} info={info}")

    # Estrutura de cada finding
    required_finding_fields = {"timestamp", "pilar", "item", "value", "status", "detail"}
    for i, f in enumerate(findings):
        missing = required_finding_fields - f.keys()
        if missing:
            r.fail(f"Finding[{i}]", f"campos ausentes: {missing}")
            break
        if f.get("pilar") != pilar:
            r.fail(f"Finding[{i}].pilar",
                   f"esperado '{pilar}', encontrado '{f.get('pilar')}'")
            break
    else:
        if findings:
            r.ok("Estrutura dos findings", f"{len(findings)} findings bem formados")

    # Duração
    if duration is None or duration < 0:
        r.warn("duration_seconds", f"inválido: {duration}")
    else:
        r.ok("Duração coleta", f"{duration:.2f}s")

    # Mostra findings com erro para diagnóstico
    errors = [f for f in findings if f.get("status") == "error"]
    if errors:
        r.warn(f"Findings com erro ({len(errors)})",
               " | ".join(f.get("item", "?") for f in errors[:5]))


# ── runner principal ──────────────────────────────────────────────────────────

def _run_agent(name: str, collect_fn, config: AgentConfig) -> tuple[dict | None, str]:
    try:
        payload = collect_fn(config)
        return payload, ""
    except Exception as e:
        return None, str(e)


def main() -> int:
    config = _make_config()
    os_family = "windows" if platform.system() == "Windows" else "linux"

    print()
    print("=" * 54)
    print("  ARGUS -- Validacao de Payloads")
    print(f"  Plataforma: {os_family} | {_ts()}")
    print("=" * 54)

    agents = [
        ("operacional", "agent_operacional"),
        ("backup",      "agent_backup"),
        ("acesso",      "agent_acesso"),
        ("logs",        "agent_logs"),
    ]

    total = 0
    passed = 0

    for pilar, module_name in agents:
        total += 1
        print(f"\n[{pilar}]")

        try:
            mod = __import__(module_name)
        except ImportError as e:
            print(f"  {FAIL} Import falhou: {e}")
            continue

        payload, error = _run_agent(pilar, mod.collect, config)
        r = _Result()

        if payload is None:
            r.fail("collect()", f"exceção: {error}")
            r.print()
            continue

        # Verificações comuns a todos os agentes
        _check_envelope(payload, pilar, r)

        # Verificações específicas por agente
        if pilar == "operacional":
            _validate_operacional(payload, r)
        elif pilar == "backup":
            _validate_backup(payload, r)
        elif pilar in ("acesso", "logs"):
            _validate_findings_agent(payload, pilar, r)

        r.print()

        if not r.has_fail:
            passed += 1

    print()
    print("=" * 54)
    status_line = f"RESULTADO: {passed}/{total} agentes VALIDOS"
    if passed == total:
        print(f"  {status_line}")
    else:
        print(f"  {status_line}  <- revise os [ERRO] acima")
    print("=" * 54)
    print()

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

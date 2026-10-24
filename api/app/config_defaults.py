"""
config_defaults.py — Config padrão por servidor + helpers de leitura.

A central é dona da configuração de cada servidor (serviços críticos, caminhos de
backup, thresholds, intervalo, pilares ligados). O agente baixa essa config e a
aplica; a central também a usa na análise (thresholds). Este módulo centraliza:

- `default_config(os_family)` — a config inicial de um servidor recém-registrado
  (espelha os defaults históricos que estavam fixos no agente e em analysis.py).
- helpers `op_thresholds()` para o motor de análise ler os limiares da config com
  fallback seguro (config ausente/parcial nunca quebra a análise — ver CONTRATO.md).

O blob usa LISTAS ÚNICAS (`critical_services`, `paths`): o `Server` já tem `os_family`,
então não precisa do split `_windows/_linux`. O agente mapeia para o SO dele.
"""

from typing import Any

# Limiares históricos (estavam fixos em analysis.py)
_CPU_WARN, _CPU_CRIT = 75.0, 90.0
_MEM_WARN, _MEM_CRIT = 80.0, 90.0
_DISK_WARN, _DISK_CRIT = 80.0, 90.0

_DEFAULT_SERVICES = {
    "windows": ["LanmanServer", "Dnscache", "W32Time"],
    # sshd: o agente resolve ssh/sshd conforme a distro. cron fora do padrao: nao
    # e critico em todo servidor e nao vem instalado em imagens minimas (falso positivo).
    "linux": ["sshd"],
}
_DEFAULT_BACKUP_PATHS = {
    "windows": ["D:\\Backups", "E:\\Backups"],
    "linux": ["/var/backups", "/mnt/backups"],
}
_DEFAULT_EXTENSIONS = [".tar.gz", ".zip", ".dump", ".vhd", ".vhdx"]


def default_config(os_family: str) -> dict[str, Any]:
    """Config inicial de um servidor (version 1). os_family: 'windows' | 'linux'."""
    os_key = "windows" if os_family == "windows" else "linux"
    return {
        "interval_seconds": 300,
        "operacional": {
            "enabled": True,
            "critical_services": list(_DEFAULT_SERVICES[os_key]),
            "cpu_warn": _CPU_WARN, "cpu_crit": _CPU_CRIT,
            "mem_warn": _MEM_WARN, "mem_crit": _MEM_CRIT,
            "disk_warn": _DISK_WARN, "disk_crit": _DISK_CRIT,
        },
        "backup": {
            "enabled": True,
            "paths": list(_DEFAULT_BACKUP_PATHS[os_key]),
            "sla_hours": 24,
            "min_size_mb": 5,
            "extensions": list(_DEFAULT_EXTENSIONS),
        },
        # finding_overrides: {item: "ignore"|"info"} silencia falsos positivos por
        # servidor (preenchido pela UI ao marcar um achado como ignorado).
        "acesso": {
            "enabled": True,
            "failed_login_threshold": 10,
            "alert_on_account_change": True,
            "finding_overrides": {},
        },
        "logs": {
            "enabled": True,
            "max_log_age_hours": 24,
            "min_retention_rotations": 90,
            "min_channel_size_mb": 256,
            "finding_overrides": {},
        },
    }


def op_thresholds(config: dict | None) -> dict[str, float]:
    """
    Limiares do pilar operacional, lidos da config com fallback aos defaults.
    Tolera config None/parcial.
    """
    op = (config or {}).get("operacional") or {}

    def _num(key: str, default: float) -> float:
        v = op.get(key)
        return float(v) if isinstance(v, (int, float)) else default

    return {
        "cpu_warn": _num("cpu_warn", _CPU_WARN),
        "cpu_crit": _num("cpu_crit", _CPU_CRIT),
        "mem_warn": _num("mem_warn", _MEM_WARN),
        "mem_crit": _num("mem_crit", _MEM_CRIT),
        "disk_warn": _num("disk_warn", _DISK_WARN),
        "disk_crit": _num("disk_crit", _DISK_CRIT),
    }

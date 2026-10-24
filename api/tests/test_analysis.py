"""
test_analysis.py — Regras do motor de análise (funções puras, sem banco).
"""

import datetime

from app.config_defaults import default_config
from app.analysis import (
    Status,
    evaluate_backup,
    evaluate_findings,
    evaluate_operacional,
    evaluate_server,
    is_offline,
    worst,
)

UTC = datetime.timezone.utc


# ── operacional ───────────────────────────────────────────────────────────────

def test_cpu_thresholds():
    ok, _ = evaluate_operacional({"cpu": {"usage_pct": 50.0}})
    warn, _ = evaluate_operacional({"cpu": {"usage_pct": 80.0}})
    crit, alerts = evaluate_operacional({"cpu": {"usage_pct": 95.0}})
    assert ok == Status.OK
    assert warn == Status.WARN
    assert crit == Status.CRIT
    assert any(a.item == "cpu" and a.severity == "crit" for a in alerts)


def test_memory_thresholds():
    warn, _ = evaluate_operacional({"memory": {"usage_pct": 85.0}})
    crit, _ = evaluate_operacional({"memory": {"usage_pct": 92.0}})
    assert warn == Status.WARN
    assert crit == Status.CRIT


def test_disk_thresholds():
    status, alerts = evaluate_operacional(
        {"disk": [{"mount": "C:", "usage_pct": 50.0},
                  {"mount": "D:", "usage_pct": 94.0}]}
    )
    assert status == Status.CRIT
    assert any("D:" in a.title for a in alerts)


def test_critical_service_stopped_is_crit():
    status, alerts = evaluate_operacional(
        {"services": [{"name": "nginx", "status": "stopped"}]}
    )
    assert status == Status.CRIT
    assert any("nginx" in a.title for a in alerts)


def test_collector_error_is_warn():
    status, alerts = evaluate_operacional({"cpu": {"error": "wmi_unavailable"}})
    assert status == Status.WARN


def test_missing_keys_do_not_crash():
    # Regra aditiva (CONTRATO.md): payload de agente antigo, sem várias chaves
    status, _ = evaluate_operacional({})
    assert status == Status.OK


# ── backup ────────────────────────────────────────────────────────────────────

def test_backup_crit_statuses():
    for s in ("NO_BACKUP_FOUND", "SLA_BREACH", "INTEGRITY_FAIL"):
        status, alerts = evaluate_backup({"backup": {"status": s}})
        assert status == Status.CRIT, s
        assert alerts[0].severity == "crit"


def test_backup_warn_and_ok():
    warn, _ = evaluate_backup({"backup": {"status": "WARN"}})
    ok, alerts = evaluate_backup({"backup": {"status": "OK"}})
    assert warn == Status.WARN
    assert ok == Status.OK and alerts == []


def test_backup_missing_is_unknown():
    status, _ = evaluate_backup({})
    assert status == Status.UNKNOWN


def test_backup_unknown_status_is_not_ok():
    # Status de um agente mais novo que a central: não pode virar "saudável"
    status, alerts = evaluate_backup({"backup": {"status": "PARTIAL"}})
    assert status == Status.UNKNOWN and alerts == []


def test_backup_stagnant_flag_is_warn():
    # Agente novo: status WARN + integrity.stagnant (campos aditivos)
    status, alerts = evaluate_backup({"backup": {
        "status": "WARN",
        "integrity": {"integrity_check": "WARN", "stagnant": True,
                      "sha256": "a" * 64, "previous_sha256": "a" * 64},
    }})
    assert status == Status.WARN
    assert alerts[0].severity == "warn" and "estagnado" in alerts[0].title


def test_backup_stagnant_flag_with_ok_status_still_warns():
    # Defesa em profundidade: o motor lê o detalhe, não só o status do agente
    status, _ = evaluate_backup({"backup": {
        "status": "OK", "integrity": {"integrity_check": "OK", "stagnant": True}}})
    assert status == Status.WARN


def test_backup_integrity_error_is_warn_not_ok():
    # Agente antigo mascarava ERROR como status "OK"; o novo envia WARN.
    for agent_status in ("OK", "WARN"):
        status, alerts = evaluate_backup({"backup": {
            "status": agent_status,
            "integrity": {"integrity_check": "ERROR",
                          "detail": "Sem permissao para ler o arquivo"},
        }})
        assert status == Status.WARN, agent_status
        assert alerts[0].item == "integrity"
        assert "permissao" in alerts[0].detail


def test_backup_sla_breach_wins_over_integrity_error():
    status, alerts = evaluate_backup({"backup": {
        "status": "SLA_BREACH", "age_hours": 50, "sla_hours": 26,
        "integrity": {"integrity_check": "ERROR"}}})
    assert status == Status.CRIT and "50h" in alerts[0].detail


def test_backup_old_payload_without_integrity_still_works():
    # Payload do agente anterior (sem os campos novos)
    assert evaluate_backup({"backup": {"status": "OK", "integrity": {"integrity_check": "OK",
                                                                      "sha256": "x"}}})[0] == Status.OK
    assert evaluate_backup({"backup": {"status": "WARN"}})[0] == Status.WARN


# ── acesso / logs (findings) ──────────────────────────────────────────────────

def test_findings_warning_and_error_are_warn():
    status, alerts = evaluate_findings("acesso", {"findings": [
        {"item": "x", "status": "ok"},
        {"item": "y", "status": "warning", "detail": "algo"},
        {"item": "z", "status": "error", "detail": "coletor falhou"},
    ]})
    assert status == Status.WARN
    assert len(alerts) == 2


def test_audit_log_cleared_1102_is_crit():
    status, alerts = evaluate_findings("logs", {"findings": [
        {"item": "windows_audit_log_cleared_1102", "status": "error",
         "detail": "1 ocorrência"},
    ]})
    assert status == Status.CRIT
    assert alerts[0].severity == "crit"
    assert "1102" in alerts[0].title


def test_findings_all_ok():
    status, alerts = evaluate_findings("logs", {"findings": [
        {"item": "a", "status": "ok"}, {"item": "b", "status": "info"},
    ]})
    assert status == Status.OK and alerts == []


def test_failed_logins_unavailable_is_warn_and_can_be_silenced():
    # Achado do agente Linux sem auth.log/journal legivel: vira Aviso (nao some)
    finding = {"item": "failed_logins_unavailable", "status": "warning",
               "value": None, "detail": "Deteccao de falhas de logon indisponivel"}
    status, alerts = evaluate_findings("acesso", {"findings": [finding]})
    assert status == Status.WARN
    assert alerts[0].item == "failed_logins_unavailable"
    assert "indisponivel" in alerts[0].title

    overrides = {"acesso": {"finding_overrides": {"failed_logins_unavailable": "ignore"}}}
    status, alerts = evaluate_findings("acesso", {"findings": [finding]}, overrides)
    assert status == Status.OK and alerts == []


def test_service_unit_key_is_ignored_by_analysis():
    # Chave aditiva 'unit' (ssh x sshd) nao muda a avaliacao do servico
    status, alerts = evaluate_operacional({"services": [
        {"name": "sshd", "status": "active", "enabled": "enabled", "unit": "ssh"},
    ]})
    assert status == Status.OK and alerts == []


def test_linux_default_services_do_not_include_cron():
    # cron nao vem em imagens minimas (Ubuntu 26.04): inactive = falso positivo permanente
    services = default_config("linux")["operacional"]["critical_services"]
    assert services == ["sshd"]


# ── servidor ──────────────────────────────────────────────────────────────────

def _now():
    return datetime.datetime.now(UTC)


def test_server_worst_pilar_wins():
    health = evaluate_server(
        {"operacional": {"cpu": {"usage_pct": 10.0}},
         "backup": {"backup": {"status": "SLA_BREACH"}}},
        last_seen_at=_now(),
    )
    assert health.status == Status.CRIT
    assert health.pilar_statuses["backup"] == Status.CRIT
    assert health.pilar_statuses["operacional"] == Status.OK
    assert health.pilar_statuses["acesso"] == Status.UNKNOWN


def test_server_disabled_pilar_ignores_stale_crit_payload():
    # Servidor sem backup a monitorar: admin desliga o pilar na config, mas o
    # último payload salvo (de antes de desligar) ainda era NO_BACKUP_FOUND.
    # O pilar desligado deve virar "unknown" e não derrubar o servidor pra CRIT.
    health = evaluate_server(
        {"operacional": {"cpu": {"usage_pct": 10.0}},
         "backup": {"backup": {"status": "NO_BACKUP_FOUND", "path": None}}},
        last_seen_at=_now(),
        config={"backup": {"enabled": False}},
    )
    assert health.pilar_statuses["backup"] == Status.UNKNOWN
    assert health.status == Status.OK
    assert not any(a.pilar == "backup" for a in health.alerts)


def test_server_offline_precedence():
    old = _now() - datetime.timedelta(hours=2)
    health = evaluate_server(
        {"operacional": {"cpu": {"usage_pct": 10.0}}},
        last_seen_at=old, offline_after_seconds=600,
    )
    assert health.status == Status.OFFLINE
    assert health.alerts[0].item == "offline"


def test_server_never_seen_is_unknown():
    health = evaluate_server({}, last_seen_at=None)
    assert health.status == Status.UNKNOWN
    assert health.alerts == []


def test_is_offline_handles_naive_datetime():
    # SQLite (testes) devolve datetimes naive — tratados como UTC
    naive_old = datetime.datetime.now(UTC).replace(tzinfo=None) - datetime.timedelta(hours=1)
    assert is_offline(naive_old, offline_after_seconds=600) is True


def test_worst_ordering():
    assert worst([Status.OK, Status.WARN]) == Status.WARN
    assert worst([Status.WARN, Status.CRIT]) == Status.CRIT
    assert worst([Status.OK, Status.UNKNOWN]) == Status.UNKNOWN
    assert worst([]) == Status.UNKNOWN

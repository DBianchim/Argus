"""
test_analysis.py — Regras do motor de análise (funções puras, sem banco).
"""

import datetime

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

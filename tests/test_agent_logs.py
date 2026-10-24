"""
test_agent_logs.py — Testes do agente de Integridade de Logs
=============================================================
Execute com:
    python test_agent_logs.py -v
    python test_agent_logs.py TestLinuxLogs -v
    python test_agent_logs.py TestWindowsLogs -v
"""

import json
import platform
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Aponta para agents/ — um nivel acima de tests/
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from agent_logs import (
    _build_standalone_report,
    _collect_findings,
    detect_os,
    finding,
    now_iso,
    run_cmd,
    _linux_auditd_backlog,
    _linux_journald_integrity,
    _linux_last_log_entry,
    _linux_log_files,
    _linux_logrotate,
    _linux_syslog_service,
    _windows_audit_log_cleared,
    _windows_eventlog_service,
    _windows_log_channel_sizes,
    _windows_log_gaps,
    _windows_wec_subscriptions,
)


def _save_report(report: dict, path: str) -> None:
    """Helper de persistência para uso nos testes."""
    Path(path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


# ===========================================================================
# PASSO 1 — Utilitários
# ===========================================================================

class TestUtilities(unittest.TestCase):
    """PASSO 1: Funções utilitárias do agent_logs."""

    def test_detect_os_valid(self):
        self.assertIn(detect_os(), ("linux", "windows"))

    def test_detect_os_matches_platform(self):
        expected = "windows" if platform.system().lower() == "windows" else "linux"
        self.assertEqual(detect_os(), expected)

    def test_now_iso_format(self):
        ts = now_iso()
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)

    def test_finding_pilar_is_logs(self):
        f = finding("item_x", 42, "ok", "detalhe")
        self.assertEqual(f["pilar"], "logs")

    def test_finding_all_fields(self):
        f = finding("item_x", 42, "ok", "detalhe")
        self.assertEqual(f["item"], "item_x")
        self.assertEqual(f["value"], 42)
        self.assertEqual(f["status"], "ok")
        self.assertEqual(f["detail"], "detalhe")
        self.assertIn("timestamp", f)

    def test_finding_none_value(self):
        self.assertIsNone(finding("i", None, "warning")["value"])

    def test_run_cmd_success(self):
        # Usa o proprio interpretador Python como cobaia cross-platform.
        # 'echo'/'sleep' nao sao executaveis standalone no Windows (alvo primario).
        stdout, _, rc = run_cmd([sys.executable, "-c", "print('ok')"])
        self.assertEqual(rc, 0)
        self.assertIn("ok", stdout)

    def test_run_cmd_not_found(self):
        _, stderr, rc = run_cmd(["nao_existe_xyz"])
        self.assertEqual(rc, 1)
        self.assertNotEqual(stderr, "")

    def test_run_cmd_timeout(self):
        _, stderr, rc = run_cmd(
            [sys.executable, "-c", "import time; time.sleep(10)"], timeout=1
        )
        self.assertEqual(rc, 1)
        self.assertIn("imeout", stderr)


# ===========================================================================
# PASSO 2 — Estrutura do relatório
# ===========================================================================

class TestReportStructure(unittest.TestCase):
    """PASSO 2: Relatório deve ter campos corretos."""

    def _mock_report(self):
        with patch("agent_logs._collect_findings", return_value=[]):
            return _build_standalone_report("linux")

    def test_required_keys(self):
        report = self._mock_report()
        for key in ["agent", "version", "pilar", "collected_at",
                    "duration_seconds", "hostname", "os_family",
                    "summary", "total_findings", "findings"]:
            with self.subTest(key=key):
                self.assertIn(key, report)

    def test_pilar_is_logs(self):
        self.assertEqual(self._mock_report()["pilar"], "logs")

    def test_agent_name(self):
        self.assertEqual(self._mock_report()["agent"], "agent_logs")

    def test_summary_keys(self):
        for k in ("ok", "warning", "error", "info"):
            self.assertIn(k, self._mock_report()["summary"])

    def test_total_findings_matches_list(self):
        mock_f = [finding("a", 1, "ok"), finding("b", 2, "warning")]
        with patch("agent_logs._collect_findings", return_value=mock_f):
            report = _build_standalone_report("linux")
        self.assertEqual(report["total_findings"], len(report["findings"]))

    def test_summary_counts(self):
        mock_f = [
            finding("i1", 1, "ok"),
            finding("i2", 2, "ok"),
            finding("i3", 3, "warning"),
            finding("i4", 4, "error"),
        ]
        with patch("agent_logs._collect_findings", return_value=mock_f):
            report = _build_standalone_report("linux")
        self.assertEqual(report["summary"]["ok"], 2)
        self.assertEqual(report["summary"]["warning"], 1)
        self.assertEqual(report["summary"]["error"], 1)

    def test_json_serializable(self):
        report = self._mock_report()
        try:
            json.dumps(report)
        except (TypeError, ValueError) as e:
            self.fail(f"Não serializável: {e}")

    def test_duration_non_negative(self):
        self.assertGreaterEqual(self._mock_report()["duration_seconds"], 0)


# ===========================================================================
# PASSO 3 — Coletores Linux
# ===========================================================================

class TestLinuxLogs(unittest.TestCase):
    """PASSO 3: Coletores Linux do agent_logs."""

    def test_rsyslog_active_ok(self):
        with patch("agent_logs.run_cmd", return_value=("active\n", "", 0)):
            results = _linux_syslog_service()
        rsyslog = next((r for r in results if "rsyslog" in r["item"]), None)
        self.assertIsNotNone(rsyslog)
        self.assertEqual(rsyslog["status"], "ok")

    def test_rsyslog_inactive_warning(self):
        with patch("agent_logs.run_cmd", return_value=("inactive\n", "", 0)):
            results = _linux_syslog_service()
        rsyslog = next((r for r in results if "rsyslog" in r["item"]), None)
        self.assertIsNotNone(rsyslog)
        self.assertEqual(rsyslog["status"], "warning")

    def test_journald_pass_ok(self):
        with patch("agent_logs.run_cmd", return_value=("PASS\n", "", 0)):
            result = _linux_journald_integrity()
        self.assertEqual(result["status"], "ok")

    def test_journald_fail_warning(self):
        with patch("agent_logs.run_cmd", return_value=("", "checksum mismatch", 1)):
            result = _linux_journald_integrity()
        self.assertEqual(result["status"], "warning")

    def test_log_file_missing_warning(self):
        with patch("pathlib.Path.exists", return_value=False):
            results = _linux_log_files()
        warnings = [r for r in results if r["status"] == "warning"]
        self.assertGreater(len(warnings), 0)

    def test_log_file_missing_com_journald_ativo_nao_gera_warning(self):
        # Sistema so com journald: auth.log/syslog/secure/messages ausentes sao normais
        with patch("pathlib.Path.exists", return_value=False):
            with patch("agent_logs.journald_active", return_value=True):
                results = _linux_log_files()
        by_item = {r["item"]: r for r in results}
        for name in ("auth.log", "syslog", "secure", "messages"):
            self.assertEqual(by_item[f"log_file_{name}"]["status"], "info", name)
            self.assertIn("journald", by_item[f"log_file_{name}"]["detail"])
        # audit.log nao e substituido pelo journald: continua avisando
        self.assertEqual(by_item["log_file_audit.log"]["status"], "warning")

    def test_log_file_missing_sem_journald_continua_warning(self):
        with patch("pathlib.Path.exists", return_value=False):
            with patch("agent_logs.journald_active", return_value=False):
                results = _linux_log_files()
        self.assertTrue(all(r["status"] == "warning" for r in results))

    def test_log_file_recent_ok(self):
        mock_stat = MagicMock()
        mock_stat.st_mtime = time.time() - 1800   # 30 min atrás
        mock_stat.st_size = 204800
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.stat", return_value=mock_stat):
                results = _linux_log_files()
        ok_items = [r for r in results if r["status"] == "ok"]
        self.assertGreater(len(ok_items), 0)

    def test_log_file_stale_warning(self):
        mock_stat = MagicMock()
        mock_stat.st_mtime = time.time() - (26 * 3600)  # 26h atrás
        mock_stat.st_size = 1024
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.stat", return_value=mock_stat):
                results = _linux_log_files()
        warnings = [r for r in results if r["status"] == "warning"]
        self.assertGreater(len(warnings), 0)

    @unittest.skipUnless(
        platform.system() != "Windows",
        "logrotate (/etc/logrotate.d) e especifico do Linux — coletor nao roda no Windows",
    )
    def test_logrotate_retention_ok_above_90(self):
        fake_conf = "# comment\nrotate 90\nweekly\n"
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.is_dir", return_value=False):
                with patch("agent_logs.run_cmd", return_value=(fake_conf, "", 0)):
                    results = _linux_logrotate()
        ret = next((r for r in results if r["item"] == "logrotate_retention_days"), None)
        if ret:
            self.assertEqual(ret["status"], "ok")
            self.assertEqual(ret["value"], 90)

    @unittest.skipUnless(
        platform.system() != "Windows",
        "logrotate (/etc/logrotate.d) e especifico do Linux — coletor nao roda no Windows",
    )
    def test_logrotate_retention_warning_below_90(self):
        fake_conf = "rotate 7\nweekly\n"
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.is_dir", return_value=False):
                with patch("agent_logs.run_cmd", return_value=(fake_conf, "", 0)):
                    results = _linux_logrotate()
        ret = next((r for r in results if r["item"] == "logrotate_retention_days"), None)
        if ret:
            self.assertEqual(ret["status"], "warning")

    def test_auditd_backlog_lost_zero_ok(self):
        with patch("agent_logs.run_cmd", return_value=("backlog 0\nlost 0\n", "", 0)):
            results = _linux_auditd_backlog()
        lost = next((r for r in results if r["item"] == "auditd_events_lost"), None)
        if lost:
            self.assertEqual(lost["status"], "ok")
            self.assertEqual(lost["value"], 0)

    def test_auditd_backlog_lost_nonzero_warning(self):
        with patch("agent_logs.run_cmd", return_value=("backlog 5\nlost 33\n", "", 0)):
            results = _linux_auditd_backlog()
        lost = next((r for r in results if r["item"] == "auditd_events_lost"), None)
        self.assertIsNotNone(lost)
        self.assertEqual(lost["status"], "warning")
        self.assertEqual(lost["value"], 33)

    def test_auditd_unreachable_error(self):
        with patch("agent_logs.run_cmd", return_value=("", "permission denied", 1)):
            results = _linux_auditd_backlog()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "error")

    def test_last_log_entry_found(self):
        fake = "Apr 13 12:00:01 sshd session opened for ubuntu\n"
        with patch("pathlib.Path.exists", return_value=True):
            with patch("agent_logs.run_cmd", return_value=(fake, "", 0)):
                result = _linux_last_log_entry()
        self.assertEqual(result["status"], "info")
        self.assertIn("ubuntu", result["value"])

    def test_last_log_entry_no_file(self):
        with patch("pathlib.Path.exists", return_value=False):
            with patch("agent_logs.journald_active", return_value=False):
                result = _linux_last_log_entry()
        self.assertEqual(result["status"], "warning")

    def test_last_log_entry_journald_envia_so_o_timestamp(self):
        fake = "2026-10-24T14:23:30+0000 srv sshd[1]: Accepted publickey for david"
        with patch("pathlib.Path.exists", return_value=False):
            with patch("agent_logs.journald_active", return_value=True):
                with patch("agent_logs.journal_readable", return_value=True):
                    with patch("agent_logs.run_cmd", return_value=(fake, "", 0)):
                        result = _linux_last_log_entry()
        self.assertEqual(result["status"], "info")
        self.assertEqual(result["value"], "2026-10-24T14:23:30+0000")
        self.assertNotIn("david", str(result))

    def test_last_log_entry_journald_ilegivel_warning(self):
        with patch("pathlib.Path.exists", return_value=False):
            with patch("agent_logs.journald_active", return_value=True):
                with patch("agent_logs.journal_readable", return_value=False):
                    result = _linux_last_log_entry()
        self.assertEqual(result["status"], "warning")


# ===========================================================================
# PASSO 4 — Coletores Windows
# ===========================================================================

class TestWindowsLogs(unittest.TestCase):
    """PASSO 4: Coletores Windows do agent_logs."""

    def test_eventlog_service_running_ok(self):
        with patch("agent_logs.run_powershell", return_value=("Running\n", "", 0)):
            result = _windows_eventlog_service()
        self.assertEqual(result["status"], "ok")

    def test_eventlog_service_stopped_error(self):
        with patch("agent_logs.run_powershell", return_value=("Stopped\n", "", 0)):
            result = _windows_eventlog_service()
        self.assertEqual(result["status"], "error")

    def test_log_channel_sizes_ok_above_256(self):
        channels = [{"LogName": "Security", "MaximumSizeInBytes": 512 * 1024 * 1024,
                     "RecordCount": 1000, "IsEnabled": True}]
        with patch("agent_logs.run_powershell",
                   return_value=(json.dumps(channels), "", 0)):
            results = _windows_log_channel_sizes()
        sec = next((r for r in results if "Security" in r["item"]), None)
        self.assertIsNotNone(sec)
        self.assertEqual(sec["status"], "ok")

    def test_log_channel_sizes_warning_below_256(self):
        channels = [{"LogName": "Security", "MaximumSizeInBytes": 20 * 1024 * 1024,
                     "RecordCount": 500, "IsEnabled": True}]
        with patch("agent_logs.run_powershell",
                   return_value=(json.dumps(channels), "", 0)):
            results = _windows_log_channel_sizes()
        sec = next((r for r in results if "Security" in r["item"]), None)
        self.assertIsNotNone(sec)
        self.assertEqual(sec["status"], "warning")

    def test_wec_subscriptions_ok_when_found(self):
        with patch("agent_logs.run_cmd",
                   return_value=("sub1\nsub2\n", "", 0)):
            result = _windows_wec_subscriptions()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["value"]), 2)

    def test_wec_subscriptions_warning_when_empty(self):
        with patch("agent_logs.run_cmd", return_value=("", "", 0)):
            result = _windows_wec_subscriptions()
        self.assertEqual(result["status"], "warning")

    def test_audit_log_cleared_error_when_found(self):
        events = [{"TimeCreated": "t", "Message": "Log cleared"}]
        with patch("agent_logs.run_powershell",
                   return_value=(json.dumps(events), "", 0)):
            result = _windows_audit_log_cleared()
        self.assertEqual(result["status"], "error")

    def test_audit_log_cleared_ok_when_none(self):
        with patch("agent_logs.run_powershell", return_value=("", "", 0)):
            result = _windows_audit_log_cleared()
        self.assertEqual(result["status"], "ok")

    def test_log_gaps_returns_info(self):
        data = {"TimeCreated": "2026-04-13T12:00:00"}
        with patch("agent_logs.run_powershell",
                   return_value=(json.dumps(data), "", 0)):
            result = _windows_log_gaps()
        self.assertEqual(result["status"], "info")


# ===========================================================================
# PASSO 5 — Isolamento e resiliência
# ===========================================================================

class TestIsolationAndResiliency(unittest.TestCase):
    """PASSO 5: agent_logs é independente e tolerante a falhas."""

    def test_collect_linux_does_not_call_windows_fns(self):
        """Coleta Linux não deve chamar funções Windows."""
        with patch("agent_logs._windows_eventlog_service") as mock_w:
            with patch("agent_logs._linux_syslog_service", return_value=[]):
                with patch("agent_logs._linux_journald_integrity",
                           return_value=finding("x", None, "ok")):
                    with patch("agent_logs._linux_log_files", return_value=[]):
                        with patch("agent_logs._linux_logrotate", return_value=[]):
                            with patch("agent_logs._linux_auditd_backlog", return_value=[]):
                                with patch("agent_logs._linux_last_log_entry",
                                           return_value=finding("x", None, "ok")):
                                    _collect_findings("linux")
        mock_w.assert_not_called()

    def test_collect_windows_does_not_call_linux_fns(self):
        """Coleta Windows não deve chamar funções Linux."""
        with patch("agent_logs._linux_syslog_service") as mock_l:
            with patch("agent_logs._windows_eventlog_service",
                       return_value=finding("x", None, "ok")):
                with patch("agent_logs._windows_log_channel_sizes", return_value=[]):
                    with patch("agent_logs._windows_wec_subscriptions",
                               return_value=finding("x", None, "ok")):
                        with patch("agent_logs._windows_log_gaps",
                                   return_value=finding("x", None, "ok")):
                            with patch("agent_logs._windows_audit_log_cleared",
                                       return_value=finding("x", None, "ok")):
                                _collect_findings("windows")
        mock_l.assert_not_called()

    def test_one_collector_exception_does_not_crash(self):
        """Exceção em um coletor não derruba os demais."""
        def boom():
            raise RuntimeError("falha simulada")

        with patch("agent_logs._linux_syslog_service", side_effect=boom):
            with patch("agent_logs._linux_journald_integrity",
                       return_value=finding("x", None, "ok")):
                with patch("agent_logs._linux_log_files", return_value=[]):
                    with patch("agent_logs._linux_logrotate", return_value=[]):
                        with patch("agent_logs._linux_auditd_backlog", return_value=[]):
                            with patch("agent_logs._linux_last_log_entry",
                                       return_value=finding("x", None, "ok")):
                                results = _collect_findings("linux")
        errors = [r for r in results if r["status"] == "error"]
        self.assertGreater(len(errors), 0)

    def test_empty_collect_is_valid_report(self):
        with patch("agent_logs._collect_findings", return_value=[]):
            report = _build_standalone_report("linux")
        self.assertEqual(report["total_findings"], 0)
        self.assertIsInstance(report["findings"], list)

    def test_run_cmd_never_raises(self):
        try:
            run_cmd(["nao_existe_xyz_abc"])
        except Exception as e:
            self.fail(f"run_cmd levantou exceção: {e}")

    def test_agents_are_fully_independent(self):
        """agent_logs não importa (direta ou transitivamente) agent_acesso.

        Roda num interpretador limpo via subprocess: checar sys.modules no
        processo atual seria falho porque o test runner (discover) ja pode ter
        carregado agent_acesso de outro modulo de teste.
        """
        import subprocess
        agents_dir = str(Path(__file__).parent.parent / "agents")
        code = (
            "import sys; sys.path.insert(0, r'{0}'); "
            "import agent_logs; "
            "sys.exit(1 if 'agent_acesso' in sys.modules else 0)"
        ).format(agents_dir)
        result = subprocess.run([sys.executable, "-c", code], capture_output=True)
        self.assertEqual(
            result.returncode, 0,
            "agent_logs carregou agent_acesso (direta ou transitivamente)",
        )


# ===========================================================================
# PASSO 6 — Persistência
# ===========================================================================

class TestPersistence(unittest.TestCase):
    """PASSO 6: Salvamento do relatório em disco."""

    def _make_report(self):
        with patch("agent_logs._collect_findings", return_value=[]):
            return _build_standalone_report("linux")

    def test_save_creates_file(self):
        report = self._make_report()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        _save_report(report, path)
        self.assertTrue(Path(path).exists())

    def test_saved_file_is_valid_json(self):
        report = self._make_report()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        _save_report(report, path)
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(loaded["pilar"], "logs")
        self.assertEqual(loaded["agent"], "agent_logs")

    def test_findings_preserved_in_file(self):
        mock_f = [finding("item_test", "val", "ok", "detalhe")]
        with patch("agent_logs._collect_findings", return_value=mock_f):
            report = _build_standalone_report("linux")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        _save_report(report, path)
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(loaded["total_findings"], 1)
        self.assertEqual(loaded["findings"][0]["item"], "item_test")


if __name__ == "__main__":
    unittest.main(verbosity=2)

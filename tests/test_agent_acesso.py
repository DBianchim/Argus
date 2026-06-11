"""
test_agent_acesso.py — Testes do agente de Segurança de Acesso
==============================================================
Execute com:
    python test_agent_acesso.py -v
    python test_agent_acesso.py TestLinuxAccess -v
    python test_agent_acesso.py TestWindowsAccess -v
"""

import json
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Aponta para agents/ — um nivel acima de tests/
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from agent_acesso import (
    _build_standalone_report,
    _collect_findings,
    detect_os,
    finding,
    now_iso,
    run_cmd,
    _linux_auditd,
    _linux_failed_logins,
    _linux_locked_accounts,
    _linux_privileged_groups,
    _linux_root_direct_logins,
    _linux_ssh_config,
    _linux_successful_logins,
    _linux_sudo_usage,
    _windows_account_changes,
    _windows_audit_policy,
    _windows_failed_logins,
    _windows_successful_logins,
)


def _save_report(report: dict, path: str) -> None:
    """Helper de persistência para uso nos testes."""
    Path(path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


# ===========================================================================
# PASSO 1 — Utilitários
# ===========================================================================

class TestUtilities(unittest.TestCase):
    """PASSO 1: Funções utilitárias do agent_acesso."""

    def test_detect_os_valid(self):
        self.assertIn(detect_os(), ("linux", "windows"))

    def test_detect_os_matches_platform(self):
        expected = "windows" if platform.system().lower() == "windows" else "linux"
        self.assertEqual(detect_os(), expected)

    def test_now_iso_format(self):
        ts = now_iso()
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)

    def test_finding_fields(self):
        f = finding("item_x", 42, "ok", "detalhe")
        self.assertEqual(f["pilar"], "acesso")
        self.assertEqual(f["item"], "item_x")
        self.assertEqual(f["value"], 42)
        self.assertEqual(f["status"], "ok")
        self.assertEqual(f["detail"], "detalhe")
        self.assertIn("timestamp", f)

    def test_finding_none_value(self):
        self.assertIsNone(finding("i", None, "warning")["value"])

    def test_finding_list_value(self):
        self.assertEqual(finding("i", [1, 2], "info")["value"], [1, 2])

    def test_run_cmd_success(self):
        # Usa o proprio interpretador Python como cobaia cross-platform.
        # 'echo'/'sleep' nao sao executaveis standalone no Windows (alvo primario).
        stdout, stderr, rc = run_cmd([sys.executable, "-c", "print('ok')"])
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
        with patch("agent_acesso._collect_findings", return_value=[]):
            return _build_standalone_report("linux")

    def test_required_keys(self):
        report = self._mock_report()
        for key in ["agent", "version", "pilar", "collected_at",
                    "duration_seconds", "hostname", "os_family",
                    "summary", "total_findings", "findings"]:
            with self.subTest(key=key):
                self.assertIn(key, report)

    def test_pilar_is_acesso(self):
        self.assertEqual(self._mock_report()["pilar"], "acesso")

    def test_agent_name(self):
        self.assertEqual(self._mock_report()["agent"], "agent_acesso")

    def test_summary_keys(self):
        report = self._mock_report()
        for k in ("ok", "warning", "error", "info"):
            self.assertIn(k, report["summary"])

    def test_total_findings_matches_list(self):
        mock_f = [finding("a", 1, "ok"), finding("b", 2, "warning")]
        with patch("agent_acesso._collect_findings", return_value=mock_f):
            report = _build_standalone_report("linux")
        self.assertEqual(report["total_findings"], len(report["findings"]))

    def test_summary_counts(self):
        mock_f = [
            finding("i1", 1, "ok"),
            finding("i2", 2, "ok"),
            finding("i3", 3, "warning"),
            finding("i4", 4, "error"),
        ]
        with patch("agent_acesso._collect_findings", return_value=mock_f):
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

class TestLinuxAccess(unittest.TestCase):
    """PASSO 3: Coletores Linux do agent_acesso."""

    def test_failed_logins_warning_above_10(self):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("agent_acesso.run_cmd") as mock:
                mock.side_effect = [
                    ("15\n", "", 0), ("", "", 1),
                    ("15\n", "", 0), ("", "", 1),
                ]
                results = _linux_failed_logins()
        counts = [r for r in results if r["item"] == "failed_logins_count"]
        self.assertTrue(len(counts) > 0)
        self.assertEqual(counts[0]["value"], 15)
        self.assertEqual(counts[0]["status"], "warning")

    def test_failed_logins_ok_below_10(self):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("agent_acesso.run_cmd") as mock:
                mock.side_effect = [
                    ("3\n", "", 0), ("", "", 1),
                    ("3\n", "", 0), ("", "", 1),
                ]
                results = _linux_failed_logins()
        counts = [r for r in results if r["item"] == "failed_logins_count"]
        if counts:
            self.assertEqual(counts[0]["status"], "ok")

    def test_failed_logins_no_file(self):
        with patch("pathlib.Path.exists", return_value=False):
            self.assertEqual(_linux_failed_logins(), [])

    def test_sshd_root_login_yes_warning(self):
        fake = "PermitRootLogin yes\nPasswordAuthentication no\n"
        with patch("pathlib.Path.exists", return_value=True):
            with patch("agent_acesso.run_cmd", return_value=(fake, "", 0)):
                results = _linux_ssh_config()
        root = next((r for r in results if "permitrootlogin" in r["item"]), None)
        self.assertIsNotNone(root)
        self.assertEqual(root["status"], "warning")

    def test_sshd_root_login_no_ok(self):
        fake = "PermitRootLogin no\nPasswordAuthentication no\n"
        with patch("pathlib.Path.exists", return_value=True):
            with patch("agent_acesso.run_cmd", return_value=(fake, "", 0)):
                results = _linux_ssh_config()
        root = next((r for r in results if "permitrootlogin" in r["item"]), None)
        self.assertIsNotNone(root)
        self.assertEqual(root["status"], "ok")

    def test_sshd_config_missing_error(self):
        with patch("pathlib.Path.exists", return_value=False):
            results = _linux_ssh_config()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "error")

    def test_auditd_active_ok(self):
        with patch("agent_acesso.run_cmd") as mock:
            mock.side_effect = [("active\n", "", 0), ("backlog 0\nlost 0\n", "", 0)]
            results = _linux_auditd()
        svc = next((r for r in results if r["item"] == "auditd_service"), None)
        self.assertIsNotNone(svc)
        self.assertEqual(svc["status"], "ok")

    def test_auditd_inactive_error(self):
        with patch("agent_acesso.run_cmd") as mock:
            mock.side_effect = [("inactive\n", "", 0), ("", "", 1)]
            results = _linux_auditd()
        svc = next((r for r in results if r["item"] == "auditd_service"), None)
        self.assertIsNotNone(svc)
        self.assertEqual(svc["status"], "error")

    def test_auditd_lost_events_warning(self):
        with patch("agent_acesso.run_cmd") as mock:
            mock.side_effect = [("active\n", "", 0), ("backlog 0\nlost 42\n", "", 0)]
            results = _linux_auditd()
        lost = next((r for r in results if r["item"] == "auditd_events_lost"), None)
        self.assertIsNotNone(lost)
        self.assertEqual(lost["status"], "warning")
        self.assertEqual(lost["value"], 42)

    def test_auditd_no_lost_ok(self):
        with patch("agent_acesso.run_cmd") as mock:
            mock.side_effect = [("active\n", "", 0), ("backlog 0\nlost 0\n", "", 0)]
            results = _linux_auditd()
        lost = next((r for r in results if r["item"] == "auditd_events_lost"), None)
        if lost:
            self.assertEqual(lost["status"], "ok")

    def test_root_direct_login_warning(self):
        with patch("agent_acesso.run_cmd", return_value=(
            "root pts/0 Mon Jan 1 10:00 - 10:30 (00:30)\n", "", 0
        )):
            result = _linux_root_direct_logins()
        self.assertEqual(result["status"], "warning")

    def test_root_direct_login_ok_none(self):
        with patch("agent_acesso.run_cmd", return_value=("wtmp begins\n", "", 0)):
            result = _linux_root_direct_logins()
        self.assertEqual(result["status"], "ok")

    def test_locked_accounts_returns_info(self):
        with patch("agent_acesso.run_cmd", return_value=("user1\nuser2\n", "", 0)):
            result = _linux_locked_accounts()
        self.assertEqual(result["status"], "info")
        self.assertIn("user1", result["value"])

    def test_privileged_groups_info(self):
        with patch("agent_acesso.run_cmd", return_value=("sudo:x:27:ubuntu,deploy\n", "", 0)):
            result = _linux_privileged_groups()
        self.assertEqual(result["status"], "info")
        self.assertIsInstance(result["value"], list)

    def test_successful_logins_info(self):
        fake = "Apr 13 10:05:22 sshd Accepted publickey for ubuntu from 10.0.0.1\n"
        with patch("pathlib.Path.exists", return_value=True):
            with patch("agent_acesso.run_cmd", return_value=(fake, "", 0)):
                results = _linux_successful_logins()
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["status"], "info")

    def test_sudo_usage_returns_list(self):
        fake = "Apr 13 09:10:01 sudo: ubuntu COMMAND=/usr/bin/systemctl\n"
        with patch("pathlib.Path.exists", return_value=True):
            with patch("agent_acesso.run_cmd", return_value=(fake, "", 0)):
                results = _linux_sudo_usage()
        self.assertTrue(len(results) > 0)


# ===========================================================================
# PASSO 4 — Coletores Windows
# ===========================================================================

class TestWindowsAccess(unittest.TestCase):
    """PASSO 4: Coletores Windows do agent_acesso."""

    def test_failed_logins_warning_above_10(self):
        events = [{"Message": "m"}] * 15
        with patch("agent_acesso.run_powershell",
                   return_value=(json.dumps(events), "", 0)):
            result = _windows_failed_logins()
        self.assertEqual(result["status"], "warning")
        # Privacidade: o valor enviado contem apenas contagem/agregados
        self.assertEqual(result["value"]["count"], 15)
        self.assertNotIn("Message", json.dumps(result["value"]))

    def test_failed_logins_ok_few(self):
        events = [{"Message": "m"}] * 3
        with patch("agent_acesso.run_powershell",
                   return_value=(json.dumps(events), "", 0)):
            result = _windows_failed_logins()
        self.assertEqual(result["status"], "ok")

    def test_successful_logins_info(self):
        events = [{"Id": 4624}] * 5
        with patch("agent_acesso.run_powershell",
                   return_value=(json.dumps(events), "", 0)):
            result = _windows_successful_logins()
        self.assertEqual(result["status"], "info")
        self.assertEqual(result["value"]["count"], 5)

    def test_account_changes_warning_when_found(self):
        events = [{"Id": 4720}]
        with patch("agent_acesso.run_powershell",
                   return_value=(json.dumps(events), "", 0)):
            result = _windows_account_changes()
        self.assertEqual(result["status"], "warning")
        self.assertEqual(result["value"]["by_event_id"]["4720"], 1)

    def test_account_changes_ok_when_empty(self):
        with patch("agent_acesso.run_powershell", return_value=("", "", 0)):
            result = _windows_account_changes()
        self.assertEqual(result["status"], "ok")

    def test_audit_policy_error_on_fail(self):
        with patch("agent_acesso.run_cmd", return_value=("", "Access denied", 1)):
            results = _windows_audit_policy()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "error")


# ===========================================================================
# PASSO 5 — Isolamento e resiliência
# ===========================================================================

class TestIsolationAndResiliency(unittest.TestCase):
    """PASSO 5: agent_acesso é independente e tolerante a falhas."""

    def test_collect_linux_does_not_call_windows_fns(self):
        """Coleta Linux não deve chamar funções Windows."""
        with patch("agent_acesso._windows_failed_logins") as mock_w:
            with patch("agent_acesso._linux_failed_logins", return_value=[]):
                with patch("agent_acesso._linux_successful_logins", return_value=[]):
                    with patch("agent_acesso._linux_sudo_usage", return_value=[]):
                        with patch("agent_acesso._linux_ssh_config", return_value=[]):
                            with patch("agent_acesso._linux_root_direct_logins",
                                       return_value=finding("x", None, "ok")):
                                with patch("agent_acesso._linux_locked_accounts",
                                           return_value=finding("x", None, "ok")):
                                    with patch("agent_acesso._linux_privileged_groups",
                                               return_value=finding("x", None, "ok")):
                                        with patch("agent_acesso._linux_auditd",
                                                   return_value=[]):
                                            _collect_findings("linux")
        mock_w.assert_not_called()

    def test_one_collector_exception_does_not_crash(self):
        """Exceção em um coletor não derruba os demais."""
        def boom():
            raise RuntimeError("falha simulada")

        with patch("agent_acesso._linux_failed_logins", side_effect=boom):
            with patch("agent_acesso._linux_successful_logins", return_value=[]):
                with patch("agent_acesso._linux_sudo_usage", return_value=[]):
                    with patch("agent_acesso._linux_ssh_config", return_value=[]):
                        with patch("agent_acesso._linux_root_direct_logins",
                                   return_value=finding("x", None, "ok")):
                            with patch("agent_acesso._linux_locked_accounts",
                                       return_value=finding("x", None, "ok")):
                                with patch("agent_acesso._linux_privileged_groups",
                                           return_value=finding("x", None, "ok")):
                                    with patch("agent_acesso._linux_auditd",
                                               return_value=[]):
                                        results = _collect_findings("linux")
        errors = [r for r in results if r["status"] == "error"]
        self.assertGreater(len(errors), 0)

    def test_empty_collect_is_valid_report(self):
        with patch("agent_acesso._collect_findings", return_value=[]):
            report = _build_standalone_report("linux")
        self.assertEqual(report["total_findings"], 0)
        self.assertIsInstance(report["findings"], list)

    def test_run_cmd_never_raises(self):
        try:
            run_cmd(["nao_existe_xyz_abc"])
        except Exception as e:
            self.fail(f"run_cmd levantou exceção: {e}")


# ===========================================================================
# PASSO 6 — Persistência
# ===========================================================================

class TestPersistence(unittest.TestCase):
    """PASSO 6: Salvamento do relatório em disco."""

    def _make_report(self):
        with patch("agent_acesso._collect_findings", return_value=[]):
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
        self.assertEqual(loaded["pilar"], "acesso")
        self.assertEqual(loaded["agent"], "agent_acesso")

    def test_findings_preserved_in_file(self):
        mock_f = [finding("item_test", "val", "ok", "detalhe")]
        with patch("agent_acesso._collect_findings", return_value=mock_f):
            report = _build_standalone_report("linux")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        _save_report(report, path)
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(loaded["total_findings"], 1)
        self.assertEqual(loaded["findings"][0]["item"], "item_test")


if __name__ == "__main__":
    unittest.main(verbosity=2)

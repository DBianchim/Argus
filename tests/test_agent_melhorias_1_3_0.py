"""
test_agent_melhorias_1_3_0.py — Melhorias do agente 1.3.0 (ver CONTRATO.md §8)
==============================================================================
Execute com:
    python -m unittest tests/test_agent_melhorias_1_3_0.py -v

    - nome de serviço perigoso nunca chega ao PowerShell nem ao systemctl;
    - .tar.gz truncado é falha de integridade (crítico), não "não verificado";
    - tempo de atividade também no Windows.
"""

import io
import os
import sys
import tarfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

import agent_operacional
from agent_operacional import linux_services, win_services, win_uptime
from core.sysutils import is_safe_service_name

sys.path.insert(0, str(Path(__file__).parent))
from test_agent_backup import BackupTestCase  # noqa: E402


class TestNomeDeServico(unittest.TestCase):

    def test_nomes_reais_aceitos(self):
        for name in ["W32Time", "LanmanServer", "sshd", "getty@tty1", "my-app.service",
                     "MSSQL$SQLEXPRESS", "Some Service"]:
            self.assertTrue(is_safe_service_name(name), name)

    def test_nomes_perigosos_recusados(self):
        for name in ["x'; Remove-Item C:\\ -Recurse; '", "$(whoami)", "a;b", "a|b", "a`b",
                     "--help", "-H", "", " ssh", "ab\u2019c", None, 42]:
            self.assertFalse(is_safe_service_name(name), repr(name))

    def test_windows_nao_executa_powershell_com_nome_perigoso(self):
        evil = "x'; Remove-Item C:\\ -Recurse; '"
        with patch.object(agent_operacional, "_win_run_powershell") as ps:
            result = win_services([evil])
        ps.assert_not_called()
        self.assertEqual(result, [{"name": evil, "status": "not_found"}])

    def test_windows_nome_valido_segue_consultado(self):
        with patch.object(agent_operacional, "_win_run_powershell",
                          return_value='{"name":"W32Time","status":"Running","start":"Automatic"}') as ps:
            result = win_services(["W32Time"])
        ps.assert_called_once()
        self.assertEqual(result[0]["status"], "running")

    def test_linux_nao_chama_systemctl_com_opcao(self):
        with patch.object(agent_operacional, "run_command") as cmd:
            result = linux_services(["--help"])
        cmd.assert_not_called()
        self.assertEqual(result, [{"name": "--help", "status": "not_found"}])


class TestTarTruncado(BackupTestCase):

    def _tar_gz(self) -> bytes:
        payload = os.urandom(200_000)   # aleatório: não comprime, o truncamento cai no meio
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo("dados.bin")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        return buf.getvalue()

    def test_tar_gz_truncado_e_integrity_fail(self):
        data = self._tar_gz()
        self.make_backup("db.tar.gz", data[: len(data) // 2])
        r = self.cycle(extensions=[".tar.gz"])
        self.assertEqual(r["status"], "INTEGRITY_FAIL")
        self.assertEqual(r["integrity"]["integrity_check"], "FAIL")

    def test_gzip_invalido_e_integrity_fail(self):
        self.make_backup("db.tar.gz", b"isto nao e gzip" * 100)
        r = self.cycle(extensions=[".tar.gz"])
        self.assertEqual(r["status"], "INTEGRITY_FAIL")

    def test_tar_gz_integro_segue_ok(self):
        self.make_backup("db.tar.gz", self._tar_gz())
        r = self.cycle(extensions=[".tar.gz"])
        self.assertEqual(r["status"], "OK")


class TestUptimeWindows(unittest.TestCase):

    def test_le_segundos(self):
        with patch.object(agent_operacional, "_win_run_powershell", return_value="86400"):
            self.assertEqual(win_uptime(), 86400)

    def test_falha_retorna_none(self):
        for raw in ["", "erro", "-5"]:
            with patch.object(agent_operacional, "_win_run_powershell", return_value=raw):
                self.assertIsNone(win_uptime(), raw)

    def test_collect_windows_envia_uptime(self):
        fake_cfg = type("C", (), {})()
        fake_cfg.operacional = type("O", (), {"critical_services_windows": []})()
        fake_cfg.global_ = type("G", (), {"hostname": "h"})()
        with patch.object(agent_operacional, "OS_FAMILY", "windows"), \
             patch.object(agent_operacional, "win_cpu", return_value={}), \
             patch.object(agent_operacional, "win_memory", return_value={}), \
             patch.object(agent_operacional, "win_disk", return_value=[]), \
             patch.object(agent_operacional, "win_uptime", return_value=123):
            payload = agent_operacional.collect(fake_cfg)
        self.assertEqual(payload["metrics"]["uptime_seconds"], 123)

    def test_collect_windows_sem_uptime_omite_a_chave(self):
        fake_cfg = type("C", (), {})()
        fake_cfg.operacional = type("O", (), {"critical_services_windows": []})()
        fake_cfg.global_ = type("G", (), {"hostname": "h"})()
        with patch.object(agent_operacional, "OS_FAMILY", "windows"), \
             patch.object(agent_operacional, "win_cpu", return_value={}), \
             patch.object(agent_operacional, "win_memory", return_value={}), \
             patch.object(agent_operacional, "win_disk", return_value=[]), \
             patch.object(agent_operacional, "win_uptime", return_value=None):
            payload = agent_operacional.collect(fake_cfg)
        self.assertNotIn("uptime_seconds", payload["metrics"])


if __name__ == "__main__":
    unittest.main()

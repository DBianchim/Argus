"""
test_agent_operacional_services.py — Servicos criticos no Linux (ssh x sshd)
=============================================================================
Execute com:
    python -m unittest tests/test_agent_operacional_services.py -v

O nome da unit do OpenSSH varia por distro (Debian/Ubuntu: ssh; RHEL: sshd). O
agente resolve o nome que existe no host, sem mudar o 'name' configurado.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Aponta para agents/ — um nivel acima de tests/
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from agent_operacional import linux_services


def _systemctl(states: dict):
    """run_command simulado: states = {('is-active', 'ssh'): 'active', ...}."""
    def fake(args, timeout=15):
        return states.get((args[1], args[2]), "")
    return fake


class TestLinuxServices(unittest.TestCase):

    def run_services(self, names, states):
        with patch("agent_operacional.run_command", side_effect=_systemctl(states)):
            return linux_services(names)

    def test_sshd_resolve_para_ssh_em_debian_ubuntu(self):
        result = self.run_services(["sshd"], {
            ("is-active", "sshd"): "inactive",
            ("is-active", "ssh"): "active",
            ("is-enabled", "ssh"): "enabled",
        })
        self.assertEqual(result, [
            {"name": "sshd", "status": "active", "enabled": "enabled", "unit": "ssh"},
        ])

    def test_ssh_resolve_para_sshd(self):
        result = self.run_services(["ssh"], {
            ("is-active", "ssh"): "inactive",
            ("is-active", "sshd"): "active",
            ("is-enabled", "sshd"): "enabled",
        })
        self.assertEqual(result[0]["status"], "active")
        self.assertEqual(result[0]["unit"], "sshd")

    def test_unit_configurada_ativa_nao_consulta_alias_nem_traz_unit(self):
        result = self.run_services(["sshd"], {
            ("is-active", "sshd"): "active",
            ("is-enabled", "sshd"): "enabled",
        })
        self.assertEqual(result, [{"name": "sshd", "status": "active", "enabled": "enabled"}])

    def test_ssh_parado_de_verdade_continua_reportado_parado(self):
        # Nem a unit nem o alias ativos: o agente nao esconde o problema
        result = self.run_services(["sshd"], {
            ("is-active", "sshd"): "failed",
            ("is-active", "ssh"): "inactive",
        })
        self.assertEqual(result[0]["status"], "failed")
        self.assertNotIn("unit", result[0])

    def test_servico_sem_alias_nao_e_alterado(self):
        result = self.run_services(["cron"], {("is-active", "cron"): "inactive"})
        self.assertEqual(result[0]["status"], "inactive")
        self.assertNotIn("unit", result[0])

    def test_sem_saida_do_systemctl_vira_not_found(self):
        result = self.run_services(["nginx"], {})
        self.assertEqual(result[0]["status"], "not-found")
        self.assertEqual(result[0]["enabled"], "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)

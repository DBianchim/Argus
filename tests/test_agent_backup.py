"""
test_agent_backup.py — Testes do agente de Backup (deteccao de estagnacao)
===========================================================================
Execute com:
    python -m unittest tests/test_agent_backup.py -v

Cobre o estado persistente (backup_state.json), fora do diretorio de backup:
    - estagnado = backup NOVO (caminho ou mtime/tamanho diferentes) com SHA256
      identico ao backup anterior observado;
    - mesmo arquivo, inalterado, em ciclos repetidos NAO e estagnacao;
    - integrity_check='ERROR' nao pode virar status OK.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Aponta para agents/ — um nivel acima de tests/
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

import agent_backup
from agent_backup import (
    STATE_FILENAME,
    check_backup_files,
    collect,
    compute_sha256,
    load_state,
    save_state,
)
from core.sysutils import state_file_path


class BackupTestCase(unittest.TestCase):
    """Base: diretorio de backup e diretorio de estado separados, em tmp."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.backup_dir = root / "backups"
        self.backup_dir.mkdir()
        self.state_path = str(root / "agent" / STATE_FILENAME)

    def make_backup(self, name: str, content: bytes, age_hours: float = 1.0) -> str:
        """Cria/sobrescreve um backup com mtime = agora - age_hours."""
        path = self.backup_dir / name
        path.write_bytes(content)
        mtime = time.time() - age_hours * 3600
        os.utime(path, (mtime, mtime))
        return str(path)

    def cycle(self, **overrides) -> dict:
        """Um ciclo do agente: devolve o dict de check_backup_files."""
        kwargs = dict(
            paths=[str(self.backup_dir)],
            extensions=[".bak"],
            min_size_mb=0,
            sla_hours=48,
            state_path=self.state_path,
        )
        kwargs.update(overrides)
        return check_backup_files(**kwargs)


class TestEstagnacao(BackupTestCase):

    def test_primeira_execucao_e_ok_e_grava_estado(self):
        self.make_backup("db_1.bak", b"conteudo A")
        r = self.cycle()
        self.assertEqual(r["status"], "OK")
        self.assertEqual(r["integrity"]["integrity_check"], "OK")
        self.assertIn("Primeira observacao", r["integrity"]["detail"])
        self.assertIsNone(r["integrity"]["previous_sha256"])
        self.assertFalse(r["integrity"]["stagnant"])
        state = load_state(self.state_path)
        self.assertEqual(state["sha256"], r["integrity"]["sha256"])

    def test_mesmo_arquivo_intocado_em_ciclos_repetidos_nao_alerta(self):
        self.make_backup("db.bak", b"conteudo A")
        for _ in range(5):
            r = self.cycle()
            self.assertEqual(r["status"], "OK")
            self.assertFalse(r["integrity"]["stagnant"])
        # Do 2o ciclo em diante o hash vem do estado (arquivo nao e relido)
        self.assertEqual(r["integrity"]["hash_source"], "cached")

    def test_arquivo_intocado_nao_recalcula_sha256(self):
        self.make_backup("db.bak", b"conteudo A")
        self.cycle()
        with patch.object(agent_backup, "compute_sha256") as mocked:
            self.cycle()
            self.cycle()
        mocked.assert_not_called()

    def test_novo_arquivo_com_conteudo_diferente_e_ok(self):
        self.make_backup("db_1.bak", b"conteudo A", age_hours=25)
        first = self.cycle()
        self.make_backup("db_2.bak", b"conteudo B", age_hours=1)
        r = self.cycle()
        self.assertEqual(r["status"], "OK")
        self.assertFalse(r["integrity"]["stagnant"])
        self.assertEqual(r["integrity"]["previous_sha256"], first["integrity"]["sha256"])
        self.assertNotEqual(r["integrity"]["sha256"], first["integrity"]["sha256"])

    def test_novo_arquivo_com_hash_identico_e_estagnado(self):
        self.make_backup("db_1.bak", b"conteudo A", age_hours=25)
        self.cycle()
        self.make_backup("db_2.bak", b"conteudo A", age_hours=1)  # nome novo, mesmo conteudo
        r = self.cycle()
        self.assertEqual(r["status"], "WARN")
        self.assertEqual(r["integrity"]["integrity_check"], "WARN")
        self.assertTrue(r["integrity"]["stagnant"])
        self.assertEqual(r["integrity"]["sha256"], r["integrity"]["previous_sha256"])
        self.assertEqual(r["integrity"]["hash_source"], "computed")

    def test_estagnacao_persiste_nos_ciclos_seguintes_ate_backup_novo(self):
        self.make_backup("db_1.bak", b"conteudo A", age_hours=25)
        self.cycle()
        self.make_backup("db_2.bak", b"conteudo A", age_hours=2)
        self.assertEqual(self.cycle()["status"], "WARN")
        # Ciclos seguintes sobre o mesmo arquivo estagnado continuam em WARN
        again = self.cycle()
        self.assertEqual(again["status"], "WARN")
        self.assertEqual(again["integrity"]["hash_source"], "cached")
        # Chega um backup bom: volta a OK
        self.make_backup("db_3.bak", b"conteudo B", age_hours=1)
        self.assertEqual(self.cycle()["status"], "OK")

    def test_sobrescrita_no_mesmo_caminho_com_mesmo_conteudo_e_estagnada(self):
        self.make_backup("db.bak", b"conteudo A", age_hours=25)
        self.cycle()
        self.make_backup("db.bak", b"conteudo A", age_hours=1)  # mesmo caminho, mtime novo
        r = self.cycle()
        self.assertEqual(r["status"], "WARN")
        self.assertTrue(r["integrity"]["stagnant"])

    def test_sobrescrita_no_mesmo_caminho_com_conteudo_novo_e_ok(self):
        self.make_backup("db.bak", b"conteudo A", age_hours=25)
        self.cycle()
        self.make_backup("db.bak", b"conteudo B diferente", age_hours=1)
        r = self.cycle()
        self.assertEqual(r["status"], "OK")
        self.assertFalse(r["integrity"]["stagnant"])

    def test_compara_com_a_execucao_anterior_e_nao_com_a_primeira(self):
        # Regressao: o sidecar antigo ficava congelado no hash da 1a observacao.
        self.make_backup("db.bak", b"A", age_hours=50)
        self.cycle(sla_hours=100)
        self.make_backup("db.bak", b"B", age_hours=26)
        self.assertEqual(self.cycle(sla_hours=100)["status"], "OK")
        self.make_backup("db.bak", b"B", age_hours=2)   # igual ao de ontem, nao ao de anteontem
        self.assertEqual(self.cycle(sla_hours=100)["status"], "WARN")

    def test_cenario_de_simulacao_ciclos_1_a_5(self):
        # 1: novo | 2-3: intocado | 4: sobrescrito c/ mesmo conteudo | 5: repetido
        self.make_backup("db.bak", b"A", age_hours=25)
        status = [self.cycle()["status"]]
        status += [self.cycle()["status"] for _ in range(2)]
        self.make_backup("db.bak", b"A", age_hours=1)
        status += [self.cycle()["status"]]
        status += [self.cycle()["status"]]
        self.assertEqual(status, ["OK", "OK", "OK", "WARN", "WARN"])

    def test_sem_state_path_nao_detecta_estagnacao_mas_nao_quebra(self):
        self.make_backup("db.bak", b"A")
        r = self.cycle(state_path=None)
        self.assertEqual(r["status"], "OK")
        self.assertFalse(os.path.exists(self.state_path))


class TestEstadoForaDoDiretorioDeBackup(BackupTestCase):

    def test_nenhum_arquivo_e_criado_no_diretorio_de_backup(self):
        self.make_backup("db.bak", b"A")
        before = sorted(os.listdir(self.backup_dir))
        self.cycle()
        self.cycle()
        self.assertEqual(sorted(os.listdir(self.backup_dir)), before)
        self.assertTrue(os.path.isfile(self.state_path))

    def test_sidecar_antigo_e_ignorado(self):
        path = self.make_backup("db.bak", b"A")
        Path(path + ".sha256").write_text(compute_sha256(path), encoding="utf-8")
        r = self.cycle()
        self.assertEqual(r["status"], "OK")  # nao herda o WARN do sidecar congelado

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "chmod de diretorio so bloqueia escrita em POSIX nao-root")
    def test_diretorio_de_backup_somente_leitura_nao_gera_erro(self):
        self.make_backup("db.bak", b"A")
        os.chmod(self.backup_dir, 0o555)
        self.addCleanup(os.chmod, self.backup_dir, 0o755)
        r = self.cycle()
        self.assertEqual(r["status"], "OK")
        self.assertNotEqual(r["integrity"]["integrity_check"], "ERROR")

    def test_estado_corrompido_vira_primeira_observacao(self):
        self.make_backup("db.bak", b"A")
        os.makedirs(os.path.dirname(self.state_path))
        Path(self.state_path).write_text("{ isto nao e json", encoding="utf-8")
        r = self.cycle()
        self.assertEqual(r["status"], "OK")
        self.assertIn("Primeira observacao", r["integrity"]["detail"])
        # O estado e reescrito de forma valida
        self.assertIsNotNone(load_state(self.state_path))

    def test_estado_com_campos_invalidos_e_descartado(self):
        os.makedirs(os.path.dirname(self.state_path))
        bad_states = [
            [],                                                     # raiz nao e dict
            {"last": None},
            {"last": {"path": "x"}},                                # campos ausentes
            {"last": {"path": "x", "mtime_ns": "1", "size": 1,      # tipo errado
                      "sha256": "a" * 64}},
            {"last": {"path": "x", "mtime_ns": 1, "size": 1,        # hash invalido
                      "sha256": "curto"}},
        ]
        for bad in bad_states:
            Path(self.state_path).write_text(json.dumps(bad), encoding="utf-8")
            self.assertIsNone(load_state(self.state_path), bad)

    def test_estado_ausente_retorna_none(self):
        self.assertIsNone(load_state(self.state_path))
        self.assertIsNone(load_state(None))

    def test_falha_ao_gravar_estado_nao_quebra_a_coleta(self):
        self.make_backup("db.bak", b"A")
        # O "diretorio" do estado e na verdade um arquivo -> makedirs/open falham
        blocker = Path(self._tmp.name) / "blocker"
        blocker.write_text("x", encoding="utf-8")
        r = self.cycle(state_path=str(blocker / "sub" / STATE_FILENAME))
        self.assertEqual(r["status"], "OK")
        self.assertIn("state_warning", r["integrity"])

    def test_save_state_nao_deixa_tmp_para_tras(self):
        entry = {"path": "x", "mtime_ns": 1, "size": 1, "sha256": "a" * 64,
                 "previous_sha256": None, "stagnant": False}
        self.assertIsNone(save_state(self.state_path, entry))
        self.assertEqual(os.listdir(os.path.dirname(self.state_path)), [STATE_FILENAME])
        self.assertEqual(load_state(self.state_path), entry)


class TestErroEFalhasNaoViramOk(BackupTestCase):

    def test_erro_de_leitura_nao_vira_ok(self):
        self.make_backup("db.bak", b"A")
        with patch.object(agent_backup, "compute_sha256", side_effect=PermissionError):
            r = self.cycle()
        self.assertEqual(r["integrity"]["integrity_check"], "ERROR")
        self.assertEqual(r["status"], "WARN")
        self.assertIn("permissao", r["integrity"]["detail"])

    def test_erro_generico_nao_vira_ok(self):
        self.make_backup("db.bak", b"A")
        with patch.object(agent_backup, "compute_sha256", side_effect=OSError("disco com defeito")):
            r = self.cycle()
        self.assertEqual(r["status"], "WARN")
        self.assertIn("disco com defeito", r["integrity"]["detail"])

    def test_erro_nao_vira_referencia_de_estado(self):
        self.make_backup("db.bak", b"A")
        with patch.object(agent_backup, "compute_sha256", side_effect=PermissionError):
            self.cycle()
        self.assertFalse(os.path.exists(self.state_path))

    def test_sla_breach_tem_prioridade_sobre_erro(self):
        self.make_backup("db.bak", b"A", age_hours=100)
        with patch.object(agent_backup, "compute_sha256", side_effect=PermissionError):
            r = self.cycle(sla_hours=24)
        self.assertEqual(r["status"], "SLA_BREACH")

    def test_arquivo_pequeno_demais_e_integrity_fail_e_nao_vira_referencia(self):
        self.make_backup("db.bak", b"A")
        r = self.cycle(min_size_mb=10)
        self.assertEqual(r["status"], "INTEGRITY_FAIL")
        self.assertFalse(os.path.exists(self.state_path))

    def test_sem_backup_retorna_no_backup_found(self):
        r = self.cycle()
        self.assertEqual(r["status"], "NO_BACKUP_FOUND")


class TestCollect(BackupTestCase):

    def test_collect_grava_estado_ao_lado_da_fila(self):
        self.make_backup("db.bak", b"A")
        queue_path = str(Path(self._tmp.name) / "agent" / "queue")
        backup_cfg = SimpleNamespace(
            paths_windows=[str(self.backup_dir)],
            paths_linux=[str(self.backup_dir)],
            extensions=[".bak"],
            min_size_mb=0,
            sla_hours=48,
        )
        config = SimpleNamespace(
            backup=backup_cfg,
            global_=SimpleNamespace(hostname="srv-teste"),
            retry=SimpleNamespace(queue_path=queue_path),
        )
        payload = collect(config)
        self.assertEqual(payload["pilar"], "backup")
        self.assertEqual(payload["metrics"]["backup"]["status"], "OK")
        self.assertTrue(os.path.isfile(self.state_path))
        # Segundo ciclo: mesmo arquivo, sem WARN
        self.assertEqual(collect(config)["metrics"]["backup"]["status"], "OK")

    def test_state_file_path_deriva_do_diretorio_pai_da_fila(self):
        self.assertEqual(
            state_file_path(os.path.join("base", "queue"), "x.json"),
            os.path.join("base", "x.json"),
        )
        self.assertEqual(
            state_file_path("base/queue/", "x.json"),
            os.path.join("base", "x.json"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

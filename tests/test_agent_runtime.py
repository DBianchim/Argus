"""
test_agent_runtime.py — Estado em disco e instancia unica do agente
====================================================================
Execute com:
    python -m unittest tests/test_agent_runtime.py -v

Cobre:
    - gravacao do estado (backup_state.json) na pasta PAI da fila local e o
      comportamento claro (state_warning / aviso no runner) quando ela nao grava
      — caso real: Linux com ProtectSystem=strict e pasta root:root;
    - trava de instancia unica (runner.py): segunda instancia e recusada e o lock
      de um processo morto e reaproveitado.
"""

import errno
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Aponta para agents/ — um nivel acima de tests/
AGENTS_DIR = Path(__file__).parent.parent / "agents"
sys.path.insert(0, str(AGENTS_DIR))

from agent_backup import STATE_FILENAME, collect
from core.instance_lock import EXIT_ALREADY_RUNNING, InstanceLock, acquire_instance_lock
from core.sysutils import state_dir_error, state_file_path


def _config(queue_path: str, backup_dir: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        backup=SimpleNamespace(paths_linux=[backup_dir], paths_windows=[backup_dir],
                               extensions=[".bak"], min_size_mb=0, sla_hours=48),
        global_=SimpleNamespace(hostname="srv-teste"),
        retry=SimpleNamespace(queue_path=queue_path),
    )


class TestEstadoNaPastaDaFila(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.queue = self.root / "state" / "queue"      # ex.: /var/lib/argus/agent-monitor/queue
        self.queue.mkdir(parents=True)
        self.backups = self.root / "backups"
        self.backups.mkdir()
        (self.backups / "db.bak").write_bytes(b"conteudo")

    def test_estado_e_gravado_na_pasta_pai_da_fila(self):
        payload = collect(_config(str(self.queue), str(self.backups)))
        integrity = payload["metrics"]["backup"]["integrity"]
        self.assertNotIn("state_warning", integrity)
        self.assertTrue((self.root / "state" / STATE_FILENAME).is_file())
        self.assertIsNone(state_dir_error(str(self.queue)))
        # a pasta da fila nao fica com sobra do probe nem do .tmp
        self.assertEqual(sorted(os.listdir(self.root / "state")), sorted(["queue", STATE_FILENAME]))

    def test_pasta_somente_leitura_gera_state_warning_sem_quebrar_a_coleta(self):
        # Errno 30 como visto no Ubuntu com a unit endurecida
        real_open = open

        def read_only_open(path, mode="r", *args, **kwargs):
            if "w" in mode:
                raise OSError(errno.EROFS, "Read-only file system", str(path))
            return real_open(path, mode, *args, **kwargs)

        with patch("agent_backup.open", side_effect=read_only_open, create=True):
            payload = collect(_config(str(self.queue), str(self.backups)))
        backup = payload["metrics"]["backup"]
        self.assertEqual(backup["status"], "OK")
        self.assertIn("Read-only file system", backup["integrity"]["state_warning"])
        self.assertFalse((self.root / "state" / STATE_FILENAME).exists())

    def test_state_dir_error_descreve_pasta_nao_gravavel(self):
        erofs = OSError(errno.EROFS, "Read-only file system")
        with patch("core.sysutils.tempfile.mkstemp", side_effect=erofs):
            error = state_dir_error(str(self.queue))
        self.assertIn("Read-only file system", error)
        self.assertIn(os.path.dirname(state_file_path(str(self.queue), "x")), error)

    def test_state_dir_error_quando_o_caminho_e_um_arquivo(self):
        blocker = self.root / "blocker"
        blocker.write_text("x", encoding="utf-8")
        self.assertIsNotNone(state_dir_error(str(blocker / "sub" / "queue")))


class TestInstanciaUnica(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "state", "agent.lock")

    def lock(self) -> InstanceLock:
        lock = InstanceLock(self.path)
        self.addCleanup(lock.release)
        return lock

    def test_primeira_instancia_obtem_e_grava_o_pid(self):
        first = self.lock()
        self.assertTrue(first.acquire())
        self.assertEqual(first.holder_pid(), os.getpid())

    def test_segunda_instancia_e_recusada(self):
        first, second = self.lock(), self.lock()
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())

    def test_liberada_pode_ser_obtida_de_novo(self):
        first, second = self.lock(), self.lock()
        self.assertTrue(first.acquire())
        first.release()
        self.assertTrue(second.acquire())

    def test_lock_de_processo_morto_e_reaproveitado(self):
        # Um processo real segura a trava e e morto a forca (sem release): o SO
        # libera o lock e o arquivo com o PID velho nao bloqueia o proximo agente.
        script = textwrap.dedent("""
            import os, sys
            sys.path.insert(0, sys.argv[1])
            from core.instance_lock import InstanceLock
            lock = InstanceLock(sys.argv[2])
            print(os.getpid() if lock.acquire() else 'busy', flush=True)
            sys.stdin.read()
        """)
        child = subprocess.Popen(
            [sys.executable, "-c", script, str(AGENTS_DIR), self.path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(child.stdout.close)
        self.addCleanup(child.stdin.close)
        self.addCleanup(child.kill)
        # No Windows, sys.executable de um venv e um launcher: o PID que vale e o
        # do Python que segura a trava (impresso por ele), nao o de Popen.
        holder = int(child.stdout.readline())

        mine = self.lock()
        self.assertFalse(mine.acquire())                 # processo vivo segura a trava
        self.assertEqual(mine.holder_pid(), holder)

        os.kill(holder, signal.SIGTERM)                  # morte a forca, sem release()
        child.wait(timeout=10)
        deadline = time.time() + 10
        acquired = mine.acquire()
        while not acquired and time.time() < deadline:
            time.sleep(0.1)
            acquired = mine.acquire()
        self.assertTrue(acquired)                        # processo morto: reaproveitada
        self.assertEqual(mine.holder_pid(), os.getpid())

    def test_pasta_sem_permissao_levanta_oserror_para_o_chamador_degradar(self):
        with patch("core.instance_lock.os.open", side_effect=OSError(errno.EROFS, "ro")):
            with self.assertRaises(OSError):
                InstanceLock(self.path).acquire()


class TestAcquireInstanceLock(unittest.TestCase):
    """acquire_instance_lock e o que o runner chama no inicio."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.queue = os.path.join(self._tmp.name, "queue")

    def test_segunda_instancia_encerra_com_exit_code_proprio(self):
        first = acquire_instance_lock(self.queue)
        self.addCleanup(first.release)
        with self.assertRaises(SystemExit) as ctx:
            acquire_instance_lock(self.queue)
        self.assertEqual(ctx.exception.code, EXIT_ALREADY_RUNNING)

    def test_trava_fica_ao_lado_da_fila(self):
        lock = acquire_instance_lock(self.queue)
        self.addCleanup(lock.release)
        self.assertEqual(lock.path, state_file_path(self.queue, "agent.lock"))

    def test_sem_permissao_para_a_trava_segue_sem_ela(self):
        with patch("core.instance_lock.os.open", side_effect=OSError(errno.EROFS, "ro")):
            self.assertIsNone(acquire_instance_lock(self.queue))


if __name__ == "__main__":
    unittest.main(verbosity=2)

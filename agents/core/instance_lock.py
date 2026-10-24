#!/usr/bin/env python3
"""
instance_lock.py — Trava de instancia unica do agente.

Dois agentes rodando no mesmo host consomem a mesma fila local e geram
"Flush concluido" duplicado e "Falha ao remover arquivo da fila". Isso acontece,
por exemplo, no Windows, onde Stop-ScheduledTask nao encerra o python.exe e um
novo Start-ScheduledTask sobe um segundo agente.

A trava e um lock do SISTEMA OPERACIONAL (fcntl.flock no Linux, msvcrt.locking
no Windows) sobre um arquivo na pasta de estado do agente. O SO libera o lock
quando o processo termina — mesmo morto a forca —, entao um arquivo deixado por
um processo morto nunca bloqueia o proximo agente. O PID gravado no arquivo serve
apenas de diagnostico.
"""

import logging
import os
import sys

from core.sysutils import state_file_path

logger = logging.getLogger(__name__)

try:
    import fcntl
except ImportError:          # Windows
    fcntl = None
    import msvcrt

# Exit code quando outra instancia ja esta rodando (diferente de 0/1/2 do argparse).
EXIT_ALREADY_RUNNING = 3

# Erro de "trava ocupada": no Linux so BlockingIOError (EAGAIN); outros erros do flock
# (ex.: ENOLCK) nao significam "outra instancia" e sobem ao chamador. No Windows o
# msvcrt.locking levanta OSError generico.
_BUSY = (BlockingIOError,) if fcntl is not None else (OSError,)

# Byte travado no Windows: bem alem do PID gravado, para que a segunda instancia
# consiga LER o PID (leitura de regiao travada falha no Windows).
_WIN_LOCK_OFFSET = 1 << 20


class InstanceLock:
    """Lock exclusivo e nao bloqueante sobre um arquivo; vale ate release() ou o fim do processo."""

    def __init__(self, path: str):
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        """
        Tenta obter a trava.

        Returns:
            True se obteve; False se outra instancia ja a detem.

        Raises:
            OSError: se o arquivo de trava nao pode ser criado/aberto (ex: pasta
                     somente leitura) — o chamador decide como degradar.
        """
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o640)
        try:
            self._lock(fd)
        except _BUSY:
            os.close(fd)
            return False
        except OSError:
            os.close(fd)
            raise
        self._fd = fd
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode('ascii'))
        return True

    def holder_pid(self) -> int | None:
        """PID gravado no arquivo de trava (best-effort; so para mensagens)."""
        try:
            with open(self.path, encoding='ascii') as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            self._unlock(self._fd)
        except OSError:
            pass
        os.close(self._fd)
        self._fd = None

    @staticmethod
    def _lock(fd: int) -> None:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            os.lseek(fd, 0, os.SEEK_SET)

    @staticmethod
    def _unlock(fd: int) -> None:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def acquire_instance_lock(queue_path: str) -> InstanceLock | None:
    """
    Garante um unico agente por host (a fila e o estado sao compartilhados).

    O arquivo de trava fica ao lado da fila local (agent.lock, ver state_file_path).

    Returns:
        A trava obtida (mantida ate o fim do processo); None se a pasta de estado
        nao permite criar o arquivo — nesse caso segue sem trava, com aviso.
        Encerra o processo (EXIT_ALREADY_RUNNING) se outra instancia detem a trava.
    """
    lock = InstanceLock(state_file_path(queue_path, 'agent.lock'))
    try:
        if lock.acquire():
            return lock
    except OSError as e:
        logger.warning('Trava de instancia unica indisponivel | arquivo=%s | erro=%s',
                       lock.path, e)
        return None
    logger.error('Ja existe outro agente em execucao neste host (pid=%s | trava=%s). '
                 'Encerre o processo anterior antes de iniciar um novo.',
                 lock.holder_pid() or '?', lock.path)
    sys.exit(EXIT_ALREADY_RUNNING)

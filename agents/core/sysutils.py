#!/usr/bin/env python3
"""
sysutils.py — Utilitarios compartilhados pelos agentes

Reune funcoes que antes eram reimplementadas em cada agente (now_iso,
detect_os, execucao de subprocess e construcao de findings), eliminando
duplicacao (DRY) e garantindo comportamento consistente entre os pilares.

Os agentes importam destas funcoes em vez de redefini-las. Como todos
dependem apenas de core/ (e nunca uns dos outros), a independencia entre
agentes e preservada.

Seguranca:
    - run_cmd usa shell=False obrigatoriamente — ver docstring da funcao.

Autores: Equipe de Infraestrutura
"""

import datetime
import logging
import os
import platform
import subprocess
import tempfile

logger = logging.getLogger(__name__)


# ── versao do agente ──────────────────────────────────────────────────────────

# Versao unica do pacote de agentes, enviada em cada payload (agent_version).
# Incremente a cada release que altere a coleta ou o contrato (ver CONTRATO.md
# na raiz do projeto). E a fonte unica: runner.py e os 4 agentes leem daqui.
AGENT_VERSION = '1.1.0'


# ── arquivos de estado ────────────────────────────────────────────────────────

def state_file_path(queue_path: str, filename: str) -> str:
    """
    Caminho de um arquivo de estado do agente, ao lado da pasta da fila local.

    O estado persistente do agente (cache de config, ultimo backup observado)
    vive fora dos diretorios monitorados, no mesmo diretorio pai de
    config.retry.queue_path. Nao cria nada em disco — apenas calcula o caminho.

    Args:
        queue_path: Valor de config.retry.queue_path.
        filename:   Nome do arquivo de estado (ex: 'backup_state.json').
    """
    base = os.path.dirname(queue_path.rstrip('/\\')) or queue_path
    return os.path.join(base, filename)


def state_dir_error(queue_path: str) -> str | None:
    """
    Verifica se a pasta de estado do agente aceita gravacao.

    Cria um arquivo temporario na pasta de state_file_path() e o remove. Serve
    para avisar no inicio (runner) quando o estado nao sera persistido — por
    exemplo, em instalacao Linux antiga em que a pasta e root:root ou fica fora
    do ReadWritePaths da unit systemd.

    Returns:
        None se a pasta e gravavel; senao, texto com o caminho e o erro.
    """
    base = os.path.dirname(state_file_path(queue_path, 'x'))
    try:
        os.makedirs(base, exist_ok=True)
        fd, probe = tempfile.mkstemp(dir=base, prefix='.probe-')
        os.close(fd)
        os.remove(probe)
    except OSError as exc:
        return f'{base}: {exc}'
    return None


# ── tempo ─────────────────────────────────────────────────────────────────────

def now_iso() -> str:
    """
    Retorna o timestamp atual em ISO 8601 UTC, sem microssegundos.

    Usa datetime.now(timezone.utc) (timezone-aware) em vez de utcnow()
    (deprecado no Python 3.12+). Formato uniforme em todos os pilares:
    '2026-06-08T22:37:54Z'.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ── plataforma ────────────────────────────────────────────────────────────────

def detect_os() -> str:
    """Retorna 'windows' ou 'linux' com base no sistema em execucao."""
    return 'windows' if platform.system().lower() == 'windows' else 'linux'


# ── journald ──────────────────────────────────────────────────────────────────

# Grupos que dao leitura ao journal do sistema.
_JOURNAL_GROUPS = {'systemd-journal', 'adm', 'wheel'}


def journald_active() -> bool:
    """True se o journald esta rodando (socket em /run/systemd/journal). Sem subprocesso."""
    return os.path.exists('/run/systemd/journal/socket')


def journal_readable() -> bool:
    """True se o usuario do agente le o journal do sistema (root ou grupo systemd-journal/adm)."""
    if getattr(os, 'geteuid', lambda: -1)() == 0:
        return True
    try:
        import grp
        names = {grp.getgrgid(gid).gr_name for gid in os.getgroups()}
    except (ImportError, KeyError, AttributeError):
        return False
    return bool(names & _JOURNAL_GROUPS)


# ── execucao de comandos ──────────────────────────────────────────────────────

def run_cmd(args: list[str], timeout: int = 15) -> tuple[str, str, int]:
    """
    Executa um comando do sistema de forma segura e nunca levanta excecao.

    SEGURANCA: shell=False e obrigatorio. Ao passar uma lista de argumentos
    com shell=False, o Python executa o binario diretamente (execv), sem
    envolver o shell do SO (/bin/sh ou cmd.exe). Isso impede que caracteres
    como ; | && sejam interpretados como operadores, eliminando o risco de
    injecao de comandos caso algum argumento venha de fonte externa.

    Args:
        args:    Lista [executavel, arg1, arg2, ...].
        timeout: Tempo maximo de espera em segundos (padrao: 15).

    Returns:
        Tupla (stdout, stderr, returncode). Em falha/timeout, returncode=1
        e stderr descreve o erro.
    """
    try:
        result = subprocess.run(
            args,
            shell=False,            # Nunca alterar para True — ver docstring
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        return '', f'Comando nao encontrado: {args[0]}', 1
    except subprocess.TimeoutExpired:
        return '', f'Timeout ao executar: {" ".join(args)}', 1
    except OSError as exc:
        return '', str(exc), 1


def run_powershell(script: str, timeout: int = 30) -> tuple[str, str, int]:
    """
    Executa um script PowerShell de forma segura e padronizada.

    Usa -NoProfile (nao carrega o perfil do usuario — mais rapido e previsivel)
    e -NonInteractive (nunca aguarda input). O script vai como argumento unico,
    sem interpretacao adicional pelo cmd.exe.

    Returns:
        Tupla (stdout, stderr, returncode), igual a run_cmd.
    """
    return run_cmd(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
        timeout=timeout,
    )


# ── findings ──────────────────────────────────────────────────────────────────

def finding(pilar: str, item: str, value, status: str, detail: str = '') -> dict:
    """
    Estrutura padronizada de um achado, usada pelos pilares acesso e logs.

    Args:
        pilar:  Pilar de origem ('acesso' | 'logs').
        item:   Identificador do achado.
        value:  Valor coletado (qualquer tipo serializavel em JSON).
        status: 'ok' | 'warning' | 'error' | 'info'.
        detail: Descricao opcional legivel.

    Returns:
        Dicionario com timestamp, pilar, item, value, status e detail.
    """
    return {
        'timestamp': now_iso(),
        'pilar':     pilar,
        'item':      item,
        'value':     value,
        'status':    status,
        'detail':    detail,
    }

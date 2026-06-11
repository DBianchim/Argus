#!/usr/bin/env python3
"""
queue_local.py — Fila local de payloads pendentes

Responsabilidade:
    Persistir payloads em disco quando o sistema central estiver
    indisponivel e reenvia-los automaticamente quando a conexao
    for restabelecida.

Funcionamento:
    - Cada payload e salvo como um arquivo JSON individual no diretorio
      configurado em config.toml -> [retry].queue_path
    - Os arquivos sao nomeados com timestamp + pilar para garantir
      ordenacao cronologica e identificacao rapida
    - O reenvio respeita a ordem cronologica (mais antigo primeiro)
    - Arquivos corrompidos sao descartados sem interromper o processo
    - Ao atingir o limite maximo, os registros mais antigos sao removidos

Formato do nome do arquivo:
    20250413_120000_operacional.json
    20250413_120500_backup.json

Autores: Equipe de Infraestrutura
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from core.config_loader import AgentConfig

logger = logging.getLogger(__name__)


# ── utilitarios internos ──────────────────────────────────────────────────────

def _queue_dir(config: AgentConfig) -> Path:
    path = Path(config.retry.queue_path)
    path.mkdir(parents=True, exist_ok=True)

    # Restringe a fila a apenas o usuario do processo (rwx------).
    # Os payloads podem conter dados de seguranca do servidor; nenhum outro
    # usuario deve le-los. No Windows, os.chmod nao aplica bits POSIX — o
    # except captura silenciosamente (as ACLs sao geridas pelo install script).
    try:
        os.chmod(path, 0o700)
    except (NotImplementedError, AttributeError, OSError) as e:
        logger.warning(
            'Nao foi possivel restringir permissoes da fila | path=%s | erro=%s',
            path, e,
        )

    return path


def _build_filename(pilar: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    return f'{timestamp}_{pilar}.json'


def _list_queue_files(queue_dir: Path) -> list[Path]:
    return sorted(queue_dir.glob('*.json'))


def _enforce_queue_limit(queue_dir: Path, max_files: int) -> None:
    files = _list_queue_files(queue_dir)
    excess = len(files) - max_files

    if excess <= 0:
        return

    for old_file in files[:excess]:
        try:
            old_file.unlink()
            logger.warning(
                'Limite da fila atingido — arquivo antigo removido | arquivo=%s',
                old_file.name
            )
        except OSError as e:
            logger.error(
                'Falha ao remover arquivo antigo da fila | arquivo=%s | erro=%s',
                old_file.name, e
            )


# ── funcoes publicas ──────────────────────────────────────────────────────────

def enqueue(payload: dict, config: AgentConfig) -> None:
    """
    Persiste um payload na fila local em disco.

    Args:
        payload: Dicionario com as metricas coletadas pelo agente.
        config:  Objeto AgentConfig com caminho e limite da fila.

    Raises:
        OSError: Se nao for possivel escrever no diretorio configurado.
    """
    queue_dir = _queue_dir(config)
    pilar     = payload.get('pilar', 'desconhecido')
    filename  = _build_filename(pilar)
    filepath  = queue_dir / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    logger.debug('Payload enfileirado | arquivo=%s', filename)

    _enforce_queue_limit(queue_dir, config.retry.queue_max_size)


def flush_queue(config: AgentConfig, send_fn) -> tuple[int, int]:
    """
    Reenvia todos os payloads pendentes na fila para o sistema central.

    Percorre os arquivos em ordem cronologica (mais antigo primeiro).
    Interrompe na primeira falha para nao sobrecarregar sistema em recuperacao.

    Args:
        config:  Objeto AgentConfig com configuracoes de retry e fila.
        send_fn: Funcao de envio com assinatura send_fn(payload, config).

    Returns:
        Tupla (enviados, falhas) com contagem de cada resultado.
    """
    from core.sender import SendStatus

    queue_dir = _queue_dir(config)
    files     = _list_queue_files(queue_dir)

    if not files:
        return 0, 0

    logger.info('Iniciando reenvio da fila | arquivos_pendentes=%d', len(files))

    sent   = 0
    failed = 0

    for filepath in files:

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(
                'Arquivo corrompido na fila — descartando | arquivo=%s | erro=%s',
                filepath.name, e
            )
            try:
                filepath.unlink()
            except OSError:
                pass
            continue

        result = send_fn(payload, config)

        if result.status == SendStatus.SUCCESS:
            sent += 1
            try:
                filepath.unlink()
                logger.debug('Arquivo removido da fila apos reenvio | arquivo=%s', filepath.name)
            except OSError as e:
                logger.error(
                    'Falha ao remover arquivo da fila apos reenvio | arquivo=%s | erro=%s',
                    filepath.name, e
                )
        else:
            failed += 1
            logger.warning(
                'Reenvio da fila interrompido — sistema central ainda indisponivel | '
                'enviados=%d | restantes=%d',
                sent, len(files) - sent
            )
            break

    logger.info('Reenvio da fila concluido | enviados=%d | falhas=%d', sent, failed)
    return sent, failed


def queue_size(config: AgentConfig) -> int:
    """Retorna o numero de payloads pendentes na fila local."""
    try:
        queue_dir = _queue_dir(config)
        return len(_list_queue_files(queue_dir))
    except OSError:
        return 0


def clear_queue(config: AgentConfig) -> int:
    """
    Remove todos os arquivos da fila local.

    Uso restrito a manutencao e testes.
    """
    queue_dir = _queue_dir(config)
    files     = _list_queue_files(queue_dir)
    removed   = 0

    for filepath in files:
        try:
            filepath.unlink()
            removed += 1
        except OSError as e:
            logger.error(
                'Falha ao remover arquivo da fila | arquivo=%s | erro=%s',
                filepath.name, e
            )

    logger.warning('Fila local limpa manualmente | arquivos_removidos=%d', removed)
    return removed

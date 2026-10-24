#!/usr/bin/env python3
"""
runner.py — Ponto de entrada principal do agente de monitoramento

Responsabilidade:
    Inicializar o sistema de logging, carregar e validar a configuracao,
    exibir o resumo de inicializacao e disparar o scheduler.

    Este e o UNICO arquivo que o operador executa diretamente.
    Todos os demais modulos sao inicializados por este arquivo.

Uso:
    Execucao direta:
        python runner.py
        python runner.py --config /caminho/personalizado/config.toml

    Como servico (gerenciado pelo install.sh / install.bat):
        systemctl start agent-monitor   (Linux)
        sc start agent-monitor          (Windows)

Autores: Equipe de Infraestrutura
"""

import argparse
import logging
import logging.handlers
import os
import platform
import sys
from pathlib import Path

from core import queue_local
import scheduler
from core.config_loader import load_config
from core.instance_lock import acquire_instance_lock
from core.sysutils import AGENT_VERSION, state_dir_error

# ── constantes ────────────────────────────────────────────────────────────────

# Fonte unica da versao: core/sysutils.py (mesma enviada nos payloads).
VERSION    = AGENT_VERSION
APP_NAME   = 'agent-monitor'
OS_FAMILY  = 'windows' if platform.system() == 'Windows' else 'linux'

_LOG_DIR = {
    'linux':   Path('/var/log/argus/agent-monitor'),
    'windows': Path('C:/ProgramData/Argus/agent-monitor/logs'),
}


# ── configuracao de logging ───────────────────────────────────────────────────

def _setup_logging(log_level: str, log_dir: Path | None = None) -> None:
    """
    Configura o sistema de logging com saida para console e arquivo rotativo.

    Formato padrao:
        2025-04-13 12:00:00 UTC | INFO     | scheduler | Ciclo #1 iniciado

    Rotacao de arquivo:
        - Tamanho maximo: 5 MB por arquivo
        - Retencao: ultimos 5 arquivos
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt='%(asctime)s UTC | %(levelname)-8s | %(name)-20s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    formatter.converter = __import__('time').gmtime

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    effective_log_dir = log_dir if log_dir is not None else _LOG_DIR.get(OS_FAMILY)

    if effective_log_dir:
        try:
            effective_log_dir.mkdir(parents=True, exist_ok=True)
            log_file = effective_log_dir / f'{APP_NAME}.log'

            file_handler = logging.handlers.RotatingFileHandler(
                filename    = log_file,
                maxBytes    = 5 * 1024 * 1024,  # 5 MB
                backupCount = 5,
                encoding    = 'utf-8',
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

            logging.getLogger(__name__).info(
                'Log em arquivo ativado | caminho=%s', log_file
            )
        except OSError as e:
            logging.getLogger(__name__).warning(
                'Nao foi possivel criar o arquivo de log | diretorio=%s | erro=%s',
                effective_log_dir, e
            )


# ── argparse ──────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog        = APP_NAME,
        description = 'Agente de monitoramento de infraestrutura',
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Exemplos:\n'
            '  python runner.py\n'
            '  python runner.py --config /etc/agent-monitor/config.toml\n'
            '  python runner.py --log-level DEBUG\n'
        )
    )

    parser.add_argument(
        '--config',
        type    = Path,
        default = None,
        metavar = 'CAMINHO',
        help    = 'Caminho para o config.toml (padrao: mesmo diretorio do runner.py)',
    )
    parser.add_argument(
        '--log-level',
        default = os.environ.get('AGENT_LOG_LEVEL', 'INFO'),
        choices = ['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        metavar = 'NIVEL',
        help    = 'Nivel de logging: DEBUG | INFO | WARNING | ERROR (padrao: INFO)',
    )
    parser.add_argument(
        '--dry-run',
        action  = 'store_true',
        default = False,
        help    = (
            'Executa a coleta sem enviar dados. Imprime os payloads com '
            'token mascarado e sai. Exit code 0 = todos OK, 1 = erros. '
            'Ideal para validar a instalacao em producao antes de ativar o envio.'
        ),
    )
    parser.add_argument(
        '--version',
        action  = 'version',
        version = f'{APP_NAME} {VERSION}',
    )

    return parser.parse_args()


# ── resumo de inicializacao ───────────────────────────────────────────────────

def _print_startup_summary(config, dry_run: bool = False) -> None:
    logger = logging.getLogger(__name__)

    masked  = config.global_._mask_token()
    pending = queue_local.queue_size(config)

    logger.info('=' * 60)
    logger.info('%s v%s iniciado', APP_NAME, VERSION)
    if dry_run:
        logger.info('*** MODO DRY-RUN — nenhum dado sera enviado ***')
    logger.info('=' * 60)
    logger.info('Sistema operacional : %s', OS_FAMILY)
    logger.info('Hostname            : %s', config.global_.hostname)
    logger.info('API URL             : %s', config.global_.api_url)
    logger.info('Token               : %s', masked)
    logger.info('Intervalo           : %ds', config.schedule.interval_seconds)
    logger.info('Retry max           : %d tentativas', config.retry.max_attempts)
    logger.info('Backoff             : %ds', config.retry.backoff_seconds)
    logger.info('Fila local          : %s', config.retry.queue_path)
    logger.info('Fila pendente       : %d arquivos', pending)
    logger.info('Agentes habilitados :')
    logger.info('  operacional       : %s', config.operacional.enabled)
    logger.info('  backup            : %s', config.backup.enabled)
    logger.info('  acesso            : %s', config.acesso.enabled)
    logger.info('  logs              : %s', config.logs.enabled)
    logger.info('=' * 60)


# ── ponto de entrada ──────────────────────────────────────────────────────────

def main() -> None:
    """
    Funcao principal — inicializa e executa o agente de monitoramento.

    Sequencia de inicializacao:
        1. Processa argumentos de linha de comando
        2. Configura o sistema de logging
        3. Carrega e valida o config.toml
        4. Exibe o resumo de inicializacao
        5. Garante instancia unica (trava) e avisa se a pasta de estado nao grava
        6. Dispara o scheduler (loop infinito)
    """
    args = _parse_args()

    _setup_logging(args.log_level)

    logger = logging.getLogger(__name__)
    logger.info('Iniciando %s v%s | python=%s | os=%s',
                APP_NAME, VERSION, sys.version.split()[0], OS_FAMILY)

    config = load_config(args.config)

    _print_startup_summary(config, dry_run=args.dry_run)

    if args.dry_run:
        exit_code = scheduler.run_dry(config)
        sys.exit(exit_code)

    # Fila e estado sao compartilhados: so um agente por host (encerra se ja houver outro)
    instance_lock = acquire_instance_lock(config.retry.queue_path)

    state_error = state_dir_error(config.retry.queue_path)
    if state_error:
        logger.warning('Pasta de estado nao gravavel: o estado do agente (estagnacao do '
                       'backup, cache de config) nao sera persistido | %s', state_error)

    scheduler.run(config)
    if instance_lock:
        instance_lock.release()

    logger.info('%s encerrado', APP_NAME)
    sys.exit(0)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
scheduler.py — Orquestrador do ciclo de coleta e envio

Responsabilidade:
    Executar o ciclo completo de monitoramento em loop continuo,
    respeitando o intervalo configurado e orquestrando a ordem
    correta das operacoes em cada ciclo.

Ordem de execucao por ciclo:
    1. Verificar e reenviar fila local pendente (flush_queue)
    2. Executar cada agente habilitado (collect)
    3. Enviar cada payload coletado (send_payload)
    4. Aguardar o intervalo configurado antes do proximo ciclo

Tolerancia a falhas:
    - Falha em um agente nao interrompe os demais
    - Falha de envio salva na fila local automaticamente
    - Excecoes inesperadas sao logadas e o ciclo continua
    - O scheduler nunca encerra por conta propria — apenas por
      sinal do sistema operacional (SIGTERM) ou KeyboardInterrupt

Autores: Equipe de Infraestrutura
"""

import logging
import signal
import time
from functools import partial
from typing import Callable

import agent_backup
import agent_operacional
import agent_acesso
import agent_logs
from core import central_config
from core import queue_local
from core import sender
from core.config_loader import AgentConfig, apply_central_config
from core.sender import SendStatus

logger = logging.getLogger(__name__)


# ── controle de ciclo de vida ─────────────────────────────────────────────────

class _ShutdownHandler:
    """
    Monitora sinais do sistema operacional para encerramento gracioso.

    Captura SIGTERM (enviado pelo systemd/sc.exe ao parar o servico)
    e SIGINT (Ctrl+C em execucao manual) para que o scheduler possa
    encerrar o loop apos o ciclo atual ser concluido.
    """

    def __init__(self):
        self.shutdown_requested = False
        signal.signal(signal.SIGTERM, self._handle)
        signal.signal(signal.SIGINT,  self._handle)

    def _handle(self, signum, frame):
        logger.info('Sinal de encerramento recebido (signal=%d) — aguardando fim do ciclo atual', signum)
        self.shutdown_requested = True


# ── execucao dos agentes ──────────────────────────────────────────────────────

def _run_agent(name: str, collect_fn: Callable, config: AgentConfig) -> dict | None:
    """
    Executa um agente de coleta de forma isolada.

    O isolamento garante que uma excecao em um agente nao interrompa
    a execucao dos demais no mesmo ciclo.

    Args:
        name:       Nome do agente para logging.
        collect_fn: Funcao collect(config) do agente.
        config:     Objeto AgentConfig para passar ao agente.

    Returns:
        Payload coletado como dicionario, ou None em caso de falha.
    """
    try:
        logger.debug('Iniciando coleta | agente=%s', name)
        payload = collect_fn(config)
        logger.debug('Coleta concluida | agente=%s', name)
        return payload
    except Exception as e:
        logger.error('Falha na coleta | agente=%s | erro=%s', name, e, exc_info=True)
        return None


def _send_agent_payload(payload: dict, config: AgentConfig) -> int | None:
    """
    Envia o payload de um agente usando sender com fila local como fallback.

    Returns:
        O config_version informado pela central na resposta (200), ou None.
    """
    queue_fn = partial(queue_local.enqueue, config=config)

    result = sender.send_payload(
        payload  = payload,
        config   = config,
        queue_fn = queue_fn,
    )

    pilar = payload.get('pilar', 'desconhecido')

    if result.status == SendStatus.SUCCESS:
        logger.info('Envio bem-sucedido | pilar=%s | tentativas=%d', pilar, result.attempts)

    elif result.status == SendStatus.QUEUED:
        pending = queue_local.queue_size(config)
        logger.warning(
            'Payload salvo na fila | pilar=%s | fila_pendente=%d arquivos',
            pilar, pending
        )

    elif result.status == SendStatus.DISCARDED:
        logger.error(
            'Payload descartado | pilar=%s | http=%s | detalhe=%s',
            pilar, result.http_code, result.detail
        )

    return result.config_version


# ── ciclo principal ───────────────────────────────────────────────────────────

def _build_agent_list(config: AgentConfig) -> list[tuple[str, Callable]]:
    """
    Monta a lista de agentes habilitados com base no config.toml.

    Apenas agentes com enabled=true sao incluidos.

    Args:
        config: Objeto AgentConfig com flags de habilitacao por agente.

    Returns:
        Lista de tuplas (nome, funcao_collect) para os agentes ativos.
    """
    agents = []

    if config.operacional.enabled:
        agents.append(('operacional', agent_operacional.collect))
        logger.debug('Agente habilitado: operacional')

    if config.backup.enabled:
        agents.append(('backup', agent_backup.collect))
        logger.debug('Agente habilitado: backup')

    if config.acesso.enabled:
        agents.append(('acesso', agent_acesso.collect))
        logger.debug('Agente habilitado: acesso')

    if config.logs.enabled:
        agents.append(('logs', agent_logs.collect))
        logger.debug('Agente habilitado: logs')

    return agents


def _run_cycle(agents: list[tuple[str, Callable]], config: AgentConfig) -> int | None:
    """
    Executa um ciclo completo de monitoramento.

    Um ciclo consiste em:
        1. Flush da fila local (reenvio de pendencias)
        2. Coleta de cada agente habilitado
        3. Envio de cada payload coletado

    Returns:
        O config_version mais recente visto nas respostas do ingest (ou None).
    """
    pending = queue_local.queue_size(config)
    if pending > 0:
        logger.info('Fila local com pendencias | arquivos=%d — iniciando reenvio', pending)
        send_fn = lambda payload, cfg: sender.send_payload(payload, cfg, queue_fn=None)
        enviados, falhas = queue_local.flush_queue(config, send_fn)
        logger.info('Flush concluido | enviados=%d | falhas=%d', enviados, falhas)

    seen_version: int | None = None
    for name, collect_fn in agents:
        payload = _run_agent(name, collect_fn, config)

        if payload is None:
            logger.warning('Ciclo ignorado para agente=%s — coleta retornou vazio', name)
            continue

        version = _send_agent_payload(payload, config)
        if version is not None:
            seen_version = version

    return seen_version


# ── sincronizacao de config com a central ─────────────────────────────────────

def _sync_from_central(config: AgentConfig) -> int | None:
    """
    Busca a config na central e aplica. Em falha, tenta o cache em disco.
    Retorna a versao aplicada (ou None se nada foi aplicado).
    """
    central, version = central_config.fetch_config(config)
    if central is not None:
        apply_central_config(config, central)
        central_config.save_cache(config, central, version)
        logger.info('Config aplicada da central | versao=%s', version)
        return version
    # Central indisponivel: usa o cache, se houver
    cached, cached_version = central_config.load_cache(config)
    if cached is not None:
        apply_central_config(config, cached)
        logger.info('Central indisponivel — config aplicada do cache | versao=%s',
                    cached_version)
        return cached_version
    logger.info('Sem config da central nem cache — usando config.toml local')
    return None


# ── funcao publica ────────────────────────────────────────────────────────────

def run(config: AgentConfig) -> None:
    """
    Inicia o loop principal do scheduler.

    Esta e a unica funcao que o runner.py deve chamar.
    O loop executa indefinidamente ate receber SIGTERM ou SIGINT.

    A config e gerenciada pela central: buscamos no inicio e re-sincronizamos
    quando a resposta do ingest indica um config_version novo (inclui o intervalo).

    Args:
        config: Objeto AgentConfig carregado e validado pelo runner.py (bootstrap).
    """
    shutdown = _ShutdownHandler()

    # Sync inicial: a central manda; cai para cache/toml se ela estiver fora.
    current_version = _sync_from_central(config)

    agents   = _build_agent_list(config)
    interval = config.schedule.interval_seconds

    if not agents:
        logger.error('Nenhum agente habilitado — encerrando')
        return

    logger.info(
        'Scheduler iniciado | agentes=%s | intervalo=%ds | config_version=%s',
        [name for name, _ in agents], interval, current_version
    )

    cycle = 0

    while not shutdown.shutdown_requested:
        cycle += 1
        cycle_start = time.monotonic()

        logger.info('Iniciando ciclo #%d', cycle)

        try:
            seen_version = _run_cycle(agents, config)
        except Exception as e:
            seen_version = None
            logger.critical(
                'Erro inesperado no ciclo #%d | erro=%s',
                cycle, e, exc_info=True
            )

        # A central sinalizou config nova? Rebaixa, aplica e atualiza intervalo/agentes.
        if seen_version is not None and seen_version != current_version:
            logger.info('Config mudou na central | versao %s -> %s — atualizando',
                        current_version, seen_version)
            central, version = central_config.fetch_config(config)
            if central is not None:
                apply_central_config(config, central)
                central_config.save_cache(config, central, version)
                current_version = version
                agents   = _build_agent_list(config)
                interval = config.schedule.interval_seconds
                logger.info(
                    'Config aplicada | versao=%s | intervalo=%ds | agentes=%s',
                    current_version, interval, [name for name, _ in agents]
                )
                if not agents:
                    logger.error('Config desabilitou todos os agentes — encerrando')
                    return

        elapsed  = time.monotonic() - cycle_start
        wait     = max(0.0, interval - elapsed)

        logger.info(
            'Ciclo #%d concluido | duracao=%.1fs | proximo_em=%.1fs',
            cycle, elapsed, wait
        )

        waited = 0.0
        while waited < wait and not shutdown.shutdown_requested:
            time.sleep(min(1.0, wait - waited))
            waited += 1.0

    logger.info('Scheduler encerrado graciosamente apos %d ciclos', cycle)


# ── modo dry-run ──────────────────────────────────────────────────────────────

def _dry_run_print_payload(name: str, payload: dict) -> None:
    """
    Imprime um payload no terminal de forma legivel, sem enviar nada.

    Mostra o envelope (timestamp, hostname, pilar) e um resumo das metricas.
    Para agentes com findings (acesso, logs) mostra a contagem por status;
    para os demais (operacional, backup) mostra os campos principais.
    """
    metrics = payload.get('metrics', {})

    print()
    print('+' + '-' * 58)
    print(f'| [DRY-RUN] agente={name}')
    print(f"|   timestamp : {payload.get('timestamp', '?')}")
    print(f"|   hostname  : {payload.get('hostname', '?')}")
    print(f"|   os_family : {payload.get('os_family', '?')}")
    print(f"|   pilar     : {payload.get('pilar', '?')}")

    if 'summary' in metrics:
        s     = metrics.get('summary', {})
        total = metrics.get('total_findings', '?')
        print(f"|   findings  : {total} total  "
              f"OK:{s.get('ok', 0)} WARN:{s.get('warning', 0)} "
              f"ERR:{s.get('error', 0)} INFO:{s.get('info', 0)}")
    elif 'backup' in metrics:
        bk = metrics.get('backup', {})
        print(f"|   backup    : status={bk.get('status', '?')} "
              f"age={bk.get('age_hours', '?')}h")
    else:
        cpu  = metrics.get('cpu', {})
        mem  = metrics.get('memory', {})
        disk = metrics.get('disk', [])
        svc  = metrics.get('services', [])
        print(f"|   cpu       : {cpu.get('usage_pct', '?')}%")
        print(f"|   memory    : {mem.get('usage_pct', '?')}%")
        print(f"|   disk      : {len(disk)} volume(s)")
        print(f"|   services  : {len(svc)} verificado(s)")

    print('+' + '-' * 58)


def run_dry(config: AgentConfig) -> int:
    """
    Executa um unico ciclo de coleta SEM enviar dados (modo dry-run).

    Chamado exclusivamente pelo runner.py quando --dry-run e passado.
    Nao chama sender.send_payload() nem queue_local.enqueue() — nada sai
    da maquina e a fila local nao e tocada.

    Returns:
        0 se todos os agentes coletaram sem findings de status='error'.
        1 se algum agente retornou None ou teve finding com status='error'.
    """
    logger.info('[DRY-RUN] Iniciando coleta de validacao (sem envio)')

    agents = _build_agent_list(config)
    if not agents:
        logger.error('[DRY-RUN] Nenhum agente habilitado — encerrando')
        return 1

    has_error = False

    for name, collect_fn in agents:
        payload = _run_agent(name, collect_fn, config)

        if payload is None:
            logger.error('[DRY-RUN] Falha na coleta | agente=%s | payload=None', name)
            has_error = True
            continue

        findings = payload.get('metrics', {}).get('findings', [])
        error_findings = [f for f in findings if f.get('status') == 'error']
        if error_findings:
            has_error = True
            logger.warning(
                '[DRY-RUN] %d finding(s) com status=error | agente=%s',
                len(error_findings), name
            )

        _dry_run_print_payload(name, payload)

    if has_error:
        logger.warning('[DRY-RUN] Coleta concluida COM ERROS — exit code 1')
        return 1

    logger.info('[DRY-RUN] Coleta concluida sem erros — exit code 0')
    return 0

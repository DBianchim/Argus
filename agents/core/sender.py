#!/usr/bin/env python3
"""
sender.py — Modulo de envio HTTP para o sistema central

Responsabilidade:
    Enviar payloads de metricas para a API central via HTTP POST,
    aplicando autenticacao por token, retry com backoff linear e
    encaminhamento para fila local em caso de falha definitiva.

Fluxo de envio:
    1. Tenta enviar o payload imediatamente
    2. Em caso de falha recuperavel (503, timeout), aguarda e tenta novamente
    3. Apos esgotar as tentativas, encaminha para queue_local.py
    4. Erros nao recuperaveis (401, 400) sao logados e descartados

Codigos HTTP e acoes:
    200  → sucesso, payload aceito pelo sistema central
    400  → payload invalido, NAO reenviar (problema nos dados)
    401  → token invalido, NAO reenviar (problema de configuracao)
    422  → formato incorreto, NAO reenviar (problema nos dados)
    503  → sistema indisponivel, salvar na fila local
    timeout → tratar como 503

Autores: Equipe de Infraestrutura
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum, auto

import requests
from requests.exceptions import ConnectionError, Timeout, RequestException

from core.config_loader import AgentConfig

logger = logging.getLogger(__name__)


# ── resultado do envio ────────────────────────────────────────────────────────

class SendStatus(Enum):
    """
    Resultado possivel de uma tentativa de envio.

        SUCCESS      → payload aceito, nenhuma acao adicional necessaria
        QUEUED       → falha recuperavel, payload salvo na fila local
        DISCARDED    → falha nao recuperavel, payload descartado
    """
    SUCCESS   = auto()
    QUEUED    = auto()
    DISCARDED = auto()


@dataclass
class SendResult:
    """
    Detalhe completo do resultado de um envio.

    Attributes:
        status:      Resultado final (SUCCESS | QUEUED | DISCARDED)
        http_code:   Codigo HTTP retornado pela API, ou None em caso de timeout
        attempts:    Numero de tentativas realizadas
        detail:      Mensagem descritiva para logging
    """
    status:    SendStatus
    http_code: int | None
    attempts:  int
    detail:    str


# Codigos HTTP que indicam problema nos dados/configuracao — nao reenviar
_NON_RETRYABLE_CODES = {400, 401, 403, 422}


# ── funcoes internas ──────────────────────────────────────────────────────────

def _build_headers(api_token: str) -> dict[str, str]:
    return {
        'Content-Type':  'application/json',
        'Authorization': f'Bearer {api_token}',
        'User-Agent':    'agent-monitor/1.0',
    }


def _mask_token(token: str) -> str:
    if len(token) <= 8:
        return '****'
    return f'{token[:4]}****{token[-4:]}'


def _is_retryable(exception: Exception | None, http_code: int | None) -> bool:
    if exception is not None:
        return isinstance(exception, (Timeout, ConnectionError))

    if http_code is not None:
        return http_code not in _NON_RETRYABLE_CODES and http_code != 200

    return False


def _attempt_send(
    url:        str,
    headers:    dict,
    payload:    dict,
    timeout:    int,
    verify:     bool | str,
) -> tuple[int | None, Exception | None]:
    """
    Realiza uma unica tentativa de envio HTTP POST.

    Args:
        verify: Validacao TLS. True = CAs padrao do sistema; caminho de arquivo
                PEM = valida contra essa CA (ex.: CA interna do Caddy). Nunca
                False — a validacao TLS permanece sempre ativa.

    Returns:
        Tupla (http_code, exception).
    """
    # X-Request-ID unico por tentativa — permite ao servidor correlacionar
    # retries e detectar duplicatas nos logs.
    attempt_headers = {**headers, 'X-Request-ID': str(uuid.uuid4())}

    try:
        response = requests.post(
            url=url,
            headers=attempt_headers,
            json=payload,
            timeout=timeout,
            verify=verify,   # True (CAs do sistema) ou caminho da CA interna;
                             # a validacao TLS nunca e desligada
        )
        return response.status_code, None

    except Timeout as e:
        return None, e
    except ConnectionError as e:
        return None, e
    except RequestException as e:
        return None, e


# ── funcao publica principal ──────────────────────────────────────────────────

def send_payload(payload: dict, config: AgentConfig, queue_fn=None) -> SendResult:
    """
    Envia um payload para a API central com retry e backoff linear.

    Politica de retry:
        Tentativa 1: imediata
        Tentativa 2: aguarda backoff_seconds * 1
        Tentativa 3: aguarda backoff_seconds * 2

    Apos esgotar as tentativas, chama queue_fn(payload) se disponivel.

    Args:
        payload:  Dicionario com as metricas coletadas pelo agente.
        config:   Objeto AgentConfig com URL, token e parametros de retry.
        queue_fn: Funcao opcional de enfileiramento local.

    Returns:
        SendResult com status, codigo HTTP, tentativas e mensagem.
    """
    url      = f'{config.global_.api_url}/api/v1/ingest'
    headers  = _build_headers(config.global_.api_token)
    timeout  = config.retry.http_timeout
    max_att  = config.retry.max_attempts
    backoff  = config.retry.backoff_seconds
    # CA interna (Caddy `tls internal`) quando configurada; senao CAs do sistema.
    verify   = config.global_.ca_cert or True
    pilar    = payload.get('pilar', 'desconhecido')
    hostname = payload.get('hostname', 'desconhecido')

    logger.debug(
        'Iniciando envio | pilar=%s | host=%s | token=%s | url=%s',
        pilar, hostname, _mask_token(config.global_.api_token), url
    )

    last_code:      int | None       = None
    last_exception: Exception | None = None

    for attempt in range(1, max_att + 1):

        if attempt > 1:
            wait = backoff * (attempt - 1)
            logger.warning(
                'Tentativa %d/%d | aguardando %ds antes de retentar | pilar=%s',
                attempt, max_att, wait, pilar
            )
            time.sleep(wait)

        http_code, exception = _attempt_send(url, headers, payload, timeout, verify)
        last_code      = http_code
        last_exception = exception

        if http_code == 200:
            logger.info(
                'Payload enviado com sucesso | pilar=%s | host=%s | tentativa=%d',
                pilar, hostname, attempt
            )
            return SendResult(
                status=SendStatus.SUCCESS,
                http_code=200,
                attempts=attempt,
                detail='Payload aceito pelo sistema central',
            )

        if http_code in _NON_RETRYABLE_CODES:
            logger.error(
                'Falha nao recuperavel | http=%d | pilar=%s | payload descartado',
                http_code, pilar
            )
            return SendResult(
                status=SendStatus.DISCARDED,
                http_code=http_code,
                attempts=attempt,
                detail=f'HTTP {http_code} — payload descartado (nao recuperavel)',
            )

        if exception:
            logger.warning(
                'Falha de conexao | tentativa=%d/%d | pilar=%s | erro=%s',
                attempt, max_att, pilar, type(exception).__name__
            )
        else:
            logger.warning(
                'Falha HTTP | tentativa=%d/%d | http=%s | pilar=%s',
                attempt, max_att, http_code, pilar
            )

    # Todas as tentativas esgotadas — encaminhar para fila local
    if queue_fn is not None:
        try:
            queue_fn(payload)
            logger.warning(
                'Payload salvo na fila local | pilar=%s | host=%s | tentativas=%d',
                pilar, hostname, max_att
            )
            return SendResult(
                status=SendStatus.QUEUED,
                http_code=last_code,
                attempts=max_att,
                detail='Sistema central indisponivel — payload salvo na fila local',
            )
        except Exception as e:
            logger.error(
                'Falha ao salvar na fila local | pilar=%s | erro=%s',
                pilar, str(e)
            )

    logger.error(
        'Payload descartado | pilar=%s | host=%s | tentativas=%d | ultimo_erro=%s',
        pilar, hostname, max_att,
        last_exception or f'HTTP {last_code}'
    )
    return SendResult(
        status=SendStatus.DISCARDED,
        http_code=last_code,
        attempts=max_att,
        detail='Tentativas esgotadas e sem fila local disponivel — payload descartado',
    )

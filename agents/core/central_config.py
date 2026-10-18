#!/usr/bin/env python3
"""
central_config.py — Sincronizacao da configuracao gerenciada pela central.

A central e dona da config de cada servidor (servicos criticos, caminhos de
backup, intervalo, pilares ligados, thresholds). O agente:

    1. No inicio, busca a config (`fetch_config`) e aplica.
    2. A cada ciclo, le o `config_version` da resposta do ingest; se mudou,
       rebaixa a config nova e aplica (ver scheduler.py).

Resiliencia: a config baixada e gravada em cache no disco (`config_cache.json`,
ao lado da fila local). Se a central estiver fora no boot, o agente usa o cache;
se nao houver cache, segue com os defaults do config.toml local.
"""

import json
import logging
import os

import requests

from core.config_loader import AgentConfig
from core.sysutils import state_file_path

logger = logging.getLogger(__name__)


def _cache_path(config: AgentConfig) -> str:
    """config_cache.json ao lado da pasta da fila local."""
    return state_file_path(config.retry.queue_path, 'config_cache.json')


def fetch_config(config: AgentConfig) -> tuple[dict | None, int | None]:
    """
    Busca a config do servidor em GET /api/v1/agent-config.

    Returns:
        (config_dict, version) em sucesso; (None, None) em qualquer falha
        (central fora, 401, corpo invalido) — nunca levanta.
    """
    url = f'{config.global_.api_url}/api/v1/agent-config'
    headers = {
        'Authorization': f'Bearer {config.global_.api_token}',
        'User-Agent': 'agent-monitor/1.0',
    }
    verify = config.global_.ca_cert or True
    try:
        r = requests.get(url, headers=headers,
                         timeout=config.retry.http_timeout, verify=verify)
        if r.status_code != 200:
            logger.warning('Falha ao buscar config da central | http=%s', r.status_code)
            return None, None
        data = r.json()
        return data.get('config'), data.get('config_version')
    except Exception as e:
        logger.warning('Falha ao buscar config da central | erro=%s', type(e).__name__)
        return None, None


def load_cache(config: AgentConfig) -> tuple[dict | None, int | None]:
    """Le a ultima config baixada do disco. (None, None) se ausente/invalida."""
    try:
        with open(_cache_path(config), encoding='utf-8') as f:
            data = json.load(f)
        return data.get('config'), data.get('config_version')
    except FileNotFoundError:
        return None, None
    except Exception as e:
        logger.warning('Cache de config invalido | erro=%s', type(e).__name__)
        return None, None


def save_cache(config: AgentConfig, central: dict, version: int | None) -> None:
    """Grava a config baixada em disco (best-effort)."""
    try:
        path = _cache_path(config)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'config': central, 'config_version': version}, f, ensure_ascii=False)
    except Exception as e:
        logger.warning('Falha ao gravar cache de config | erro=%s', type(e).__name__)

"""
rate_limit.py — Limite de taxa por IP para endpoints públicos/sensíveis

Usa slowapi com armazenamento em memória (por processo) — a central roda uma
única instância da API no docker-compose, então não há necessidade de um
backend compartilhado (Redis) para coordenar contadores entre processos.

Onde é aplicado:
    /install/*    — endpoints públicos e sem autenticação (bootstrap). Cada
                    requisição a /argus-agent.zip monta um zip em memória —
                    um alvo barato de flood. Limite apertado (poucas
                    instalações por minuto é o uso real).
    /api/v1/ingest — autenticado, mas o teto aqui é DELIBERADAMENTE generoso:
                    um agente que estava offline reenvia toda a fila local em
                    sequência ao reconectar (até 1000 payloads — ver
                    queue_max_size em agents/config.prod.toml). O limite é um
                    disjuntor contra flood/token comprometido, não um
                    throttle do uso normal — nunca deve barrar essa
                    recuperação, que é uma garantia central do projeto.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

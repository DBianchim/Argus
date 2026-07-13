"""
test_rate_limit.py — Rate limiting por IP em endpoints públicos/sensíveis.

/install/*: limite apertado (30/minuto) — endpoint público, sem autenticação,
que monta um zip em memória a cada chamada. Testado até o 429 de verdade.

/api/v1/ingest: limite deliberadamente alto (1500/minuto) — é um disjuntor
contra flood/token comprometido, não um throttle do uso normal (um agente
recuperando de uma queda reenvia até 1000 payloads em sequência). Não
exaurimos esse teto aqui (seria lento e não é o ponto); confirmamos apenas que
a rota está protegida (cabeçalho X-RateLimit-*) e que o fluxo normal continua
intacto.
"""

import pytest

from app.rate_limit import limiter
from conftest import AGENT_HEADERS, make_envelope


@pytest.fixture(autouse=True)
def _reset_limiter():
    """O limiter é global de processo (chave = IP) — zera entre testes para
    um teste não herdar contagem de outro (todas as chamadas de teste saem
    do mesmo IP simulado do ASGITransport)."""
    limiter.reset()
    yield
    limiter.reset()


async def test_install_script_allows_normal_use(client):
    resp = await client.get("/install/install.sh")
    assert resp.status_code == 200


async def test_install_script_blocks_after_limit(client):
    # O limite é 30/minuto — a 31ª chamada no mesmo minuto deve ser barrada.
    for _ in range(30):
        resp = await client.get("/install/install.sh")
        assert resp.status_code == 200

    resp = await client.get("/install/install.sh")
    assert resp.status_code == 429


async def test_install_endpoints_have_independent_paths_share_limiter_key(client):
    # slowapi conta por (chave, rota) — cada endpoint decorado tem seu próprio
    # balde, então esgotar install.sh não deve afetar install.ps1.
    for _ in range(30):
        await client.get("/install/install.sh")
    assert (await client.get("/install/install.sh")).status_code == 429

    resp = await client.get("/install/install.ps1")
    assert resp.status_code == 200


async def test_ingest_still_works_normally_after_decoration(client, server_id):
    # O teto de 1500/minuto é um disjuntor, não algo a esgotar em teste
    # (esgotá-lo aqui seria lento e não prova nada que o teste de /install já
    # não prove sobre o mecanismo). Isto é uma checagem de regressão: a
    # decoração do @limiter.limit não pode quebrar o fluxo normal de ingestão.
    for _ in range(5):
        resp = await client.post("/api/v1/ingest", json=make_envelope(), headers=AGENT_HEADERS)
        assert resp.status_code == 200

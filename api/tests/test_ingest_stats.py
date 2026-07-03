"""
test_ingest_stats.py — Instrumentação da ingestão (GET /api/v1/ingest/stats).

Verifica que cada POST /ingest é contabilizado, que as latências são medidas,
que o caminho de falha (503) incrementa total_failed, e que o endpoint exige
o token do dashboard (não é dado de agente).
"""

import pytest

from app import crud
from app.ingest_metrics import metrics as ingest_metrics
from conftest import AGENT_HEADERS, DASHBOARD_HEADERS, make_envelope


@pytest.fixture(autouse=True)
def _reset_metrics():
    """O singleton é global de processo — zera antes de cada teste isolar contagens."""
    ingest_metrics.reset()
    yield
    ingest_metrics.reset()


async def test_stats_requires_dashboard_token(client):
    assert (await client.get("/api/v1/ingest/stats")).status_code == 401
    # Token de agente não vale para consulta do dashboard.
    resp = await client.get("/api/v1/ingest/stats", headers=AGENT_HEADERS)
    assert resp.status_code == 401


async def test_stats_starts_zeroed(client):
    body = (await client.get("/api/v1/ingest/stats", headers=DASHBOARD_HEADERS)).json()
    assert body["total_received"] == 0
    assert body["total_persisted"] == 0
    assert body["total_failed"] == 0
    assert body["per_pilar"] == {}


async def test_stats_counts_successful_ingest(client, server_id):
    await client.post("/api/v1/ingest", json=make_envelope("operacional"), headers=AGENT_HEADERS)
    await client.post("/api/v1/ingest", json=make_envelope("backup"), headers=AGENT_HEADERS)
    await client.post("/api/v1/ingest", json=make_envelope("operacional"), headers=AGENT_HEADERS)

    body = (await client.get("/api/v1/ingest/stats", headers=DASHBOARD_HEADERS)).json()
    assert body["total_received"] == 3
    assert body["total_persisted"] == 3
    assert body["total_failed"] == 0
    assert body["per_pilar"] == {"operacional": 2, "backup": 1}
    # 3 payloads recém-persistidos caem na janela de vazão de 60s.
    assert body["throughput_per_min"] == 3
    assert body["sample_size"] == 3
    # Latência medida deve ser um número não-negativo.
    assert body["persist_ms_p95"] >= 0.0
    assert body["persist_ms_max"] >= body["persist_ms_p50"]


async def test_stats_ignores_rejected_payloads(client, server_id):
    # 422 (corpo inválido) nunca chega a persistir — não deve contar como recebido,
    # pois a instrumentação vive dentro do handler, após a validação Pydantic.
    bad = make_envelope()
    bad["metrics"] = {}
    assert (await client.post("/api/v1/ingest", json=bad, headers=AGENT_HEADERS)).status_code == 422

    body = (await client.get("/api/v1/ingest/stats", headers=DASHBOARD_HEADERS)).json()
    assert body["total_received"] == 0


async def test_stats_counts_persist_failure(client, server_id, monkeypatch):
    # Força a persistência a falhar → 503 e total_failed incrementado.
    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(crud, "insert_metric", boom)

    resp = await client.post("/api/v1/ingest", json=make_envelope(), headers=AGENT_HEADERS)
    assert resp.status_code == 503

    body = (await client.get("/api/v1/ingest/stats", headers=DASHBOARD_HEADERS)).json()
    assert body["total_received"] == 1
    assert body["total_persisted"] == 0
    assert body["total_failed"] == 1
    # Falhas não entram na amostra de latência de persistência.
    assert body["sample_size"] == 0

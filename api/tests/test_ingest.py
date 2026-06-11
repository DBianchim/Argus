"""
test_ingest.py — Contrato de ingestão (200 / 401 / 422) e persistência.

Cobre os códigos que o agente interpreta:
    200 → sucesso (exatamente 200)
    401 → token ausente/ inválido (agente descarta)
    422 → corpo inválido (agente descarta)
"""

from conftest import AGENT_HEADERS, DASHBOARD_HEADERS, make_envelope


async def test_ingest_success_returns_200(client, server_id):
    resp = await client.post("/api/v1/ingest", json=make_envelope(), headers=AGENT_HEADERS)
    assert resp.status_code == 200          # DEVE ser exatamente 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert isinstance(body["metric_id"], int)


async def test_ingest_persists_and_updates_last_seen(client, server_id):
    await client.post("/api/v1/ingest", json=make_envelope(), headers=AGENT_HEADERS)
    # O servidor passa a ter last_seen_at preenchido
    resp = await client.get("/api/v1/servers",
                            headers={"Authorization": "Bearer argus-dashboard-dev-token"})
    assert resp.status_code == 200
    server = next(s for s in resp.json() if s["id"] == server_id)
    assert server["last_seen_at"] is not None


async def test_ingest_missing_token_401(client, server_id):
    resp = await client.post("/api/v1/ingest", json=make_envelope())
    assert resp.status_code == 401


async def test_ingest_bad_token_401(client, server_id):
    resp = await client.post("/api/v1/ingest", json=make_envelope(),
                             headers={"Authorization": "Bearer token-errado"})
    assert resp.status_code == 401


async def test_ingest_invalid_pilar_422(client, server_id):
    envelope = make_envelope()
    envelope["pilar"] = "inexistente"
    resp = await client.post("/api/v1/ingest", json=envelope, headers=AGENT_HEADERS)
    assert resp.status_code == 422


async def test_ingest_empty_metrics_422(client, server_id):
    envelope = make_envelope()
    envelope["metrics"] = {}
    resp = await client.post("/api/v1/ingest", json=envelope, headers=AGENT_HEADERS)
    assert resp.status_code == 422


async def test_ingest_missing_field_422(client, server_id):
    envelope = make_envelope()
    del envelope["timestamp"]
    resp = await client.post("/api/v1/ingest", json=envelope, headers=AGENT_HEADERS)
    assert resp.status_code == 422


async def test_ingest_agent_version_persisted(client, server_id):
    envelope = make_envelope()
    envelope["agent_version"] = "1.0.0"
    resp = await client.post("/api/v1/ingest", json=envelope, headers=AGENT_HEADERS)
    assert resp.status_code == 200

    page = (await client.get("/api/v1/metrics", headers=DASHBOARD_HEADERS)).json()
    assert page["items"][0]["agent_version"] == "1.0.0"


async def test_ingest_without_agent_version_still_works(client, server_id):
    # Compatibilidade aditiva (CONTRATO.md): agentes antigos não enviam o campo —
    # a API deve aceitar (200) e armazenar NULL.
    envelope = make_envelope()
    assert "agent_version" not in envelope
    resp = await client.post("/api/v1/ingest", json=envelope, headers=AGENT_HEADERS)
    assert resp.status_code == 200

    page = (await client.get("/api/v1/metrics", headers=DASHBOARD_HEADERS)).json()
    assert page["items"][0]["agent_version"] is None

"""
test_queries.py — Consultas do dashboard: latest por pilar e histórico paginado.
"""

from conftest import AGENT_HEADERS, DASHBOARD_HEADERS, make_envelope


async def _ingest(client, **kw):
    resp = await client.post("/api/v1/ingest", json=make_envelope(**kw), headers=AGENT_HEADERS)
    assert resp.status_code == 200


async def test_latest_returns_one_per_pilar(client, server_id):
    # Dois 'operacional' (o mais recente deve vencer) + um 'backup'
    await _ingest(client, pilar="operacional", timestamp="2026-06-08T10:00:00Z")
    await _ingest(client, pilar="operacional", timestamp="2026-06-08T12:00:00Z")
    await _ingest(client, pilar="backup", timestamp="2026-06-08T11:00:00Z")

    resp = await client.get(f"/api/v1/servers/{server_id}/latest", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 200
    items = resp.json()
    pilares = {i["pilar"] for i in items}
    assert pilares == {"operacional", "backup"}     # 1 por pilar

    operacional = next(i for i in items if i["pilar"] == "operacional")
    assert operacional["collected_at"].startswith("2026-06-08T12:00:00")  # o mais recente


async def test_latest_unknown_server_404(client, server_id):
    resp = await client.get("/api/v1/servers/9999/latest", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 404


async def test_history_pagination_and_filter(client, server_id):
    for hour in range(5):
        await _ingest(client, pilar="operacional", timestamp=f"2026-06-08T0{hour}:00:00Z")
    await _ingest(client, pilar="backup", timestamp="2026-06-08T09:00:00Z")

    # Filtro por pilar
    resp = await client.get("/api/v1/metrics", params={"pilar": "operacional"},
                            headers=DASHBOARD_HEADERS)
    assert resp.status_code == 200
    page = resp.json()
    assert page["total"] == 5
    assert all(i["pilar"] == "operacional" for i in page["items"])

    # Paginação
    resp = await client.get("/api/v1/metrics",
                            params={"pilar": "operacional", "limit": 2, "offset": 0},
                            headers=DASHBOARD_HEADERS)
    page = resp.json()
    assert page["total"] == 5
    assert len(page["items"]) == 2
    # Ordenado por collected_at desc → o primeiro é o mais recente (04:00)
    assert page["items"][0]["collected_at"].startswith("2026-06-08T04:00:00")


async def test_servers_list_includes_registered(client, server_id):
    resp = await client.get("/api/v1/servers", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 200
    assert any(s["id"] == server_id for s in resp.json())

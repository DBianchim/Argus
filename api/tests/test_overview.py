"""
test_overview.py — Visão Geral: KPIs, status derivados pelo motor e alertas.
"""

import datetime

from sqlalchemy import update

from app.models import Server
from conftest import AGENT_HEADERS, DASHBOARD_HEADERS, make_envelope


async def _ingest(client, pilar: str, metrics: dict, **kw):
    envelope = make_envelope(pilar=pilar, **kw)
    envelope["metrics"] = metrics
    envelope["agent_version"] = "1.0.0"
    resp = await client.post("/api/v1/ingest", json=envelope, headers=AGENT_HEADERS)
    assert resp.status_code == 200


async def test_overview_crit_from_cpu(client, server_id):
    await _ingest(client, "operacional", {"cpu": {"usage_pct": 95.0}})
    await _ingest(client, "backup", {"backup": {"status": "OK"}})

    resp = await client.get("/api/v1/overview", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 200
    body = resp.json()

    assert body["kpis"]["servers_total"] == 1
    assert body["kpis"]["crit"] == 1
    assert body["kpis"]["backups_ok_pct"] == 100.0

    server = body["servers"][0]
    assert server["status"] == "crit"
    assert server["pilar_statuses"]["operacional"] == "crit"
    assert server["pilar_statuses"]["backup"] == "ok"
    assert server["pilar_statuses"]["acesso"] == "unknown"
    assert server["agent_version"] == "1.0.0"

    assert any(a["severity"] == "crit" and a["item"] == "cpu"
               for a in body["alerts"])


async def test_overview_offline_detection(client, server_id, session_factory):
    await _ingest(client, "operacional", {"cpu": {"usage_pct": 10.0}})

    # Simula servidor sem contato há 2h (limite: 600s)
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
    async with session_factory() as session:
        await session.execute(
            update(Server).where(Server.id == server_id).values(last_seen_at=past)
        )
        await session.commit()

    body = (await client.get("/api/v1/overview", headers=DASHBOARD_HEADERS)).json()
    assert body["servers"][0]["status"] == "offline"
    assert body["kpis"]["offline"] == 1
    assert body["kpis"]["online"] == 0
    assert any(a["item"] == "offline" for a in body["alerts"])


async def test_overview_server_never_seen_is_unknown(client, server_id):
    # Servidor registrado mas sem nenhum payload
    body = (await client.get("/api/v1/overview", headers=DASHBOARD_HEADERS)).json()
    assert body["servers"][0]["status"] == "unknown"
    assert body["kpis"]["backups_ok_pct"] is None


async def test_overview_operacional_summary_and_sparkline(client, server_id):
    await _ingest(
        client, "operacional",
        {
            "cpu": {"usage_pct": 30.0},
            "memory": {"usage_pct": 50.0},
            "disk": [{"mount": "/", "usage_pct": 40.0}, {"mount": "/data", "usage_pct": 65.0}],
            "uptime_seconds": 3600.0,
        },
        timestamp="2026-06-08T22:00:00Z",
    )
    await _ingest(
        client, "operacional",
        {
            "cpu": {"usage_pct": 46.0},
            "memory": {"usage_pct": 55.0},
            "disk": [{"mount": "/", "usage_pct": 41.0}, {"mount": "/data", "usage_pct": 66.0}],
            "uptime_seconds": 4200.0,
        },
        timestamp="2026-06-08T22:10:00Z",
    )

    body = (await client.get("/api/v1/overview", headers=DASHBOARD_HEADERS)).json()
    server = body["servers"][0]

    # Resumo vem do payload mais recente (22:10) — inclui o pior disco (66%).
    assert server["cpu_pct"] == 46.0
    assert server["mem_pct"] == 55.0
    assert server["disk_pct"] == 66.0
    assert server["uptime_seconds"] == 4200.0

    # Sparkline: as duas amostras, em ordem cronológica.
    assert server["cpu_history"] == [30.0, 46.0]


async def test_overview_operacional_summary_missing_when_no_data(client, server_id):
    body = (await client.get("/api/v1/overview", headers=DASHBOARD_HEADERS)).json()
    server = body["servers"][0]
    assert server["cpu_pct"] is None
    assert server["mem_pct"] is None
    assert server["disk_pct"] is None
    assert server["uptime_seconds"] is None
    assert server["cpu_history"] == []


async def test_overview_requires_auth(client):
    resp = await client.get("/api/v1/overview")
    assert resp.status_code == 401


async def test_server_health_endpoint(client, server_id):
    await _ingest(client, "backup", {"backup": {"status": "SLA_BREACH",
                                                "age_hours": 31, "sla_hours": 24}})

    resp = await client.get(f"/api/v1/servers/{server_id}/health",
                            headers=DASHBOARD_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "crit"
    assert body["pilar_statuses"]["backup"] == "crit"
    assert any("SLA" in a["title"] for a in body["alerts"])


async def test_server_health_404(client, server_id):
    resp = await client.get("/api/v1/servers/9999/health", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 404

"""
test_auth.py — Autenticação de agente (revogação) e de dashboard.
"""

from sqlalchemy import update

from app.models import Server
from conftest import AGENT_HEADERS, DASHBOARD_HEADERS, make_envelope


async def test_revoked_server_gets_401(client, server_id, session_factory):
    # Revoga o servidor → ingest passa a 401
    async with session_factory() as session:
        await session.execute(
            update(Server).where(Server.id == server_id).values(is_active=False)
        )
        await session.commit()

    resp = await client.post("/api/v1/ingest", json=make_envelope(), headers=AGENT_HEADERS)
    assert resp.status_code == 401


async def test_dashboard_requires_token(client):
    resp = await client.get("/api/v1/servers")
    assert resp.status_code == 401


async def test_dashboard_wrong_token_401(client):
    resp = await client.get("/api/v1/servers",
                            headers={"Authorization": "Bearer dashboard-errado"})
    assert resp.status_code == 401


async def test_dashboard_correct_token_200(client):
    resp = await client.get("/api/v1/servers", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_health_is_public_and_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

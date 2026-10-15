"""
test_server_registration.py — POST /api/v1/servers (registro via dashboard).
"""

from app.auth import hash_password
from app.models import User
from conftest import DASHBOARD_HEADERS


async def _create_user(session_factory, username, role) -> None:
    async with session_factory() as session:
        session.add(User(
            username=username, password_hash=hash_password("senha-forte-123"),
            display_name=username.capitalize(), role=role, is_active=True,
        ))
        await session.commit()


async def _login(client, username) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "senha-forte-123"}
    )
    return resp.json()["token"]


async def test_service_token_can_register_server(client):
    resp = await client.post(
        "/api/v1/servers",
        json={"hostname": "srv-novo-01", "os_family": "linux", "display_name": "Novo"},
        headers=DASHBOARD_HEADERS,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["server"]["hostname"] == "srv-novo-01"
    assert body["server"]["is_active"] is True
    assert len(body["token"]) > 20

    # O token devolvido autentica o ingest de verdade
    envelope = {
        "timestamp": "2026-07-17T10:00:00Z", "hostname": "srv-novo-01",
        "os_family": "linux", "pilar": "operacional", "metrics": {"cpu": {"usage_pct": 10}},
    }
    ingest = await client.post(
        "/api/v1/ingest", json=envelope,
        headers={"Authorization": f"Bearer {body['token']}"},
    )
    assert ingest.status_code == 200


async def test_operator_can_register_server(client, session_factory):
    await _create_user(session_factory, "op", "operator")
    token = await _login(client, "op")
    resp = await client.post(
        "/api/v1/servers",
        json={"hostname": "srv-op-01", "os_family": "windows", "display_name": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201


async def test_viewer_cannot_register_server(client, session_factory):
    await _create_user(session_factory, "view", "viewer")
    token = await _login(client, "view")
    resp = await client.post(
        "/api/v1/servers",
        json={"hostname": "srv-viewer-01", "os_family": "linux", "display_name": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_registered_server_appears_in_list(client):
    await client.post(
        "/api/v1/servers",
        json={"hostname": "srv-list-01", "os_family": "linux", "display_name": None},
        headers=DASHBOARD_HEADERS,
    )
    resp = await client.get("/api/v1/servers", headers=DASHBOARD_HEADERS)
    hostnames = {s["hostname"] for s in resp.json()}
    assert "srv-list-01" in hostnames

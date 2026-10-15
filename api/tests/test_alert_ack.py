"""
test_alert_ack.py — Reconhecimento de alertas (Tela de Alertas / Detalhe de Servidor).
"""

from app.auth import hash_password
from app.models import User
from conftest import AGENT_HEADERS, DASHBOARD_HEADERS, make_envelope

PASSWORD = "senha-forte-123"


async def _create_user(session_factory, username="david", role="admin", display_name=None) -> None:
    async with session_factory() as session:
        session.add(User(
            username=username, password_hash=hash_password(PASSWORD),
            display_name=display_name or username.capitalize(), role=role, is_active=True,
        ))
        await session.commit()


async def _login(client, username="david") -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    return resp.json()["token"]


async def _ingest_crit_cpu(client, server_id):
    envelope = make_envelope(pilar="operacional")
    envelope["metrics"] = {"cpu": {"usage_pct": 95.0}}
    resp = await client.post("/api/v1/ingest", json=envelope, headers=AGENT_HEADERS)
    assert resp.status_code == 200


async def test_alert_starts_unacked(client, server_id):
    await _ingest_crit_cpu(client, server_id)
    body = (await client.get("/api/v1/overview", headers=DASHBOARD_HEADERS)).json()
    alert = next(a for a in body["alerts"] if a["item"] == "cpu")
    assert alert["acked_by"] is None
    assert alert["acked_at"] is None


async def test_ack_marks_alert_and_survives_refetch(client, session_factory, server_id):
    await _create_user(session_factory)
    token = await _login(client)
    await _ingest_crit_cpu(client, server_id)

    resp = await client.post(
        f"/api/v1/servers/{server_id}/alerts/ack",
        json={"pilar": "operacional", "item": "cpu"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["acked_by"] == "David"

    body = (await client.get("/api/v1/overview", headers=DASHBOARD_HEADERS)).json()
    alert = next(a for a in body["alerts"] if a["item"] == "cpu")
    assert alert["acked_by"] == "David"
    assert alert["acked_at"] is not None

    # Também reflete no health do servidor específico
    health = (await client.get(
        f"/api/v1/servers/{server_id}/health", headers=DASHBOARD_HEADERS
    )).json()
    h_alert = next(a for a in health["alerts"] if a["item"] == "cpu")
    assert h_alert["acked_by"] == "David"


async def test_ack_requires_user_session_not_service_token(client, server_id):
    await _ingest_crit_cpu(client, server_id)
    resp = await client.post(
        f"/api/v1/servers/{server_id}/alerts/ack",
        json={"pilar": "operacional", "item": "cpu"},
        headers=DASHBOARD_HEADERS,
    )
    assert resp.status_code == 401


async def test_ack_unknown_server_404(client, session_factory):
    await _create_user(session_factory)
    token = await _login(client)
    resp = await client.post(
        "/api/v1/servers/9999/alerts/ack",
        json={"pilar": "operacional", "item": "cpu"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_reack_updates_acked_by(client, session_factory, server_id):
    await _create_user(session_factory, username="david")
    await _create_user(session_factory, username="maria")
    await _ingest_crit_cpu(client, server_id)

    david_token = await _login(client, "david")
    maria_token = await _login(client, "maria")

    await client.post(
        f"/api/v1/servers/{server_id}/alerts/ack",
        json={"pilar": "operacional", "item": "cpu"},
        headers={"Authorization": f"Bearer {david_token}"},
    )
    resp = await client.post(
        f"/api/v1/servers/{server_id}/alerts/ack",
        json={"pilar": "operacional", "item": "cpu"},
        headers={"Authorization": f"Bearer {maria_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["acked_by"] == "Maria"  # o reconhecimento mais recente vence

    body = (await client.get("/api/v1/overview", headers=DASHBOARD_HEADERS)).json()
    alert = next(a for a in body["alerts"] if a["item"] == "cpu")
    assert alert["acked_by"] == "Maria"

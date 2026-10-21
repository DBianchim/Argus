"""
test_notifications.py — Transições de estado e registro de alertas.
"""

import datetime

from sqlalchemy import func, select

from app.analysis import Status
from app.config import settings
from app.main import check_offline
from app.models import NotificationLog, Server
from app.notifications import should_notify
from conftest import AGENT_HEADERS, DASHBOARD_HEADERS, make_envelope


# ── lógica pura de transição ──────────────────────────────────────────────────

def test_should_notify_transitions():
    assert should_notify(None, Status.OK) is None
    assert should_notify(None, Status.CRIT) == "crit"
    assert should_notify(Status.OK, Status.WARN) == "warn"
    assert should_notify(Status.OK, Status.CRIT) == "crit"
    assert should_notify(Status.WARN, Status.CRIT) == "crit"
    assert should_notify(Status.OK, Status.OFFLINE) == "crit"
    assert should_notify(Status.CRIT, Status.OK) == "info"     # recuperação
    assert should_notify(Status.WARN, Status.OK) == "info"
    assert should_notify(Status.CRIT, Status.CRIT) is None     # estável
    assert should_notify(Status.OK, Status.OK) is None
    assert should_notify(Status.UNKNOWN, Status.OK) is None    # nascer com dados


# ── integração via ingest ─────────────────────────────────────────────────────

async def _ingest(client, pilar, metrics):
    envelope = make_envelope(pilar=pilar)
    envelope["metrics"] = metrics
    resp = await client.post("/api/v1/ingest", json=envelope, headers=AGENT_HEADERS)
    assert resp.status_code == 200


async def _count(session_factory) -> int:
    async with session_factory() as session:
        return (await session.execute(
            select(func.count()).select_from(NotificationLog)
        )).scalar_one()


async def test_transition_records_one_notification(client, server_id, session_factory):
    # Primeiro payload já crítico → 1 notificação
    await _ingest(client, "operacional", {"cpu": {"usage_pct": 95.0}})
    assert await _count(session_factory) == 1

    # Reingestão estável (continua crítico) → NÃO duplica
    await _ingest(client, "operacional", {"cpu": {"usage_pct": 96.0}})
    assert await _count(session_factory) == 1


async def test_recovery_generates_info_notification(client, server_id, session_factory):
    await _ingest(client, "operacional", {"cpu": {"usage_pct": 95.0}})   # crit
    await _ingest(client, "operacional", {"cpu": {"usage_pct": 10.0}})   # → ok

    async with session_factory() as session:
        rows = (await session.execute(
            select(NotificationLog).order_by(NotificationLog.id)
        )).scalars().all()
    assert len(rows) == 2
    assert rows[0].severity == "crit" and rows[0].status_to == "crit"
    assert rows[1].severity == "info" and rows[1].status_to == "ok"


async def test_offline_check_does_not_reset_online_server_status(client, server_id, session_factory):
    # Servidor online e crítico: o loop de offline não pode rebaixá-lo a UNKNOWN,
    # senão cada novo payload geraria outra notificação "ficou CRÍTICO".
    await _ingest(client, "operacional", {"cpu": {"usage_pct": 95.0}})
    assert await _count(session_factory) == 1

    now = datetime.datetime.now(datetime.timezone.utc)
    async with session_factory() as session:
        await check_offline(session, now)
    await _ingest(client, "operacional", {"cpu": {"usage_pct": 96.0}})

    assert await _count(session_factory) == 1
    async with session_factory() as session:
        assert (await session.get(Server, server_id)).last_status == "crit"


async def test_offline_check_marks_silent_server_offline(client, server_id, session_factory):
    await _ingest(client, "operacional", {"cpu": {"usage_pct": 10.0}})

    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=settings.offline_after_seconds + 60)
    async with session_factory() as session:
        await check_offline(session, later)
        assert (await session.get(Server, server_id)).last_status == "offline"


async def test_notifications_endpoint_and_since_id(client, server_id):
    await _ingest(client, "operacional", {"cpu": {"usage_pct": 95.0}})

    page = (await client.get("/api/v1/notifications", headers=DASHBOARD_HEADERS)).json()
    assert len(page["items"]) == 1
    first_id = page["items"][0]["id"]
    assert page["items"][0]["status_to"] == "crit"

    # since_id = id atual → nada novo
    empty = (await client.get(
        f"/api/v1/notifications?since_id={first_id}", headers=DASHBOARD_HEADERS
    )).json()
    assert empty["items"] == []


async def test_notifications_requires_auth(client):
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 401


async def test_ingest_still_200_even_if_notify_path_runs(client, server_id):
    # Garante que o hook de notificação não altera o contrato (200) do ingest
    resp = await client.post(
        "/api/v1/ingest",
        json=make_envelope(pilar="backup"),
        headers=AGENT_HEADERS,
    )
    assert resp.status_code == 200

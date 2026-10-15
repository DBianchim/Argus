"""
test_auth_users.py — Entrada do usuário: login, sessões, logout, revogação.
"""

import datetime

from sqlalchemy import update

from app.auth import hash_password, hash_token
from app.models import User, UserSession
from conftest import DASHBOARD_HEADERS

PASSWORD = "senha-forte-123"


async def _create_user(session_factory, username="david", password=PASSWORD,
                       active=True) -> int:
    async with session_factory() as session:
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name="David",
            is_active=active,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _login(client, username="david", password=PASSWORD):
    return await client.post("/api/v1/auth/login",
                             json={"username": username, "password": password})


# ── login ─────────────────────────────────────────────────────────────────────

async def test_login_success_returns_session(client, session_factory):
    await _create_user(session_factory)
    resp = await _login(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["user"]["username"] == "david"


async def test_login_wrong_password_generic_401(client, session_factory):
    await _create_user(session_factory)
    resp = await _login(client, password="errada")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Credenciais inválidas"


async def test_login_unknown_user_same_generic_message(client, session_factory):
    # Mensagem idêntica à de senha errada — não revela se o usuário existe
    resp = await _login(client, username="nao-existe")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Credenciais inválidas"


async def test_login_inactive_user_401(client, session_factory):
    await _create_user(session_factory, active=False)
    resp = await _login(client)
    assert resp.status_code == 401


# ── sessões ───────────────────────────────────────────────────────────────────

async def test_session_token_grants_dashboard_access(client, session_factory):
    await _create_user(session_factory)
    token = (await _login(client)).json()["token"]
    resp = await client.get("/api/v1/servers",
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


async def test_me_returns_logged_user(client, session_factory):
    await _create_user(session_factory)
    token = (await _login(client)).json()["token"]
    resp = await client.get("/api/v1/auth/me",
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "david"


async def test_me_rejects_service_token(client):
    # O token de serviço não é uma pessoa — /me exige sessão
    resp = await client.get("/api/v1/auth/me", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 401


async def test_logout_revokes_session(client, session_factory):
    await _create_user(session_factory)
    token = (await _login(client)).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 200
    resp = await client.get("/api/v1/servers", headers=headers)
    assert resp.status_code == 401


async def test_expired_session_401(client, session_factory):
    user_id = await _create_user(session_factory)
    token = "token-expirado-de-teste"
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    async with session_factory() as session:
        session.add(UserSession(
            token_hash=hash_token(token), user_id=user_id, expires_at=past
        ))
        await session.commit()

    resp = await client.get("/api/v1/servers",
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_deactivated_user_invalidates_existing_session(client, session_factory):
    await _create_user(session_factory)
    token = (await _login(client)).json()["token"]
    async with session_factory() as session:
        await session.execute(
            update(User).where(User.username == "david").values(is_active=False)
        )
        await session.commit()

    resp = await client.get("/api/v1/servers",
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_patch_me_updates_own_display_name(client, session_factory):
    await _create_user(session_factory)
    token = (await _login(client)).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.patch(
        "/api/v1/auth/me", json={"display_name": "Novo Nome"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Novo Nome"

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["display_name"] == "Novo Nome"


async def test_patch_me_rejects_service_token(client):
    resp = await client.patch(
        "/api/v1/auth/me", json={"display_name": "X"}, headers=DASHBOARD_HEADERS
    )
    assert resp.status_code == 401


async def test_service_token_still_works(client):
    # Compatibilidade: o DASHBOARD_TOKEN segue válido para integrações
    resp = await client.get("/api/v1/servers", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 200

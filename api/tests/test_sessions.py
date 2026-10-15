"""
test_sessions.py — GET/DELETE /api/v1/auth/sessions (Minha conta → Sessões ativas).
"""

from app.auth import hash_password
from app.models import User

PASSWORD = "senha-forte-123"


async def _create_user(session_factory, username="david") -> None:
    async with session_factory() as session:
        session.add(User(
            username=username, password_hash=hash_password(PASSWORD),
            display_name=username.capitalize(), role="admin", is_active=True,
        ))
        await session.commit()


async def _login(client, username="david") -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    return resp.json()["token"]


async def test_lists_only_current_session(client, session_factory):
    await _create_user(session_factory)
    token = await _login(client)
    resp = await client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1
    assert sessions[0]["is_current"] is True


async def test_lists_multiple_sessions_flags_current(client, session_factory):
    await _create_user(session_factory)
    token_a = await _login(client)
    token_b = await _login(client)  # segundo login → segunda sessão

    resp = await client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token_b}"}
    )
    sessions = resp.json()
    assert len(sessions) == 2
    current = [s for s in sessions if s["is_current"]]
    assert len(current) == 1

    # Do ponto de vista da sessão A, é ELA que é a atual
    resp_a = await client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token_a}"}
    )
    ids_current_a = {s["id"] for s in resp_a.json() if s["is_current"]}
    ids_current_b = {s["id"] for s in sessions if s["is_current"]}
    assert ids_current_a != ids_current_b


async def test_revoke_session_removes_it_from_list(client, session_factory):
    await _create_user(session_factory)
    token_a = await _login(client)
    token_b = await _login(client)

    sessions = (await client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token_a}"}
    )).json()
    other = next(s for s in sessions if not s["is_current"])

    resp = await client.delete(
        f"/api/v1/auth/sessions/{other['id']}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 204

    # A sessão revogada não autentica mais
    check = await client.get(
        "/api/v1/servers", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert check.status_code == 401

    remaining = (await client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token_a}"}
    )).json()
    assert len(remaining) == 1


async def test_cannot_revoke_another_users_session(client, session_factory):
    await _create_user(session_factory, "david")
    await _create_user(session_factory, "maria")
    david_token = await _login(client, "david")
    maria_token = await _login(client, "maria")

    maria_sessions = (await client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {maria_token}"}
    )).json()
    real_maria_id = maria_sessions[0]["id"]

    # David tenta revogar uma sessão da Maria — 404 (não pertence a ele)
    resp = await client.delete(
        f"/api/v1/auth/sessions/{real_maria_id}",
        headers={"Authorization": f"Bearer {david_token}"},
    )
    assert resp.status_code == 404

    # Confere que a sessão da Maria continua válida
    still_valid = await client.get(
        "/api/v1/servers", headers={"Authorization": f"Bearer {maria_token}"}
    )
    assert still_valid.status_code == 200

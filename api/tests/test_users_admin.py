"""
test_users_admin.py — Gerenciamento de usuários e permissões (papéis).

Cobre: CRUD de usuários (admin), gating por papel nos endpoints de servidores,
proteção do último admin, troca de senha (self-service) e reset (admin).
"""

from app.auth import hash_password
from app.models import Server, User
from conftest import DASHBOARD_HEADERS

PASSWORD = "senha-forte-123"


async def _create_user(session_factory, username, role, password=PASSWORD, active=True) -> int:
    async with session_factory() as session:
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name=username.title(),
            role=role,
            is_active=active,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _login(client, username, password=PASSWORD):
    resp = await client.post("/api/v1/auth/login",
                             json={"username": username, "password": password})
    return resp.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── CRUD de usuarios (admin) ───────────────────────────────────────────────────

async def test_admin_can_list_users(client, session_factory):
    await _create_user(session_factory, "admin1", "admin")
    resp = await client.get("/api/v1/users", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 200
    assert any(u["username"] == "admin1" for u in resp.json())


async def test_admin_can_create_user(client, session_factory):
    await _create_user(session_factory, "admin1", "admin")
    resp = await client.post("/api/v1/users", headers=DASHBOARD_HEADERS, json={
        "username": "novo", "password": "outra-senha-123", "role": "viewer",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "novo"
    assert body["role"] == "viewer"
    assert body["is_active"] is True


async def test_create_user_duplicate_username_409(client, session_factory):
    await _create_user(session_factory, "dup", "admin")
    resp = await client.post("/api/v1/users", headers=DASHBOARD_HEADERS, json={
        "username": "dup", "password": "outra-senha-123", "role": "viewer",
    })
    assert resp.status_code == 409


async def test_operator_cannot_manage_users_403(client, session_factory):
    await _create_user(session_factory, "op1", "operator")
    token = await _login(client, "op1")
    resp = await client.get("/api/v1/users", headers=_auth(token))
    assert resp.status_code == 403


async def test_viewer_cannot_manage_users_403(client, session_factory):
    await _create_user(session_factory, "view1", "viewer")
    token = await _login(client, "view1")
    resp = await client.post("/api/v1/users", headers=_auth(token), json={
        "username": "x", "password": "outra-senha-123", "role": "viewer",
    })
    assert resp.status_code == 403


async def test_admin_can_patch_user_role(client, session_factory):
    await _create_user(session_factory, "admin1", "admin")
    target_id = await _create_user(session_factory, "target", "viewer")
    resp = await client.patch(f"/api/v1/users/{target_id}", headers=DASHBOARD_HEADERS,
                              json={"role": "operator"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "operator"


async def test_admin_can_deactivate_user(client, session_factory):
    await _create_user(session_factory, "admin1", "admin")
    target_id = await _create_user(session_factory, "target", "viewer")
    resp = await client.patch(f"/api/v1/users/{target_id}", headers=DASHBOARD_HEADERS,
                              json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


async def test_admin_can_delete_user(client, session_factory):
    await _create_user(session_factory, "admin1", "admin")
    target_id = await _create_user(session_factory, "target", "viewer")
    resp = await client.delete(f"/api/v1/users/{target_id}", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 204
    resp = await client.get("/api/v1/users", headers=DASHBOARD_HEADERS)
    assert all(u["id"] != target_id for u in resp.json())


# ── protecao do ultimo admin ───────────────────────────────────────────────────

async def test_cannot_demote_last_active_admin(client, session_factory):
    admin_id = await _create_user(session_factory, "solo-admin", "admin")
    resp = await client.patch(f"/api/v1/users/{admin_id}", headers=DASHBOARD_HEADERS,
                              json={"role": "viewer"})
    assert resp.status_code == 409


async def test_cannot_deactivate_last_active_admin(client, session_factory):
    admin_id = await _create_user(session_factory, "solo-admin", "admin")
    resp = await client.patch(f"/api/v1/users/{admin_id}", headers=DASHBOARD_HEADERS,
                              json={"is_active": False})
    assert resp.status_code == 409


async def test_cannot_delete_last_active_admin(client, session_factory):
    admin_id = await _create_user(session_factory, "solo-admin", "admin")
    resp = await client.delete(f"/api/v1/users/{admin_id}", headers=DASHBOARD_HEADERS)
    assert resp.status_code == 409


async def test_can_demote_admin_when_another_admin_remains(client, session_factory):
    await _create_user(session_factory, "admin1", "admin")
    admin2_id = await _create_user(session_factory, "admin2", "admin")
    resp = await client.patch(f"/api/v1/users/{admin2_id}", headers=DASHBOARD_HEADERS,
                              json={"role": "viewer"})
    assert resp.status_code == 200


# ── gating por papel nos endpoints de servidores ──────────────────────────────

async def _make_server(session_factory) -> int:
    async with session_factory() as session:
        server = Server(hostname="srv-1", os_family="linux",
                        api_token_hash="x" * 64, is_active=True)
        session.add(server)
        await session.commit()
        await session.refresh(server)
        return server.id


async def test_viewer_can_read_servers(client, session_factory):
    await _create_user(session_factory, "view1", "viewer")
    await _make_server(session_factory)
    token = await _login(client, "view1")
    resp = await client.get("/api/v1/servers", headers=_auth(token))
    assert resp.status_code == 200


async def test_viewer_cannot_patch_server_403(client, session_factory):
    await _create_user(session_factory, "view1", "viewer")
    server_id = await _make_server(session_factory)
    token = await _login(client, "view1")
    resp = await client.patch(f"/api/v1/servers/{server_id}", headers=_auth(token),
                              json={"display_name": "novo"})
    assert resp.status_code == 403


async def test_operator_can_patch_server(client, session_factory):
    await _create_user(session_factory, "op1", "operator")
    server_id = await _make_server(session_factory)
    token = await _login(client, "op1")
    resp = await client.patch(f"/api/v1/servers/{server_id}", headers=_auth(token),
                              json={"display_name": "novo"})
    assert resp.status_code == 200


async def test_viewer_cannot_delete_server_403(client, session_factory):
    await _create_user(session_factory, "view1", "viewer")
    server_id = await _make_server(session_factory)
    token = await _login(client, "view1")
    resp = await client.delete(f"/api/v1/servers/{server_id}", headers=_auth(token))
    assert resp.status_code == 403


async def test_service_token_still_manages_servers(client, session_factory):
    server_id = await _make_server(session_factory)
    resp = await client.patch(f"/api/v1/servers/{server_id}", headers=DASHBOARD_HEADERS,
                              json={"display_name": "novo"})
    assert resp.status_code == 200


# ── senha: reset (admin) e troca (self-service) ───────────────────────────────

async def test_admin_can_reset_password(client, session_factory):
    await _create_user(session_factory, "admin1", "admin")
    target_id = await _create_user(session_factory, "target", "viewer")
    resp = await client.post(f"/api/v1/users/{target_id}/reset-password",
                             headers=DASHBOARD_HEADERS,
                             json={"new_password": "nova-senha-456"})
    assert resp.status_code == 204

    login_resp = await client.post("/api/v1/auth/login",
                                   json={"username": "target", "password": "nova-senha-456"})
    assert login_resp.status_code == 200


async def test_self_change_password_wrong_current_401(client, session_factory):
    await _create_user(session_factory, "user1", "viewer")
    token = await _login(client, "user1")
    resp = await client.post("/api/v1/auth/change-password", headers=_auth(token),
                             json={"current_password": "errada", "new_password": "outra-nova-123"})
    assert resp.status_code == 401


async def test_self_change_password_success_and_revokes_other_sessions(client, session_factory):
    await _create_user(session_factory, "user1", "viewer")
    token_a = await _login(client, "user1")
    token_b = await _login(client, "user1")

    resp = await client.post("/api/v1/auth/change-password", headers=_auth(token_a),
                             json={"current_password": PASSWORD, "new_password": "outra-nova-123"})
    assert resp.status_code == 200
    new_token = resp.json()["token"]

    # sessao B (antiga) foi revogada
    resp_b = await client.get("/api/v1/servers", headers=_auth(token_b))
    assert resp_b.status_code == 401

    # a nova sessao emitida na troca funciona
    resp_new = await client.get("/api/v1/servers", headers=_auth(new_token))
    assert resp_new.status_code == 200

    # login com a senha nova funciona
    login_resp = await client.post("/api/v1/auth/login",
                                   json={"username": "user1", "password": "outra-nova-123"})
    assert login_resp.status_code == 200

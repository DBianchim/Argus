#!/usr/bin/env python3
"""
manage.py — CLI administrativa da API Argus

Comandos:
    create-server   — registra um servidor e gera o token (exibido UMA vez)
    list-servers    — lista os servidores registrados
    revoke-server   — desativa um servidor (is_active=false → ingest passa a 401)
    create-user     — cria um usuário do dashboard (senha via prompt seguro)
    list-users      — lista os usuários
    deactivate-user — desativa um usuário (login passa a falhar)
    set-role        — muda o papel de um usuário (admin/operator/viewer)

Papéis (permissões):
    admin    — gerencia usuários e servidores (tudo)
    operator — edita/remove servidores e config, mas não gerencia usuários
    viewer   — somente leitura

Uso (a partir de api/):
    python manage.py create-server --hostname DESKTOP --os windows
    python manage.py create-user --username david --role admin
    python manage.py list-users
    python manage.py set-role --username david --role operator
"""

import argparse
import asyncio
import getpass

from sqlalchemy import select, update

from app import crud
from app.auth import hash_password
from app.database import SessionLocal
from app.models import Server, User


async def _create_server(hostname: str, os_family: str, display_name: str | None) -> None:
    async with SessionLocal() as session:
        server, token = await crud.create_server(
            session, hostname=hostname, os_family=os_family, display_name=display_name,
        )
        server_id = server.id

    print("Servidor registrado com sucesso:")
    print(f"  id       : {server_id}")
    print(f"  hostname : {hostname}")
    print(f"  os       : {os_family}")
    print()
    print("  TOKEN (copie agora — NAO sera exibido novamente):")
    print(f"    {token}")
    print()
    print("  Defina no servidor: AGENT_API_TOKEN=<token acima>")


async def _list_servers() -> None:
    async with SessionLocal() as session:
        rows = (await session.execute(select(Server).order_by(Server.id))).scalars().all()
    if not rows:
        print("Nenhum servidor registrado.")
        return
    print(f"{'id':>3}  {'hostname':<24} {'os':<8} {'ativo':<6} {'ultimo_contato'}")
    print("-" * 70)
    for s in rows:
        last = s.last_seen_at.isoformat() if s.last_seen_at else "-"
        print(f"{s.id:>3}  {s.hostname:<24} {s.os_family:<8} "
              f"{'sim' if s.is_active else 'nao':<6} {last}")


async def _revoke_server(server_id: int) -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            update(Server).where(Server.id == server_id).values(is_active=False)
        )
        await session.commit()
    if result.rowcount:
        print(f"Servidor {server_id} revogado (is_active=false).")
    else:
        print(f"Servidor {server_id} nao encontrado.")


async def _create_user(username: str, display_name: str | None, role: str) -> None:
    # Senha via prompt oculto — nunca em argv (visível no histórico do shell)
    password = getpass.getpass("Senha do novo usuario: ")
    confirm = getpass.getpass("Confirme a senha: ")
    if password != confirm:
        print("Senhas nao conferem — nada foi criado.")
        return
    if len(password) < 8:
        print("Senha muito curta (minimo 8 caracteres) — nada foi criado.")
        return

    async with SessionLocal() as session:
        existing = await session.execute(
            select(User).where(User.username == username)
        )
        if existing.scalar_one_or_none() is not None:
            print(f"Usuario '{username}' ja existe.")
            return
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name=display_name,
            role=role,
            is_active=True,
        )
        session.add(user)
        await session.commit()
    print(f"Usuario '{username}' criado com papel '{role}'. Login disponivel no dashboard.")


async def _list_users() -> None:
    async with SessionLocal() as session:
        rows = (await session.execute(select(User).order_by(User.id))).scalars().all()
    if not rows:
        print("Nenhum usuario cadastrado. Use: python manage.py create-user --username <nome>")
        return
    print(f"{'id':>3}  {'username':<20} {'papel':<10} {'ativo':<6} {'criado_em'}")
    print("-" * 65)
    for u in rows:
        created = u.created_at.strftime("%Y-%m-%d") if u.created_at else "-"
        print(f"{u.id:>3}  {u.username:<20} {u.role:<10} "
              f"{'sim' if u.is_active else 'nao':<6} {created}")


async def _deactivate_user(username: str) -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            update(User).where(User.username == username).values(is_active=False)
        )
        await session.commit()
    if result.rowcount:
        print(f"Usuario '{username}' desativado (sessoes existentes deixam de valer).")
    else:
        print(f"Usuario '{username}' nao encontrado.")


async def _set_role(username: str, role: str) -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            update(User).where(User.username == username).values(role=role)
        )
        await session.commit()
    if result.rowcount:
        print(f"Usuario '{username}' agora tem o papel '{role}'.")
    else:
        print(f"Usuario '{username}' nao encontrado.")


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI administrativa da API Argus")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-server", help="Registra um servidor e gera o token")
    p_create.add_argument("--hostname", required=True)
    p_create.add_argument("--os", dest="os_family", required=True,
                          choices=["windows", "linux"])
    p_create.add_argument("--display-name", default=None)

    sub.add_parser("list-servers", help="Lista os servidores registrados")

    p_revoke = sub.add_parser("revoke-server", help="Desativa um servidor")
    p_revoke.add_argument("--id", dest="server_id", type=int, required=True)

    p_user = sub.add_parser("create-user", help="Cria um usuario do dashboard")
    p_user.add_argument("--username", required=True)
    p_user.add_argument("--display-name", default=None)
    p_user.add_argument("--role", default="admin",
                        choices=["admin", "operator", "viewer"])

    sub.add_parser("list-users", help="Lista os usuarios do dashboard")

    p_deact = sub.add_parser("deactivate-user", help="Desativa um usuario")
    p_deact.add_argument("--username", required=True)

    p_role = sub.add_parser("set-role", help="Muda o papel de um usuario")
    p_role.add_argument("--username", required=True)
    p_role.add_argument("--role", required=True,
                        choices=["admin", "operator", "viewer"])

    args = parser.parse_args()

    if args.command == "create-server":
        asyncio.run(_create_server(args.hostname, args.os_family, args.display_name))
    elif args.command == "list-servers":
        asyncio.run(_list_servers())
    elif args.command == "revoke-server":
        asyncio.run(_revoke_server(args.server_id))
    elif args.command == "create-user":
        asyncio.run(_create_user(args.username, args.display_name, args.role))
    elif args.command == "list-users":
        asyncio.run(_list_users())
    elif args.command == "deactivate-user":
        asyncio.run(_deactivate_user(args.username))
    elif args.command == "set-role":
        asyncio.run(_set_role(args.username, args.role))


if __name__ == "__main__":
    main()

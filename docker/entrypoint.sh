#!/bin/sh
# entrypoint.sh — sobe a API da central depois de preparar o banco.
#
# O compose garante (depends_on: condition: service_healthy) que o Postgres já
# aceita conexões antes de iniciar este container, então aqui basta:
#   1) aplicar as migrations (alembic upgrade head)
#   2) exec do comando (uvicorn) — exec faz o uvicorn virar PID 1 e receber o
#      SIGTERM do `docker stop`, permitindo o shutdown limpo do lifespan.
#
# ATENÇÃO: este arquivo precisa ter fim de linha LF (ver .gitattributes).
set -e

echo "[entrypoint] Aplicando migrations (alembic upgrade head)..."
alembic upgrade head
echo "[entrypoint] Migrations OK. Iniciando: $*"

exec "$@"

#!/bin/sh
# restore.sh — restaura um dump de /backups no banco `argus`.
#
# ATENCAO: sobrescreve o banco atual (--clean). Confirme antes de rodar contra
# uma central em producao.
#
# Uso (a partir do host, com a central no ar):
#   docker compose exec backup /restore.sh --list
#   docker compose exec backup /restore.sh argus-20260713T220000Z.dump
set -eu

BACKUP_DIR=/backups

if [ "${1:-}" = "--list" ] || [ -z "${1:-}" ]; then
    echo "Dumps disponiveis em $BACKUP_DIR:"
    ls -lh "$BACKUP_DIR"/argus-*.dump 2>/dev/null || echo "  (nenhum)"
    if [ -z "${1:-}" ]; then
        echo
        echo "Uso: restore.sh <arquivo.dump>"
        exit 1
    fi
    exit 0
fi

FILE="$BACKUP_DIR/$1"
[ -f "$FILE" ] || FILE="$1"   # aceita caminho absoluto tambem

if [ ! -f "$FILE" ]; then
    echo "[restore] arquivo nao encontrado: $1" >&2
    exit 1
fi

echo "[restore] restaurando '$FILE' no banco 'argus' (db)"
echo "[restore] isto SOBRESCREVE os dados atuais. Ctrl+C nos proximos 10s para cancelar."
sleep 10

pg_restore -h db -U argus -d argus --clean --if-exists --no-owner "$FILE"
echo "[restore] concluido."

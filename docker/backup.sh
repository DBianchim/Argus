#!/bin/sh
# backup.sh — dump periodico do Postgres da central, com retencao.
#
# Roda como sidecar no docker-compose (imagem postgres:18, mesma versao do
# banco — garante pg_dump/pg_restore compativeis). Grava em /backups, que o
# compose liga a uma pasta do HOST (./backups), nao um volume Docker gerenciado:
# assim o arquivo fica acessivel para copiar para fora da maquina (rsync,
# robocopy, sync de nuvem) sem precisar entender o storage interno do Docker —
# um backup que so existe no mesmo disco da central nao protege contra a perda
# desse disco.
#
# Formato -Fc (custom, comprimido): permite restore seletivo com pg_restore e
# nao depende de encoding de shell, diferente de um dump -Fp/.sql puro.
set -eu

BACKUP_DIR=/backups
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"

mkdir -p "$BACKUP_DIR"

run_backup() {
    ts=$(date -u +%Y%m%dT%H%M%SZ)
    dest="$BACKUP_DIR/argus-$ts.dump"
    tmp="$dest.tmp"

    echo "[backup] iniciando dump -> $dest"
    if pg_dump -h db -U argus -d argus -Fc -f "$tmp"; then
        mv "$tmp" "$dest"
        echo "[backup] OK ($(du -h "$dest" | cut -f1))"
    else
        echo "[backup] FALHOU — descartando arquivo parcial"
        rm -f "$tmp"
        return 1
    fi

    echo "[backup] aplicando retencao (${RETENTION_DAYS} dias)"
    find "$BACKUP_DIR" -name 'argus-*.dump' -mtime "+${RETENTION_DAYS}" -print -delete
}

echo "[backup] sidecar iniciado | intervalo=${INTERVAL_HOURS}h | retencao=${RETENTION_DAYS}d | destino=${BACKUP_DIR}"

# Primeiro dump logo na subida — nao espera o primeiro intervalo completo, ou
# um reinicio antes do primeiro ciclo deixaria a central sem nenhum backup.
run_backup || true

while true; do
    sleep "$(( INTERVAL_HOURS * 3600 ))"
    run_backup || true
done

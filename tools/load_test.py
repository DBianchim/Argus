#!/usr/bin/env python3
"""
load_test.py — Simulador de frota para carga real contra a central Argus

Registra N servidores efêmeros no banco (como `manage.py create-server`, em lote),
dispara agentes virtuais que enviam payloads reais via HTTP para
POST /api/v1/ingest (o mesmo endpoint que os agentes de verdade usam), mede a
carga do lado do cliente e confere com o GET /api/v1/ingest/stats do lado do
servidor. Ao final, remove os servidores simulados (cascata: métricas e
notificações somem junto) — a menos que --keep seja passado.

Diferença para tools/mock_server.py: aquele é um servidor falso para testar o
agente sem subir a central. Este é um CLIENTE que testa a central DE VERDADE
(banco + análise + notificações) sob carga, sem precisar de N máquinas físicas.

Requer: rodar com o Python do api/.venv (usa app.database/app.config direto) e
a central (uvicorn) já rodando em --api-url.

Uso (a partir de api/, com o venv ativo e a API rodando em outro terminal):
    python ..\\tools\\load_test.py run --count 20 --duration 60 --interval 10
    python ..\\tools\\load_test.py run --count 50 --duration 30 --burst   # pico
    python ..\\tools\\load_test.py cleanup                                # órfãos
"""

import argparse
import asyncio
import datetime
import random
import statistics
import sys
import time
from pathlib import Path

# Permite importar app.* mesmo chamando o script de fora de api/.
API_DIR = Path(__file__).parent.parent / "api"
sys.path.insert(0, str(API_DIR))

import httpx
from sqlalchemy import delete, select

from app.auth import hash_token
from app.config import settings
from app.config_defaults import default_config
from app.database import SessionLocal
from app.models import Server

AGENT_VERSION = "loadtest-sim"  # marca síntese: fácil de filtrar/identificar no dashboard
PILARES = ("operacional", "backup", "acesso", "logs")


# ── geração de payload (realista, com --chaos-pct opcional) ───────────────────

def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_payload(pilar: str, hostname: str, os_family: str, chaos_pct: int) -> dict:
    chaos = random.randint(1, 100) <= chaos_pct

    if pilar == "operacional":
        cpu = random.uniform(90, 99) if chaos else random.uniform(5, 60)
        mem_pct = random.uniform(85, 95) if chaos else random.uniform(20, 70)
        metrics = {
            "cpu": {"usage_pct": round(cpu, 1), "cores": 8},
            "memory": {
                "total_mb": 16384, "used_mb": round(16384 * mem_pct / 100),
                "usage_pct": round(mem_pct, 1),
            },
            "disk": [{"mount": "/", "usage_pct": round(random.uniform(30, 70), 1)}],
            "services": [{"name": "sshd" if os_family == "linux" else "WinRM", "status": "running"}],
        }
        if os_family == "linux":
            metrics["uptime_seconds"] = random.randint(3600, 900000)

    elif pilar == "backup":
        status = "SLA_BREACH" if chaos else "OK"
        metrics = {"backup": {
            "status": status,
            "path": "/mnt/backups/db.tar.gz",
            "age_hours": round(random.uniform(30, 48) if chaos else random.uniform(1, 20), 1),
            "sla_hours": 24,
            "sla_ok": not chaos,
            "integrity": {"integrity_check": "PASS"},
            "log": {"log_found": True},
        }}

    else:  # acesso / logs
        n_err = random.randint(1, 2) if chaos else 0
        findings = [
            {
                "timestamp": _now_iso(), "pilar": pilar, "item": f"sim_finding_{i}",
                "value": "erro simulado", "status": "error", "detail": "gerado por load_test.py",
            }
            for i in range(n_err)
        ]
        metrics = {
            "summary": {"ok": 1, "warning": 0, "error": n_err, "info": 0},
            "total_findings": 1 + n_err,
            "findings": findings,
            "duration_seconds": round(random.uniform(0.1, 2.0), 2),
        }

    return {
        "timestamp": _now_iso(),
        "hostname": hostname,
        "os_family": os_family,
        "pilar": pilar,
        "agent_version": AGENT_VERSION,
        "metrics": metrics,
    }


# ── registro / limpeza de servidores efêmeros ──────────────────────────────────

async def _register_fleet(count: int, prefix: str) -> list[dict]:
    """Cria `count` servidores no banco (metade windows, metade linux) e devolve
    id/hostname/os_family/token de cada um (token só existe agora, em memória)."""
    import secrets

    fleet = []
    async with SessionLocal() as session:
        for i in range(count):
            os_family = "linux" if i % 2 else "windows"
            hostname = f"{prefix}-{i:03d}"
            token = secrets.token_urlsafe(24)
            server = Server(
                hostname=hostname,
                os_family=os_family,
                display_name=f"[load_test] {hostname}",
                api_token_hash=hash_token(token),
                is_active=True,
                config=default_config(os_family),
                config_version=1,
            )
            session.add(server)
            fleet.append({"hostname": hostname, "os_family": os_family, "token": token})
        await session.commit()
    print(f"[registro] {count} servidor(es) efêmero(s) criado(s) com prefixo '{prefix}-'")
    return fleet


async def _cleanup_fleet(prefix: str) -> int:
    """Remove todo servidor cujo hostname comece com `prefix-` (cascata: métricas/notificações)."""
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Server).where(Server.hostname.like(f"{prefix}-%"))
        )).scalars().all()
        n = len(rows)
        if n:
            await session.execute(delete(Server).where(Server.hostname.like(f"{prefix}-%")))
            await session.commit()
    return n


# ── carga ───────────────────────────────────────────────────────────────────

class _Stats:
    def __init__(self):
        self.status_counts: dict[int, int] = {}
        self.latencies_ms: list[float] = []
        self.errors: list[str] = []

    def record(self, status: int | None, latency_ms: float, error: str | None = None):
        if status is not None:
            self.status_counts[status] = self.status_counts.get(status, 0) + 1
            self.latencies_ms.append(latency_ms)
        if error:
            self.errors.append(error)

    def print_summary(self, wall_seconds: float):
        total = sum(self.status_counts.values())
        print()
        print("=" * 60)
        print("  Resultado do lado do CLIENTE (o que o simulador observou)")
        print("=" * 60)
        print(f"  Requisicoes enviadas : {total + len(self.errors)}")
        print(f"  Por status HTTP      : {dict(sorted(self.status_counts.items()))}")
        if self.errors:
            print(f"  Falhas de rede/conexao: {len(self.errors)} "
                  f"(ex.: {self.errors[0][:80]})")
        if self.latencies_ms:
            lat = sorted(self.latencies_ms)
            print(f"  Vazao observada      : {total / wall_seconds:.1f} req/s "
                  f"({total} em {wall_seconds:.1f}s)")
            print(f"  Latencia p50/p95/max : "
                  f"{statistics.median(lat):.1f}ms / "
                  f"{lat[int(len(lat) * 0.95)]:.1f}ms / {lat[-1]:.1f}ms")
        print()


async def _agent_loop(
    client: httpx.AsyncClient, server: dict, api_url: str, deadline: float,
    interval: float, jitter: bool, pilares: tuple, chaos_pct: int, stats: _Stats,
):
    """Um agente virtual: dispara um payload por pilar a cada `interval`, até `deadline`."""
    headers = {"Authorization": f"Bearer {server['token']}"}
    if jitter:
        await asyncio.sleep(random.uniform(0, interval))

    while time.monotonic() < deadline:
        for pilar in pilares:
            payload = _build_payload(pilar, server["hostname"], server["os_family"], chaos_pct)
            start = time.perf_counter()
            try:
                resp = await client.post(f"{api_url}/api/v1/ingest", json=payload, headers=headers)
                stats.record(resp.status_code, (time.perf_counter() - start) * 1000)
            except httpx.HTTPError as exc:
                stats.record(None, 0.0, error=f"{type(exc).__name__}: {exc}")
        await asyncio.sleep(interval)


async def _fetch_server_stats(api_url: str, dashboard_token: str) -> dict | None:
    headers = {"Authorization": f"Bearer {dashboard_token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{api_url}/api/v1/ingest/stats", headers=headers)
        if resp.status_code != 200:
            print(f"[aviso] GET /ingest/stats respondeu {resp.status_code} — "
                  f"confira --dashboard-token")
            return None
        return resp.json()
    except httpx.HTTPError as exc:
        print(f"[aviso] Não foi possível consultar /ingest/stats: {exc}")
        return None


def _print_server_stats(data: dict | None):
    print("=" * 60)
    print("  Resultado do lado do SERVIDOR (GET /api/v1/ingest/stats)")
    print("=" * 60)
    if data is None:
        print("  (indisponível)")
        print()
        return
    print(f"  Recebidos/Persistidos/Falhos : "
          f"{data['total_received']}/{data['total_persisted']}/{data['total_failed']}")
    print(f"  Por pilar                    : {data['per_pilar']}")
    print(f"  Vazao (janela de 60s)        : {data['throughput_per_min']} payloads/min")
    print(f"  Latencia de persistencia     : "
          f"avg={data['persist_ms_avg']}ms  p50={data['persist_ms_p50']}ms  "
          f"p95={data['persist_ms_p95']}ms  max={data['persist_ms_max']}ms")
    print()


# ── comandos ───────────────────────────────────────────────────────────────────

async def cmd_run(args: argparse.Namespace) -> int:
    fleet = await _register_fleet(args.count, args.prefix)
    pilares = tuple(args.pilares.split(",")) if args.pilares else PILARES
    for p in pilares:
        if p not in PILARES:
            print(f"[erro] pilar desconhecido: '{p}' (válidos: {PILARES})")
            return 1

    dashboard_token = args.dashboard_token or settings.dashboard_token

    print(f"[carga] {len(fleet)} agente(s) virtual(is) | pilares={pilares} | "
          f"intervalo={args.interval}s | duracao={args.duration}s | "
          f"modo={'burst' if args.burst else 'escalonado (jitter)'}"
          + (f" | chaos={args.chaos_pct}%" if args.chaos_pct else ""))
    print(f"[carga] alvo: {args.api_url}/api/v1/ingest")
    print()

    stats = _Stats()
    deadline = time.monotonic() + args.duration
    wall_start = time.monotonic()

    limits = httpx.Limits(max_connections=max(50, args.count))
    async with httpx.AsyncClient(timeout=15, limits=limits) as client:
        await asyncio.gather(*[
            _agent_loop(
                client, server, args.api_url, deadline, args.interval,
                jitter=not args.burst, pilares=pilares, chaos_pct=args.chaos_pct,
                stats=stats,
            )
            for server in fleet
        ])

    wall_seconds = time.monotonic() - wall_start
    stats.print_summary(wall_seconds)

    # Pequena folga para o servidor terminar de registrar o último lote no /ingest/stats.
    await asyncio.sleep(0.5)
    server_stats = await _fetch_server_stats(args.api_url, dashboard_token)
    _print_server_stats(server_stats)

    if args.keep:
        print(f"[registro] servidores mantidos (prefixo '{args.prefix}-'). "
              f"Remova depois com: python load_test.py cleanup --prefix {args.prefix}")
    else:
        n = await _cleanup_fleet(args.prefix)
        print(f"[limpeza] {n} servidor(es) simulado(s) removido(s) (métricas incluídas).")

    return 0


async def cmd_cleanup(args: argparse.Namespace) -> int:
    n = await _cleanup_fleet(args.prefix)
    print(f"[limpeza] {n} servidor(es) com prefixo '{args.prefix}-' removido(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Registra a frota simulada e gera carga real")
    p_run.add_argument("--count", type=int, default=10, help="Nº de servidores virtuais (padrão: 10)")
    p_run.add_argument("--duration", type=float, default=30, help="Duração da carga em segundos (padrão: 30)")
    p_run.add_argument("--interval", type=float, default=5, help="Intervalo entre ciclos de cada agente (padrão: 5s)")
    p_run.add_argument("--pilares", default=None, help="Lista separada por vírgula (padrão: os 4)")
    p_run.add_argument("--api-url", default="http://localhost:8000", help="URL da central")
    p_run.add_argument("--prefix", default="loadtest", help="Prefixo dos hostnames simulados")
    p_run.add_argument("--dashboard-token", default=None, help="Override do token do dashboard (senão usa o .env da API)")
    p_run.add_argument("--chaos-pct", type=int, default=0, help="%% de payloads com valores fora do normal (0-100)")
    p_run.add_argument("--burst", action="store_true", help="Todos os agentes disparam juntos, sem escalonamento (teste de pico)")
    p_run.add_argument("--keep", action="store_true", help="Não remove os servidores simulados ao final")
    p_run.set_defaults(func=cmd_run)

    p_clean = sub.add_parser("cleanup", help="Remove servidores simulados órfãos (ex.: após Ctrl+C)")
    p_clean.add_argument("--prefix", default="loadtest", help="Prefixo dos hostnames a remover")
    p_clean.set_defaults(func=cmd_cleanup)

    args = parser.parse_args()
    try:
        return asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("\n[interrompido] rode 'cleanup' para remover servidores simulados que tenham sobrado.")
        return 130


if __name__ == "__main__":
    sys.exit(main())

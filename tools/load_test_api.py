#!/usr/bin/env python3
"""
load_test_api.py - carga contra o POST /api/v1/ingest da central, SOMENTE pela API HTTPS.

Ferramenta usada no teste de carga do CT09. Ao contrario
de tools/load_test.py, nao acessa o banco: registra os servidores simulados por
POST /api/v1/servers, envia a carga pelo mesmo caminho dos agentes reais (Caddy -> API) e
remove os servidores por DELETE ao final. Por isso roda de qualquer maquina que alcance
a central, inclusive uma VM cliente separada.

Requisitos: python 3.10+ e `pip install httpx`.
Token do dashboard: variavel de ambiente ARGUS_DASHBOARD_TOKEN (nunca como argumento).
CA interna da central: --ca-cert caminho/root.crt (baixe de http://<central>/install/ca.crt).

Exemplo:
  set ARGUS_DASHBOARD_TOKEN=...   (ou export no Linux)
  python load_test_api.py --base-url https://argus.local --ca-cert root.crt --count 20 --duration 60 --interval 10
"""
import argparse, asyncio, datetime, json, os, random, statistics, sys, time
import httpx

PILARES = ("operacional", "backup", "acesso", "logs")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def payload(pilar, hostname, os_family):
    if pilar == "operacional":
        m = {"cpu": {"usage_pct": round(random.uniform(5, 60), 1), "cores": 4},
             "memory": {"usage_pct": round(random.uniform(20, 70), 1)},
             "disk": [{"mount": "/", "usage_pct": round(random.uniform(30, 70), 1)}],
             "services": [{"name": "sshd", "status": "running"}]}
    elif pilar == "backup":
        m = {"backup": {"status": "OK", "path": "/mnt/backups/db.tar.gz", "age_hours": round(random.uniform(1, 20), 1),
                        "sla_hours": 24, "sla_ok": True, "integrity": {"integrity_check": "OK"}, "log": {"log_found": True}}}
    else:
        m = {"summary": {"ok": 1, "warning": 0, "error": 0, "info": 0}, "total_findings": 1, "findings": [],
             "duration_seconds": round(random.uniform(0.1, 2.0), 2)}
    return {"timestamp": now_iso(), "hostname": hostname, "os_family": os_family, "pilar": pilar,
            "agent_version": "loadtest-api", "metrics": m}


def pct(sorted_values, p):
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


async def agent(client, base, srv, deadline, interval, jitter, res):
    h = {"Authorization": f"Bearer {srv['token']}"}
    if jitter:
        await asyncio.sleep(random.uniform(0, interval))
    while time.monotonic() < deadline:
        for p in PILARES:
            t = time.perf_counter()
            try:
                r = await client.post(f"{base}/api/v1/ingest", json=payload(p, srv["hostname"], srv["os"]), headers=h)
                res["status"][r.status_code] = res["status"].get(r.status_code, 0) + 1
                res["lat"].append((time.perf_counter() - t) * 1000)
            except httpx.HTTPError as e:
                res["errors"].append(type(e).__name__)
        await asyncio.sleep(interval)


async def stats(client, base, tok):
    r = await client.get(f"{base}/api/v1/ingest/stats", headers={"Authorization": f"Bearer {tok}"})
    return r.json() if r.status_code == 200 else {"erro_http": r.status_code}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--ca-cert", default=None)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--interval", type=float, default=10)
    ap.add_argument("--burst", action="store_true")
    ap.add_argument("--prefix", default="loadapi")
    ap.add_argument("--out", default=None, help="grava o resultado em JSON")
    a = ap.parse_args()
    tok = os.environ.get("ARGUS_DASHBOARD_TOKEN")
    if not tok:
        sys.exit("defina ARGUS_DASHBOARD_TOKEN")
    base = a.base_url.rstrip("/")
    verify = a.ca_cert or True
    H = {"Authorization": f"Bearer {tok}"}
    res = {"status": {}, "lat": [], "errors": []}
    fleet = []
    async with httpx.AsyncClient(timeout=15, verify=verify, limits=httpx.Limits(max_connections=max(50, a.count))) as c:
        try:
            for i in range(a.count):
                host = f"{a.prefix}-{i:03d}"
                osf = "linux" if i % 2 else "windows"
                r = await c.post(f"{base}/api/v1/servers", headers=H,
                                 json={"hostname": host, "os_family": osf, "display_name": f"[loadtest] {host}"})
                r.raise_for_status()
                d = r.json()
                fleet.append({"id": d["server"]["id"], "hostname": host, "os": osf, "token": d["token"]})
            before = await stats(c, base, tok)
            t0 = time.monotonic()
            started = now_iso()
            deadline = t0 + a.duration
            await asyncio.gather(*[agent(c, base, s, deadline, a.interval, not a.burst, res) for s in fleet])
            wall = time.monotonic() - t0
            await asyncio.sleep(0.5)
            after = await stats(c, base, tok)
        finally:
            removed = 0
            for s in fleet:
                try:
                    rr = await c.delete(f"{base}/api/v1/servers/{s['id']}", headers=H)
                    removed += rr.status_code == 204
                except httpx.HTTPError:
                    pass
    lat = sorted(res["lat"])
    n_ok = sum(res["status"].values())
    out = {"inicio_utc": started, "parametros": {"count": a.count, "duration": a.duration, "interval": a.interval,
           "burst": a.burst, "base_url": base}, "requisicoes": n_ok + len(res["errors"]), "por_status": res["status"],
           "falhas_de_rede": len(res["errors"]), "vazao_req_s": round(n_ok / wall, 2),
           "cliente_ms": {"p50": round(statistics.median(lat), 1) if lat else None, "p95": round(pct(lat, 95), 1),
                          "p99": round(pct(lat, 99), 1), "max": round(lat[-1], 1) if lat else None},
           "central_antes": before, "central_depois": after, "servidores_removidos": f"{removed}/{len(fleet)}"}
    print(json.dumps(out, indent=1, ensure_ascii=False))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())

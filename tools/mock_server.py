#!/usr/bin/env python3
"""
mock_server.py — Servidor HTTP mock para validação do pipeline Argus

Recebe payloads dos agentes, valida estrutura e imprime resumo.
Não requer banco de dados nem dependências externas.

Uso:
    python tools\mock_server.py                # modo normal  → retorna 200 OK
    python tools\mock_server.py --mode fail    # modo fail    → retorna 503 (testa fila)
    python tools\mock_server.py --mode slow    # modo slow    → atrasa 15s (testa timeout)
    python tools\mock_server.py --port 9000    # porta alternativa

Depois, em outro terminal:
    cd agents
    python runner.py --config config.test.toml --log-level DEBUG
"""

import argparse
import datetime
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar


# ── configuração do servidor ──────────────────────────────────────────────────

class _Config:
    mode: str = "normal"
    port: int = 8000


_cfg = _Config()


# ── formatação de saída ───────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.datetime.utcnow().strftime("%H:%M:%S")


def _print_separator() -> None:
    print("-" * 60)


def _summarize(pilar: str, payload: dict) -> str:
    metrics = payload.get("metrics", {})

    if pilar == "operacional":
        cpu = metrics.get("cpu", {})
        mem = metrics.get("memory", {})
        disk = metrics.get("disk", [])
        svc = metrics.get("services", [])

        cpu_str = (f"cpu={cpu.get('usage_pct', '?')}%"
                   if "error" not in cpu else "cpu=ERR")
        mem_pct = mem.get("usage_pct", "?")
        mem_str = f"mem={mem_pct}%" if "error" not in mem else "mem=ERR"
        disk_str = ("disk=[" +
                    " ".join(f"{d.get('mount','?')}:{d.get('usage_pct','?')}%"
                             for d in disk) + "]")
        svc_str = f"services={len(svc)}"
        return f"{cpu_str} | {mem_str} | {disk_str} | {svc_str}"

    if pilar == "backup":
        bk = metrics.get("backup", {})
        status = bk.get("status", "?")
        age = bk.get("age_hours")
        age_str = f" age={age}h" if age is not None else ""
        return f"status={status}{age_str}"

    if pilar in ("acesso", "logs"):
        summary = metrics.get("summary", {})
        total = metrics.get("total_findings", "?")
        ok = summary.get("ok", 0)
        warn = summary.get("warning", 0)
        err = summary.get("error", 0)
        info = summary.get("info", 0)
        dur = metrics.get("duration_seconds", "?")
        return (f"findings={total} | ok={ok} warn={warn} err={err} info={info} "
                f"| dur={dur}s")

    return "(pilar desconhecido)"


def _validate_payload(payload: dict) -> list[str]:
    errors = []
    for field in ("timestamp", "hostname", "os_family", "pilar", "metrics"):
        if field not in payload:
            errors.append(f"campo ausente: '{field}'")

    pilar = payload.get("pilar")
    valid_pilares = {"operacional", "backup", "acesso", "logs"}
    if pilar and pilar not in valid_pilares:
        errors.append(f"pilar inválido: '{pilar}'")

    if not payload.get("metrics"):
        errors.append("metrics vazio ou None")

    return errors


# ── handler HTTP ──────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):

    request_count: ClassVar[int] = 0

    def log_message(self, format, *args):
        pass  # desabilita o log padrão do HTTPServer

    def _send(self, code: int, body: str = "") -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": body or str(code)}).encode())

    def do_GET(self):
        if self.path == "/health":
            self._send(200, "ok")
            print(f"[{_ts()}] GET /health → 200")
        else:
            self._send(404, "not found")

    def do_POST(self):
        if self.path != "/api/v1/ingest":
            self._send(404, "endpoint not found")
            return

        _Handler.request_count += 1

        # Valida Authorization header
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            print(f"[{_ts()}] ERRO: Authorization header ausente ou inválido")
            self._send(401, "unauthorized")
            return

        # Modo slow — simula timeout
        if _cfg.mode == "slow":
            print(f"[{_ts()}] MODO SLOW — aguardando 15s para simular timeout...")
            time.sleep(15)

        # Lê e parseia o corpo
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[{_ts()}] ERRO: corpo JSON inválido — {e}")
            self._send(400, "invalid json")
            return

        pilar    = payload.get("pilar", "?")
        hostname = payload.get("hostname", "?")
        os_fam   = payload.get("os_family", "?")

        # Modo fail — retorna 503 sem processar
        if _cfg.mode == "fail":
            print(f"[{_ts()}] #{_Handler.request_count:03d} ← {pilar:12s} | "
                  f"host={hostname} os={os_fam}")
            print(f"          MODO FAIL → 503 Service Unavailable")
            self._send(503, "service unavailable")
            return

        # Validação estrutural
        errors = _validate_payload(payload)

        # Imprime resumo
        summary = _summarize(pilar, payload)
        print(f"[{_ts()}] #{_Handler.request_count:03d} ← {pilar:12s} | "
              f"host={hostname} | os={os_fam}")
        print(f"           {summary}")

        if errors:
            for e in errors:
                print(f"           ⚠ {e}")
            print(f"           → 400 Bad Request")
            self._send(400, "validation error")
        else:
            token_preview = auth[7:11] + "..." if len(auth) > 14 else auth
            print(f"           token={token_preview} → 200 OK")
            self._send(200, "accepted")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="mock_server.py — Servidor HTTP mock para o Argus"
    )
    parser.add_argument(
        "--mode",
        choices=["normal", "fail", "slow"],
        default="normal",
        help="Comportamento do servidor: normal=200 | fail=503 | slow=timeout",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Porta HTTP (padrão: 8000)",
    )
    args = parser.parse_args()

    _cfg.mode = args.mode
    _cfg.port = args.port

    server = HTTPServer(("0.0.0.0", args.port), _Handler)

    print()
    print("=" * 60)
    print(f"  Argus Mock Server  |  porta={args.port}  |  modo={args.mode}")
    print("=" * 60)
    print(f"  Endpoint : POST http://localhost:{args.port}/api/v1/ingest")
    print(f"  Health   : GET  http://localhost:{args.port}/health")
    print()

    if args.mode == "fail":
        print("  MODO FAIL: todas as requisições retornam 503.")
        print("  Os agentes vão salvar payloads na fila local.")
        print("  Reinicie sem --mode para processar a fila.")
    elif args.mode == "slow":
        print("  MODO SLOW: respostas atrasadas 15s.")
        print("  Os agentes vão registrar timeout e usar backoff.")

    print()
    print("  Aguardando payloads... (Ctrl+C para encerrar)")
    print("-" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print(f"\n  Servidor encerrado | {_Handler.request_count} requisições recebidas")
        print()


if __name__ == "__main__":
    main()

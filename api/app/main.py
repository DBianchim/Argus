"""
main.py — Aplicação FastAPI da central Argus

Registra os routers (health, ingest, servers, metrics, auth, overview) e expõe
a documentação automática em /docs (Swagger) e /redoc.

Quando o build do dashboard existe (dashboard/dist), a SPA é servida pela
própria API — deploy único. Em desenvolvimento, o Vite roda separado com proxy.

Execução:
    uvicorn app.main:app --port 8000 --reload
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from . import __version__
from .config import settings
from .routers import auth as auth_router
from .routers import health, ingest, metrics, overview, servers

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

app = FastAPI(
    title="Argus API",
    version=__version__,
    description=(
        "Central de monitoramento Argus — ingestão de métricas dos agentes "
        "(operacional, backup, acesso, logs) e consultas para o dashboard."
    ),
)

app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(auth_router.router)
app.include_router(overview.router)
app.include_router(servers.router)
app.include_router(metrics.router)


# ── SPA (build do dashboard) ──────────────────────────────────────────────────
# Os routers acima foram registrados primeiro, então /api/*, /health e /docs
# têm precedência sobre o catch-all da SPA.

_DIST = Path(__file__).resolve().parent.parent.parent / "dashboard" / "dist"

if _DIST.is_dir():

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        # Qualquer rota não-arquivo → index.html (client-side routing)
        return FileResponse(_DIST / "index.html")

else:

    @app.get("/", tags=["root"])
    async def root():
        return {"name": "Argus API", "version": __version__, "docs": "/docs"}

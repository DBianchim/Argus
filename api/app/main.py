"""
main.py — Aplicação FastAPI da central Argus

Registra os routers (health, ingest, auth, overview, servers, metrics,
notifications) e expõe a documentação automática em /docs.

Um loop em background (lifespan) detecta servidores OFFLINE — ingest é
event-driven, mas "sem payload" não gera evento.

Quando o build do dashboard existe (dashboard/dist), a SPA é servida pela
própria API — deploy único. Em desenvolvimento, o Vite roda separado com proxy.

Execução:
    uvicorn app.main:app --port 8000 --reload
"""

import asyncio
import contextlib
import datetime
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# O catch-all da SPA serve o manifest da PWA via FileResponse, que infere o tipo
# pela extensão. .webmanifest não é conhecido por padrão (cairia em text/plain),
# então registramos o tipo correto para o navegador aceitar a instalação.
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")

from . import __version__, crud, notifications
from .config import settings
from .database import SessionLocal
from .rate_limit import limiter
from .routers import agent_config
from .routers import auth as auth_router
from .routers import health, ingest, install, metrics
from .routers import notifications as notifications_router
from .routers import overview, servers, users

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def _offline_watch() -> None:
    """Loop: marca servidores sem contato como OFFLINE e gera a notificação."""
    while True:
        await asyncio.sleep(settings.offline_check_seconds)
        try:
            async with SessionLocal() as session:
                now = datetime.datetime.now(datetime.timezone.utc)
                for server in await crud.servers_for_offline_check(session):
                    # Sem métricas: evaluate_server retorna OFFLINE com o alerta
                    await notifications.evaluate_and_notify(
                        session, server, {}, settings.offline_after_seconds, now
                    )
        except Exception as exc:  # nunca derruba o loop
            logger.warning("Falha no loop de offline | erro=%s", type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_offline_watch())
    logger.info("Loop de deteccao de OFFLINE iniciado (cada %ds)",
                settings.offline_check_seconds)
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Argus API",
    version=__version__,
    description=(
        "Central de monitoramento Argus — ingestão de métricas dos agentes "
        "(operacional, backup, acesso, logs) e consultas para o dashboard."
    ),
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(auth_router.router)
app.include_router(overview.router)
app.include_router(notifications_router.router)
app.include_router(servers.router)
app.include_router(metrics.router)
app.include_router(install.router)
app.include_router(agent_config.router)
app.include_router(users.router)


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

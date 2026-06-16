"""
install.py — Artefatos de instalação dos agentes (bootstrap "a partir da central").

Rotas PÚBLICAS (sem autenticação) que permitem instalar um agente em um servidor
com um único comando, sem copiar arquivos à mão:

    GET /install/argus-agent.zip  → o código do agente, zipado em memória
    GET /install/install.ps1      → instalador Windows (PowerShell)
    GET /install/install.sh       → instalador Linux

A CA do Caddy (`/install/ca.crt`) NÃO é servida aqui — quem a serve é o próprio
Caddy, a partir do seu repositório de certificados (ver docker/Caddyfile).

Servir o código e os scripts sem autenticação é seguro: não há segredo neles. O
token é informado no servidor-alvo (nunca trafega no download) e as métricas vão
por HTTPS. Ver install/INSTALL.md.
"""

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter(prefix="/install", tags=["install"])

# Layout dentro da imagem (Dockerfile copia agents/ e install/):
#   /app/api/app/routers/install.py  → sobe 4 níveis → /app
_ROOT = Path(__file__).resolve().parents[3]
_AGENTS_DIR = _ROOT / "agents"
_INSTALL_DIR = _ROOT / "install"

# Arquivos/pastas que NÃO entram no pacote do agente (dev-only ou ruído).
_EXCLUDE_NAMES = {"__pycache__", "config.toml", "config.test.toml"}
_EXCLUDE_SUFFIXES = {".pyc"}


def _should_include(path: Path) -> bool:
    parts = set(path.relative_to(_AGENTS_DIR).parts)
    if parts & _EXCLUDE_NAMES:
        return False
    if path.suffix in _EXCLUDE_SUFFIXES:
        return False
    return True


@router.get("/argus-agent.zip")
async def agent_bundle() -> StreamingResponse:
    """Empacota o código do agente (agents/) em um zip gerado em memória."""
    if not _AGENTS_DIR.is_dir():
        raise HTTPException(status_code=404, detail="agentes indisponíveis na imagem")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(_AGENTS_DIR.rglob("*")):
            if path.is_file() and _should_include(path):
                zf.write(path, path.relative_to(_AGENTS_DIR).as_posix())
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="argus-agent.zip"'},
    )


def _script(name: str, media_type: str) -> FileResponse:
    path = _INSTALL_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name} indisponível na imagem")
    return FileResponse(path, media_type=media_type)


@router.get("/install.ps1")
async def install_ps1() -> FileResponse:
    return _script("install.ps1", "text/plain; charset=utf-8")


@router.get("/install.sh")
async def install_sh() -> FileResponse:
    return _script("install.sh", "text/x-shellscript; charset=utf-8")

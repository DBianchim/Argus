# =============================================================================
# Dockerfile — imagem da CENTRAL do Argus (API + dashboard buildado)
#
# Multi-stage:
#   1) dashboard-build  → builda o SPA (React/Vite) e produz /dashboard/dist
#   2) runtime          → API FastAPI servindo o dist (deploy único)
#
# O layout interno reproduz o que api/app/main.py espera:
#   /app/api/app/main.py  →  sobe 3 níveis  →  /app/dashboard/dist
# Assim NÃO é preciso alterar o código da API.
# =============================================================================

# ---- Stage 1: build do dashboard ------------------------------------------
FROM node:20-alpine AS dashboard-build
WORKDIR /dashboard

# Instala dependências a partir do lockfile (build reprodutível) antes de copiar
# o código, aproveitando o cache de camada quando só o código muda.
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci

COPY dashboard/ ./
RUN npm run build          # gera /dashboard/dist (PWA: index.html, sw.js, manifest, ícones)


# ---- Stage 2: runtime da API ----------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# WORKDIR = raiz do projeto da API. Os caminhos relativos do Alembic
# (alembic.ini: prepend_sys_path = .) e o `python manage.py` dependem disso.
WORKDIR /app/api

# Dependências primeiro (cache de camada): só reinstala se requirements mudar.
COPY api/requirements.txt ./
RUN pip install -r requirements.txt

# Código da API e o dist buildado no layout que o main.py resolve.
COPY api/ /app/api/
COPY --from=dashboard-build /dashboard/dist /app/dashboard/dist

# Entrypoint: roda migrations e então exec do uvicorn (uvicorn vira PID 1).
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# --workers 1: o loop de detecção de OFFLINE roda no lifespan (1 por worker);
# 1 worker evita loops concorrentes notificando OFFLINE em duplicidade.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# Argus API (Fase 2)

Central de monitoramento: recebe os payloads dos agentes, autentica cada servidor,
persiste as métricas em **PostgreSQL** e expõe consultas para o dashboard.

Stack: **FastAPI** + **SQLAlchemy 2.0 async** (asyncpg) + **Alembic** + **Pydantic v2**.

---

## Pré-requisitos

- Python 3.11+ (validado em 3.14)
- PostgreSQL acessível (validado: 18.2 local em `localhost:5432`)
- Dependências:
  ```
  pip install -r requirements.txt          # runtime
  pip install -r requirements-dev.txt      # testes
  ```

---

## Setup do banco (uma vez)

```bash
# Cria o role/banco 'argus' (rode como superusuário; troque a senha no arquivo)
psql -U postgres -h localhost -f scripts/setup_db.sql

# Configure o .env (a partir do template) com a senha escolhida
cp .env.example .env
#   DATABASE_URL=postgresql+asyncpg://argus:<senha>@localhost:5432/argus
#   DASHBOARD_TOKEN=<token forte para os endpoints de consulta>

# Cria as tabelas
alembic upgrade head
```

> **Segredos:** o `.env` é só para dev (está no `.gitignore`). Em produção, defina
> `DATABASE_URL` e `DASHBOARD_TOKEN` como variáveis de ambiente reais.

---

## Registrar um servidor (gera o token do agente)

```bash
python manage.py create-server --hostname MEU-SERVIDOR --os windows
# imprime o TOKEN uma única vez → use como AGENT_API_TOKEN no agente

python manage.py list-servers
python manage.py revoke-server --id 1     # desativa (ingest passa a 401)
```

---

## Subir a API

```bash
uvicorn app.main:app --port 8000           # produção: sem --reload
# Documentação interativa: http://localhost:8000/docs
```

---

## Endpoints

| Método | Rota | Auth | Função |
|--------|------|------|--------|
| `POST` | `/api/v1/ingest` | token de agente | Recebe e persiste 1 payload (200/401/422/503) |
| `GET` | `/health` | — | Liveness + checa o banco |
| `GET` | `/api/v1/servers` | dashboard | Lista servidores + `last_seen_at` |
| `GET` | `/api/v1/servers/{id}/latest` | dashboard | Último payload por pilar (estado atual) |
| `GET` | `/api/v1/metrics` | dashboard | Histórico (`server_id,pilar,since,until` + `limit/offset`) |
| `GET` | `/docs` | — | OpenAPI/Swagger |

Endpoints de dashboard exigem `Authorization: Bearer <DASHBOARD_TOKEN>`.

### Contrato com o agente
O agente (`agents/core/sender.py`) trata os códigos assim:
- **200** = sucesso (a API retorna exatamente 200).
- **401** (token inválido) / **422** (corpo inválido) → o agente **descarta**.
- **503** (erro transitório de persistência) → o agente **retenta e enfileira**.

---

## Testes

```bash
pytest -q          # roda em SQLite async (não precisa de PostgreSQL)
```
Cobre os 4 códigos do contrato (200/401/422), autenticação (agente e dashboard,
incluindo revogação), persistência/`last_seen`, e as consultas (latest por pilar,
paginação e filtros).

---

## Estrutura

```
api/
├── app/
│   ├── main.py          # FastAPI + routers
│   ├── config.py        # Settings (.env / env vars)
│   ├── database.py      # engine async + sessão
│   ├── models.py        # ORM: Server, Metric
│   ├── schemas.py       # Pydantic
│   ├── auth.py          # token (sha256) + dependencies
│   ├── crud.py          # operações de banco
│   └── routers/         # ingest, servers, metrics, health
├── alembic/             # migrações
├── manage.py            # CLI de servidores/tokens
├── scripts/setup_db.sql
├── tests/
├── requirements.txt + requirements-dev.txt
└── .env.example
```

---

## Fluxo fim-a-fim (validado)

```
agente (runner.py)  →  POST /api/v1/ingest (Bearer token)  →  PostgreSQL
                                                              ↓
dashboard  ←  GET /api/v1/servers/{id}/latest (Bearer DASHBOARD_TOKEN)
```
Os 4 pilares (operacional, backup, acesso, logs) chegam com HTTP 200 e o `/latest`
reflete o estado atual coletado.
```

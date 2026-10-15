# Argus — API (Central)

Recebe os payloads dos agentes, autentica cada servidor, persiste as métricas em
**PostgreSQL**, avalia o estado da frota e expõe os dados ao dashboard.

Stack: **FastAPI**, **SQLAlchemy 2.0 async** (asyncpg), **Alembic**, **Pydantic v2**,
**slowapi** (rate limiting).

---

## Pré-requisitos

- Python 3.11+ (validado em 3.14)
- PostgreSQL acessível (validado: 18)
- Dependências:
  ```
  pip install -r requirements.txt          # runtime
  pip install -r requirements-dev.txt      # testes
  ```

---

## Setup do banco (desenvolvimento)

```bash
# Cria o role/banco 'argus' (como superusuário; ajuste a senha no arquivo)
psql -U postgres -h localhost -f scripts/setup_db.sql

# Configuração a partir do template
cp .env.example .env
#   DATABASE_URL=postgresql+asyncpg://argus:<senha>@localhost:5432/argus
#   DASHBOARD_TOKEN=<token forte do serviço>

# Aplica o esquema
alembic upgrade head
```

> O `.env` é apenas para desenvolvimento (consta no `.gitignore`). Em produção,
> defina `DATABASE_URL` e `DASHBOARD_TOKEN` como variáveis de ambiente.
> Em produção via Docker Compose, as migrações rodam automaticamente no boot.

---

## CLI administrativa (`manage.py`)

```bash
# Servidores (o token é exibido UMA vez; use-o como AGENT_API_TOKEN no agente)
python manage.py create-server --hostname MEU-SERVIDOR --os windows
python manage.py list-servers
python manage.py revoke-server --id 1          # desativa; o ingest passa a responder 401

# Usuários do dashboard (senha por prompt seguro)
python manage.py create-user --username maria --role admin
python manage.py list-users
python manage.py set-role --username maria --role operator
python manage.py deactivate-user --username maria
```

Servidores e usuários também podem ser gerenciados pelo dashboard (registro de
servidores: papel `operator`+; usuários: `admin`). A CLI é o caminho para o
primeiro administrador.

---

## Execução

```bash
uvicorn app.main:app --port 8000      # produção: sem --reload
# Documentação interativa: http://localhost:8000/docs
```

---

## Autenticação e papéis

| Identidade | Credencial | Uso |
|------------|------------|-----|
| Agente | Token por servidor (Bearer; armazenado como SHA-256) | `ingest`, `agent-config` |
| Usuário | Token de sessão (Bearer; hash; validade de 12 h) | Dashboard |
| Serviço | `DASHBOARD_TOKEN` | Integrações; equivale a `admin` nos endpoints de consulta e gestão |

Papéis de usuário, em hierarquia `viewer < operator < admin`:

| Papel | Permissões |
|-------|-----------|
| `viewer` | Somente leitura; pode reconhecer alertas |
| `operator` | Registrar, editar, ativar/desativar e remover servidores; alterar configuração |
| `admin` | Tudo de `operator` + gestão de usuários |

Respostas: `401` para credencial ausente/inválida; `403` para papel insuficiente;
`409` ao tentar remover, desativar ou rebaixar o último administrador ativo.

---

## Endpoints

| Método | Rota | Acesso | Função |
|--------|------|--------|--------|
| `GET` | `/health` | público | Liveness e verificação do banco |
| `POST` | `/api/v1/ingest` | agente | Recebe 1 payload (200/401/422/503; 1500/min/IP) |
| `GET` | `/api/v1/ingest/stats` | dashboard | Contadores e latência de persistência |
| `GET` | `/api/v1/agent-config` | agente | Configuração gerenciada pela central |
| `GET` | `/install/argus-agent.zip`, `install.ps1`, `install.sh` | público | Bootstrap de agentes (30/min/IP) |
| `POST` | `/api/v1/auth/login` | público | Abre sessão |
| `POST` | `/api/v1/auth/logout` | sessão | Revoga a sessão atual |
| `GET` `PATCH` | `/api/v1/auth/me` | sessão | Perfil próprio; nome de exibição |
| `GET` | `/api/v1/auth/sessions` | sessão | Sessões ativas do usuário |
| `DELETE` | `/api/v1/auth/sessions/{id}` | sessão | Revoga uma sessão própria |
| `POST` | `/api/v1/auth/change-password` | sessão | Troca a senha; revoga as demais sessões |
| `GET` | `/api/v1/overview` | dashboard | KPIs, alertas ativos e cards por servidor |
| `GET` | `/api/v1/servers` | dashboard | Lista de servidores |
| `GET` | `/api/v1/servers/{id}/health` | dashboard | Status e alertas do servidor |
| `GET` | `/api/v1/servers/{id}/latest` | dashboard | Último payload por pilar |
| `GET` | `/api/v1/servers/{id}/config` | dashboard | Configuração efetiva e `config_version` |
| `POST` | `/api/v1/servers` | operator | Registra servidor (token devolvido uma vez) |
| `PATCH` | `/api/v1/servers/{id}` | operator | Nome de exibição e ativação |
| `PUT` | `/api/v1/servers/{id}/config` | operator | Substitui a configuração |
| `DELETE` | `/api/v1/servers/{id}` | operator | Remove o servidor e seu histórico |
| `POST` | `/api/v1/servers/{id}/alerts/ack` | sessão de usuário | Reconhece um alerta (`pilar`, `item`) |
| `GET` | `/api/v1/metrics` | dashboard | Histórico (`server_id`, `pilar`, `since`, `until`, `limit`, `offset`) |
| `GET` | `/api/v1/notifications` | dashboard | Histórico de transições de estado |
| `GET` `POST` | `/api/v1/users` | admin | Lista e cria usuários |
| `PATCH` `DELETE` | `/api/v1/users/{id}` | admin | Edita ou remove usuário |
| `POST` | `/api/v1/users/{id}/reset-password` | admin | Redefine a senha |

"dashboard" = sessão de usuário válida (qualquer papel) ou token de serviço.
O reconhecimento de alertas exige sessão de usuário, pois registra quem o fez.

### Contrato com o agente

O agente (`agents/core/sender.py`) reage assim:

- **200** — sucesso.
- **401** (token inválido), **400/403/422** (corpo inválido) — descarta.
- **503**, **429** ou timeout — retenta com backoff e enfileira localmente.

Contrato completo: [../CONTRATO.md](../CONTRATO.md).

---

## Modelo de dados e migrações

| Tabela | Papel |
|--------|-------|
| `servers` | Servidor, hash do token, `last_seen_at`, `last_status`, `config`, `config_version` |
| `metrics` | Payloads recebidos (JSONB, índice GIN) |
| `users`, `user_sessions` | Usuários (scrypt, papel) e sessões (token como hash) |
| `notification_log` | Transições de estado |
| `alert_ack` | Reconhecimentos de alerta; único por `(server_id, pilar, item)` |

Migrações em `alembic/versions/` (`0001` … `0007_alert_ack`). Criar uma nova:
`alembic revision -m "descricao"`; aplicar: `alembic upgrade head`; reverter uma:
`alembic downgrade -1`.

---

## Testes

```bash
pytest -q          # 105 testes; SQLite assíncrono, não requer PostgreSQL
```

Cobre: contrato de ingestão (200/401/422/503), autenticação de agentes e
usuários, sessões, papéis e gestão de usuários, registro de servidores,
reconhecimento de alertas, visão geral, notificações, estatísticas de ingestão,
rate limiting e o motor de análise (funções puras).

---

## Estrutura

```
api/
├── app/
│   ├── main.py              # app, routers, loop de OFFLINE, SPA
│   ├── config.py            # Settings (.env / variáveis de ambiente)
│   ├── database.py          # engine async e sessão
│   ├── models.py            # ORM
│   ├── schemas.py           # Pydantic
│   ├── auth.py              # tokens, sessões, papéis
│   ├── crud.py              # operações de banco
│   ├── analysis.py          # motor de análise (funções puras)
│   ├── config_defaults.py   # configuração inicial por SO
│   ├── notifications.py     # transições de estado
│   ├── ingest_metrics.py    # instrumentação da ingestão
│   ├── rate_limit.py        # limites por IP (slowapi)
│   └── routers/             # health, ingest, auth, users, overview, servers,
│                            # metrics, notifications, agent_config, install
├── alembic/                 # migrações
├── manage.py                # CLI administrativa
├── scripts/setup_db.sql
├── tests/
├── requirements.txt, requirements-dev.txt
└── .env.example
```

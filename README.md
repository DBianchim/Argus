# Argus — Monitoramento de Infraestrutura

Sistema de monitoramento para servidores **Windows** e **Linux**. Agentes leves
coletam o estado local e o enviam a uma central (API), que persiste os dados,
analisa, gera alertas e alimenta um dashboard web.

```
┌──────────┐     HTTPS POST     ┌─────────────────────────┐           ┌────────────┐
│ Agentes  │ ─────────────────▶ │ Central                 │ ────────▶ │ Dashboard  │
│ (coleta) │   /api/v1/ingest   │ API · análise · Postgres│  consulta │ (SPA/PWA)  │
└──────────┘                    └─────────────────────────┘           └────────────┘
```

**Princípio de projeto:** o agente apenas coleta; toda análise e geração de
alertas é responsabilidade da central. Os agentes nunca decidem se algo é um
problema — apenas reportam o estado.

---

## Pilares monitorados

| Pilar | Coleta |
|-------|--------|
| **operacional** | CPU, memória, disco, serviços críticos, uptime |
| **backup** | Existência, SLA, integridade (tamanho, estrutura, SHA-256) e log dos backups |
| **acesso** | Logins SSH/Windows, sudo, configuração do SSH, auditd/auditpol, mudanças de conta |
| **logs** | Integridade de syslog/journald/Event Log, retenção, lacunas, limpeza de log |

Cada agente expõe a mesma interface ao scheduler:

```python
collect(config: AgentConfig) -> dict   # retorna o envelope padronizado
```

Envelope do payload:

```json
{ "timestamp": "...Z", "hostname": "...", "os_family": "windows|linux",
  "pilar": "...", "agent_version": "1.0.0", "metrics": { } }
```

> O contrato completo — códigos HTTP, **regra de compatibilidade aditiva** e
> versionamento — está em [CONTRATO.md](CONTRATO.md). Consulte-o antes de alterar
> qualquer agente ou a API.

---

## Componentes

| Componente | Tecnologia | Diretório | Documentação |
|------------|-----------|-----------|--------------|
| Agentes | Python 3.11+ | `agents/` | este arquivo, [install/INSTALL.md](install/INSTALL.md) |
| Central (API) | FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL 18 | `api/` | [api/README.md](api/README.md) |
| Dashboard | React 18, Vite, TypeScript, Tailwind | `dashboard/` | seção abaixo |
| Deploy | Docker Compose, Caddy (HTTPS) | raiz, `docker/` | [install/DEPLOY.md](install/DEPLOY.md) |

```
Argus/
├── agents/            # agentes: 4 pilares, scheduler, runner, core/
├── api/               # central: app/, alembic/, tests/, manage.py
├── dashboard/         # SPA React (src/pages, components, hooks, api)
├── docker/            # Caddyfile, entrypoint, backup.sh, restore.sh
├── install/           # instaladores (Linux/Windows) e guias
├── tools/             # validate_payloads, mock_server, load_test
├── tests/             # testes dos agentes
├── docker-compose.yml
└── CONTRATO.md
```

---

## Agentes

Requisitos: Python **3.11+** (em versões anteriores, `tomli` é instalado
automaticamente) e `pip install -r agents/requirements.txt`.

```bash
cd agents

# Validar a coleta localmente (sem rede)
python ../tools/validate_payloads.py

# Dry-run: coleta e imprime os payloads sem enviar
python runner.py --config config.test.toml --dry-run

# Pipeline completo contra o mock server
python ../tools/mock_server.py                 # terminal 1
python runner.py --config config.test.toml     # terminal 2
```

O token de API **não** deve constar no `config.toml` em produção: use a variável
de ambiente `AGENT_API_TOKEN` (ver `config.prod.toml` e
[install/INSTALL.md](install/INSTALL.md)) e sempre `https://` em `api_url`.

---

## Central e dashboard

A análise (`api/app/analysis.py`) transforma as métricas brutas em status
(OK, AVISO, CRÍTICO, OFFLINE) e alertas. Nenhuma regra de análise existe nos
agentes ou no JavaScript.

```bash
# Primeiro administrador (senha por prompt seguro)
cd api && python manage.py create-user --username seu-nome --role admin

# Desenvolvimento: Vite em :5173 com proxy para a API em :8000
cd dashboard && npm install && npm run dev

# Produção local: SPA servida pela API
cd dashboard && npm run build
cd ../api && uvicorn app.main:app --port 8000     # http://localhost:8000
```

### Telas

| Rota | Tela | Acesso |
|------|------|--------|
| `/` | Dashboard — KPIs da frota, alertas e cards por servidor | todos |
| `/servers` | Servidores — lista com filtros por SO e pilar | todos |
| `/servers/:id` | Detalhe — gauges, serviços, backup vs SLA, *findings*, histórico, reconhecimento de alertas | todos |
| `/alerts` | Alertas ativos da frota, com tempo em estado anormal | todos |
| `/settings` | Registro de servidores e configuração por pilar | operator, admin |
| `/account` | Perfil, senha, sessões ativas e gestão de usuários (admin) | todos |

Atualização automática a cada 30 s.

### Papéis de usuário

| Papel | Permissões |
|-------|-----------|
| `viewer` | Somente leitura; pode reconhecer alertas |
| `operator` | Leitura + registrar, editar e remover servidores e sua configuração |
| `admin` | Tudo de `operator` + gestão de usuários |

A autorização é aplicada pela API; a interface apenas oculta o que o papel não
permite. Detalhes em [api/README.md](api/README.md).

### Notificações e PWA

Quando o status de um servidor **muda** (torna-se CRÍTICO, fica OFFLINE ou se
recupera), a central registra a transição em `notification_log` e o dashboard
exibe um toast e, se permitido, uma notificação do sistema operacional. Não há
registro a cada ciclo e não há envio por e-mail.

O dashboard é uma PWA instalável (Chrome/Edge: ícone *Instalar* na barra de
endereço). Requer contexto seguro: `localhost` ou HTTPS.

---

## Testes

```bash
# Agentes (2 testes específicos de Linux são ignorados no Windows)
python -m unittest discover -s tests -p "test_*.py"     # 95 testes

# API (SQLite assíncrono; não requer PostgreSQL)
cd api && pytest -q                                     # 105 testes

# Dashboard (verificação de tipos)
cd dashboard && npm run typecheck
```

---

## Instalação em produção

Duas instalações independentes: a **central** (uma por organização) e os
**agentes** (um por servidor monitorado).

### Central

Empacotada em Docker Compose: PostgreSQL, API com dashboard, reverse proxy com
HTTPS e um serviço de backup automático do banco, todos com reinício automático.

```bash
cp .env.example .env          # preencha POSTGRES_PASSWORD e DASHBOARD_TOKEN
docker compose up -d --build  # as migrações rodam no boot
docker compose exec api python manage.py create-user --username admin --role admin
```

O HTTPS é automático via Caddy (`tls internal` com CA local, ou Let's Encrypt
para domínio público). Defina `ARGUS_HOST` no `.env` com o nome de acesso da
central (padrão `localhost`). Os dumps do banco são gravados em `./backups`, que
deve ser copiado periodicamente para fora da máquina. Guia completo — CA do Caddy,
PWA, backup e restauração, opção em nuvem: **[install/DEPLOY.md](install/DEPLOY.md)**.

### Agentes

Ver **[install/INSTALL.md](install/INSTALL.md)**: Linux (systemd) e Windows
(serviço com Virtual Service Account), token por variável de ambiente, conta de
serviço sem privilégios e validação com `--dry-run` antes de ativar o envio.

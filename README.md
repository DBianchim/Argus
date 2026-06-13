# Argus — Monitoramento de Infraestrutura

Sistema de monitoramento para servidores **Windows** e **Linux**. Agentes leves
coletam métricas locais e as enviam para uma API central, que alimenta um dashboard.

```
┌──────────┐     HTTP POST      ┌──────────┐                ┌────────────┐
│ Agentes  │ ─────────────────▶ │   API    │ ─────────────▶ │ Dashboard  │
│ (coleta) │   /api/v1/ingest   │ (central)│   consultas    │ (visão)    │
└──────────┘                    └──────────┘                └────────────┘
```

Princípio central: **o agente apenas coleta; toda análise/alerta é responsabilidade
da central.** Os agentes nunca decidem se algo é um problema — só reportam o estado.

---

## Os 4 pilares (agentes)

| Pilar | Coleta |
|-------|--------|
| **operacional** | CPU, memória, disco, serviços críticos, uptime (Linux) |
| **backup** | Existência, SLA, integridade (tamanho/estrutura/SHA256) e log dos backups |
| **acesso** | Logins SSH/Windows, sudo, config SSH, auditd/auditpol, mudanças de conta |
| **logs** | Integridade de syslog/journald/Event Log, retenção, gaps, limpeza de log |

Cada agente expõe a mesma interface para o scheduler:
```python
collect(config: AgentConfig) -> dict   # retorna o envelope padronizado
```

Envelope do payload:
```json
{ "timestamp": "...Z", "hostname": "...", "os_family": "windows|linux",
  "pilar": "...", "agent_version": "1.0.0", "metrics": { ... } }
```

> O contrato completo — códigos HTTP, **regra de compatibilidade aditiva** e
> versionamento — está em [CONTRATO.md](CONTRATO.md). Leia antes de alterar
> qualquer agente ou a API.

---

## Estrutura do projeto

```
Argus/
├── agents/                  # código dos agentes
│   ├── core/                # módulos compartilhados
│   │   ├── config_loader.py # carrega/valida config.toml + env vars
│   │   ├── sender.py        # envio HTTP com retry + backoff
│   │   ├── queue_local.py   # fila local (fallback offline)
│   │   └── sysutils.py      # utilitários (now_iso, run_cmd, finding, ...)
│   ├── agent_operacional.py
│   ├── agent_backup.py
│   ├── agent_acesso.py
│   ├── agent_logs.py
│   ├── scheduler.py         # orquestra os ciclos (coleta → envio → fila)
│   ├── runner.py            # ponto de entrada (CLI/serviço)
│   ├── config.toml          # config padrão (dev)
│   ├── config.test.toml     # config de teste (mock local)
│   ├── config.prod.toml     # template de produção (token via env var)
│   └── requirements.txt
├── install/                 # instaladores e guia
│   ├── install.sh           # Linux (systemd)
│   ├── install.bat          # Windows (serviço)
│   └── INSTALL.md
├── tools/                   # utilitários de validação
│   ├── validate_payloads.py # valida a coleta sem rede
│   └── mock_server.py       # API mock para testar o pipeline
└── tests/                   # suíte unittest
```

---

## Requisitos

- Python **3.11+** (recomendado; em versões anteriores instala `tomli` automaticamente)
- Dependências: `pip install -r agents/requirements.txt`

---

## Uso

```bash
cd agents

# Validar a coleta localmente (sem rede)
python ../tools/validate_payloads.py

# Modo dry-run: coleta e imprime os payloads sem enviar nada
python runner.py --config config.test.toml --dry-run

# Executar o pipeline completo (com o mock server em outro terminal)
python ../tools/mock_server.py                 # terminal 1
python runner.py --config config.test.toml     # terminal 2
```

### Configuração

O token de API **nunca** deve ficar no `config.toml` em produção. Use a variável
de ambiente `AGENT_API_TOKEN` (ver `config.prod.toml` e `install/INSTALL.md`).
Em produção, use sempre `https://` no `api_url`.

---

## Testes

```bash
python -m unittest discover -s tests -p "test_*.py"
```
No Windows, 2 testes específicos de Linux (logrotate) são pulados automaticamente
(`OK skipped=2`).

---

## Dashboard (Fase 3)

Interface web em `dashboard/` (React + Vite + Tailwind), servida pela própria API
quando buildada — deploy único. O **motor de análise** (`api/app/analysis.py`)
transforma as métricas brutas em status (OK/AVISO/CRÍTICO/OFFLINE) e alertas;
nenhuma regra de análise vive nos agentes ou no JavaScript.

```bash
# Usuário de acesso (senha via prompt seguro)
cd api && python manage.py create-user --username seu-nome

# Desenvolvimento (Vite em :5173 com proxy para a API em :8000)
cd dashboard && npm install && npm run dev

# Produção local (SPA servida pela API)
cd dashboard && npm run build
cd ../api && uvicorn app.main:app --port 8000
# → abra http://localhost:8000 e faça login
```

Telas: **Login** (sessões revogáveis, 12h) → **Visão Geral** (KPIs da frota,
alertas ativos, cards por servidor com status dos 4 pilares) → **Detalhe do
Servidor** (gauges de CPU/memória/disco, serviços, backup vs SLA, findings de
acesso/logs, histórico em gráfico). Atualização automática a cada 30s.

### Notificações

Quando o status de um servidor muda (ex.: vira CRÍTICO, fica OFFLINE, ou se
recupera), o Argus registra a transição em `notification_log` e o dashboard
dispara um **pop-up**: um toast in-app e — se o navegador permitir — uma
notificação do sistema operacional (aparece mesmo com a aba em segundo plano).
Notifica só na *mudança* de estado, nunca a cada ciclo. Sem e-mail/SMTP.

- A detecção de servidor OFFLINE roda num loop em background na API (a ingestão
  é orientada a eventos; "sem payload" não gera evento).
- Histórico via `GET /api/v1/notifications`; o sino na barra superior mostra os
  recentes.

### Instalar como app (PWA)

O dashboard é uma PWA — pode ser instalado e aberto como um **app próprio** (janela
isolada, ícone na barra de tarefas, sem abas nem barra de endereço), usando o motor
do Chromium.

1. Abra `http://localhost:8000` no **Chrome** ou **Edge**.
2. Clique no ícone **Instalar** na barra de endereço (ou menu → "Instalar Argus").
3. O Argus passa a abrir em janela própria. As notificações e o pop-up do SO
   continuam funcionando.

> Requer contexto seguro: funciona em `localhost`; em produção, sirva a API por
> **HTTPS** para que a instalação fique disponível.

## Instalação em produção

Ver **[install/INSTALL.md](install/INSTALL.md)** — cobre Linux (systemd) e Windows
(serviço com Virtual Service Account), token via variável de ambiente, conta de
serviço sem privilégios e validação com `--dry-run` antes de ativar o envio.

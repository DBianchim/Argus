# Deploy da Central do Argus (Docker Compose)

Guia para instalar a **central** do Argus (API + banco + dashboard) em um servidor
da empresa. O modelo é **on-premise**: cada empresa tem a sua própria instalação na
rede interna. Os **agentes** são instalados à parte, em cada servidor monitorado
(ver [INSTALL.md](INSTALL.md)).

A central é empacotada em três contêineres orquestrados pelo Docker Compose:

| Serviço | O quê | Exposto na rede? |
|---------|-------|------------------|
| `db`    | PostgreSQL 18 (dados em volume persistente) | Não (só rede interna) |
| `api`   | FastAPI + dashboard buildado (deploy único) | Não (só via Caddy) |
| `caddy` | Reverse proxy + HTTPS                       | **Sim — portas 80/443** |

Todos sobem com `restart: unless-stopped` → a central inicia sozinha no boot da
máquina e se recupera de quedas. **Tudo roda sozinho após o deploy.**

---

## Pré-requisitos

- **Docker** + **Docker Compose** (Docker Desktop no Windows/macOS, ou Docker
  Engine + plugin compose no Linux).
- As portas **80** e **443** livres no host.
- Acesso de rede dos servidores monitorados (agentes) até a central.

---

## Caminho rápido (Windows) — script guiado

Em vez dos passos manuais abaixo, na raiz do projeto rode:

```powershell
.\install\install-central.ps1
```

Ele verifica o Docker, gera o `.env` com segredos fortes (perguntando só o
`ARGUS_HOST`), sobe a central, espera ficar saudável, cria o primeiro usuário do
dashboard e imprime a URL de acesso + o comando para instalar agentes. Os passos
manuais a seguir continuam válidos (e servem para Linux ou para entender o que o
script faz).

---

## Passo a passo (manual)

### 1. Configurar os segredos

Na raiz do projeto, crie o arquivo `.env` a partir do template e preencha com
valores **fortes e únicos desta instalação**:

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
```
```bash
# Linux
cp .env.example .env
```

Gere segredos fortes (um para cada variável):

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Edite o `.env`:
```
POSTGRES_PASSWORD=<segredo gerado 1>
DASHBOARD_TOKEN=<segredo gerado 2>
```

> O `.env` **não é versionado** (contém segredos). Guarde os valores em um cofre
> de senhas. Para trocar a senha do banco depois, é preciso recriar o volume ou
> alterar a senha dentro do Postgres — planeje antes.

### 2. Subir a central

```bash
docker compose up -d --build
```

O primeiro build compila o dashboard e instala a API (alguns minutos). Em
seguida, o contêiner da API roda as migrations (`alembic upgrade head`)
automaticamente e inicia.

Confira o estado:
```bash
docker compose ps          # db e api devem ficar "healthy"; caddy "running"
docker compose logs api    # deve mostrar "Migrations OK" e o loop de OFFLINE
```

### 3. Criar o primeiro usuário e registrar servidores

```bash
# Primeiro administrador do dashboard (senha pedida de forma segura no terminal):
docker compose exec api python manage.py create-user --username admin --role admin

# Registrar cada servidor monitorado — o token é exibido UMA vez, copie-o:
docker compose exec api python manage.py create-server --hostname SRV01 --os linux
```

Use o token retornado ao instalar o agente naquele servidor (ver abaixo).

Após o primeiro acesso, servidores e usuários também podem ser gerenciados pelo
dashboard: **Configurações → Adicionar servidor** (papel `operator` ou `admin`) e
**Minha conta → Usuários** (somente `admin`). Papéis disponíveis: `viewer`
(somente leitura), `operator` (gerencia servidores e configuração) e `admin`
(inclui gestão de usuários).

### 4. Acessar

Abra `https://<ip-ou-nome-da-central>` (ou `https://localhost` se for na própria
máquina). Faça login com o usuário criado.

### 5. Instalar os agentes (bootstrap pela central)

Com a central no ar, cada servidor monitorado se instala com **um comando** que
baixa tudo da central (código + CA), sem copiar arquivos. Troque `<central>` pelo
`ARGUS_HOST` e `<token>` pelo token do passo 3:

```bash
# Linux
curl -fsSL http://<central>/install/install.sh \
  | sudo ARGUS_HOST=<central> ARGUS_TOKEN=<token> bash
```
```powershell
# Windows (PowerShell como Administrador)
$env:ARGUS_HOST="<central>"; $env:ARGUS_TOKEN="<token>"; `
  irm "http://$($env:ARGUS_HOST)/install/install.ps1" | iex
```

Detalhes, conceitos e operação dos agentes: **[INSTALL.md](INSTALL.md)**.

---

## HTTPS e a CA do Caddy

Por padrão, o Caddy opera em modo **`tls internal`**: ele gera uma **CA local** e
emite o certificado da central sozinho — sem domínio público, sem comprar
certificado.

> **Defina o hostname de acesso.** O certificado é emitido para o nome em
> `ARGUS_HOST` (default `localhost`). Para acesso de outras máquinas da rede,
> defina `ARGUS_HOST` no `.env` com o nome de rede da central
> (ex.: `argus.empresa.local`) e **acesse sempre por esse mesmo nome** — acesso
> por IP puro não envia SNI e o handshake TLS falha.

Para que os navegadores confiem (cadeado válido, e a PWA fique instalável),
**instale a CA raiz do Caddy** nas máquinas que vão acessar.

Extraia a CA raiz:
```bash
docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt > argus-ca.crt
```

Instale `argus-ca.crt` como **Autoridade de Certificação Raiz Confiável**:
- **Windows**: duplo-clique → "Instalar Certificado" → "Máquina Local" →
  "Autoridades de Certificação Raiz Confiáveis". (Ou via GPO para toda a rede.)
- **Linux**: copie para `/usr/local/share/ca-certificates/` e rode
  `sudo update-ca-certificates`.

Depois disso, `https://<central>` mostra cadeado válido e o Chrome/Edge oferece
**Instalar Argus** (PWA, abre como app próprio).

### Opção nuvem (domínio público)

Se preferir publicar a central em um domínio real, o Caddy emite e renova um
certificado **Let's Encrypt** automaticamente — sem CA local nem instalação de
certificado nos clientes. Defina `ARGUS_HOST` no `.env` com o domínio
(ex.: `argus.suaempresa.com.br`) e **remova a linha `tls internal`** de
`docker/Caddyfile`. Exija DNS apontando para a central e as portas 80/443
acessíveis da internet, e rode `docker compose up -d` de novo.

---

## Operação

```bash
docker compose ps                 # estado dos serviços
docker compose logs -f api        # logs da API ao vivo
docker compose restart api        # reiniciar a API
docker compose down               # parar tudo (dados preservados nos volumes)
docker compose up -d --build      # aplicar atualização do código (rebuild)
```

### Backup do banco

Um quarto serviço, `backup`, faz **dump automático e periódico** do banco (a cada
`BACKUP_INTERVAL_HOURS`, default 24h) e grava em `./backups` — uma pasta do
**host**, não um volume Docker gerenciado, para ficar fácil de copiar para fora
da máquina (rsync, robocopy, sync de nuvem). Um backup que só existe no mesmo
disco da central não protege contra a perda desse disco — **copie `./backups`
para outro lugar periodicamente**; o Argus não faz isso sozinho.

Os dumps contêm dados sensíveis (hashes de senha, tokens), então são gravados
com permissão `600`; em hosts Linux o dono é `root` (o container roda como root),
logo copie `./backups` com `sudo` (ex.: `sudo rsync -a backups/ destino/`).

Dumps antigos são apagados automaticamente após `BACKUP_RETENTION_DAYS` (default
14 dias). Ajuste os dois no `.env` se quiser outro intervalo/retenção.

```bash
docker compose logs -f backup       # acompanhar os dumps
ls backups/                         # arquivos argus-<timestamp>.dump
```

**Restaurar** (⚠️ sobrescreve o banco atual — o script pausa 10s antes de agir):
Pare a `api` antes — ela mantém conexões abertas no banco, o que faz o
`pg_restore --clean` falhar por lock ou restaurar com a aplicação escrevendo no meio:
```bash
docker compose exec backup sh /restore.sh --list                       # ver dumps disponíveis
docker compose stop api
docker compose exec backup sh /restore.sh argus-20260713T220000Z.dump   # restaurar um deles
docker compose start api
```

Para um dump manual avulso (ex.: antes de uma atualização arriscada), sem esperar
o ciclo automático:
```bash
docker compose exec -T db pg_dump -U argus -d argus -Fc > backups/manual-$(date -u +%Y%m%dT%H%M%SZ).dump
```

Faça backup também do volume `argus-caddy-data` (contém a CA local) — se ele for
perdido, a CA muda e os clientes precisam reinstalar o certificado. Este volume
não entra no dump automático (ciclo de vida diferente, muda raramente); copie-o
manualmente quando for renovado.

---

## Manutenção e limites conhecidos

- **Retenção de métricas**: a tabela de métricas cresce continuamente (ingestão
  de todos os agentes). Monitore o espaço em disco do volume `argus-pgdata`. Uma
  política de purga/particionamento por tempo está no roadmap; por ora, acompanhe
  o crescimento e faça backups regulares.
- **Documentação da API** (`/docs`) fica acessível pela rede interna. Em ambientes
  mais restritos, pode-se bloqueá-la no Caddy.
- **Atualizações**: ao alterar o código, rode `docker compose up -d --build` — as
  migrations rodam sozinhas no boot do contêiner da API.

# =============================================================================
# install-central.ps1 - Instalador guiado da CENTRAL do Argus (Windows)
#
# Sobe a central (PostgreSQL + API + Caddy/HTTPS) via Docker Compose, gerando os
# segredos automaticamente e criando o primeiro usuario do dashboard. Transforma
# os passos manuais do install/DEPLOY.md em um unico script.
#
# Uso: na raiz do projeto, em PowerShell:
#     .\install\install-central.ps1
# (nao precisa de Administrador; precisa do Docker Desktop instalado e aberto.)
# =============================================================================

$ErrorActionPreference = 'Stop'

function Info($m){ Write-Host "[INFO]  $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[WARN]  $m" -ForegroundColor Yellow }
function Fail($m){ Write-Host "[ERRO]  $m" -ForegroundColor Red; throw $m }

# Raiz do projeto = pasta acima de install\
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root 'docker-compose.yml'))) {
    Fail "docker-compose.yml nao encontrado em $Root. Rode este script de dentro do projeto Argus."
}
Set-Location $Root

Write-Host ""
Write-Host " ============================================================" -ForegroundColor Cyan
Write-Host "   Argus - Instalador da Central (Docker)" -ForegroundColor Cyan
Write-Host " ============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Docker disponivel? ───────────────────────────────────────────────────────
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker nao encontrado. Instale o Docker Desktop (https://www.docker.com/products/docker-desktop/) e abra-o."
}
try { docker info 2>$null | Out-Null; if ($LASTEXITCODE -ne 0) { throw } }
catch { Fail "O Docker esta instalado mas nao esta rodando. Abra o Docker Desktop, aguarde iniciar e rode de novo." }
Info "Docker disponivel"

# ── .env (segredos) ──────────────────────────────────────────────────────────
function New-Secret { -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 36 | ForEach-Object {[char]$_}) }

$envPath = Join-Path $Root '.env'
if (Test-Path $envPath) {
    Warn ".env ja existe — mantendo os segredos atuais (nao sobrescrevo)."
} else {
    Write-Host ""
    Write-Host "  ENDERECO DE ACESSO da central na rede (o certificado HTTPS sera emitido" -ForegroundColor Gray
    Write-Host "  para este nome). Use o nome/IP que os agentes e navegadores vao acessar." -ForegroundColor Gray
    $argusHost = Read-Host "  ARGUS_HOST [localhost]"
    if (-not $argusHost) { $argusHost = 'localhost' }

    $content = @"
POSTGRES_PASSWORD=$(New-Secret)
DASHBOARD_TOKEN=$(New-Secret)
ARGUS_HOST=$argusHost
"@
    # UTF-8 sem BOM (BOM quebraria a leitura do .env pelo compose)
    [System.IO.File]::WriteAllText($envPath, $content)
    Info ".env gerado com segredos fortes (ARGUS_HOST=$argusHost)"
}

# Le o ARGUS_HOST efetivo do .env (para as mensagens finais)
$argusHost = 'localhost'
foreach ($line in Get-Content $envPath) {
    if ($line -match '^\s*ARGUS_HOST\s*=\s*(.+?)\s*$') { $argusHost = $Matches[1] }
}

# ── subir a stack ────────────────────────────────────────────────────────────
Info "Subindo a central (docker compose up -d --build) — o primeiro build leva alguns minutos..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail "docker compose falhou. Veja a saida acima." }

# ── aguardar a API ficar saudavel ────────────────────────────────────────────
Info "Aguardando a API ficar saudavel (migrations rodam no boot)..."
$healthy = $false
foreach ($i in 1..30) {
    Start-Sleep -Seconds 4
    $st = (docker inspect --format '{{.State.Health.Status}}' argus-api-1 2>$null)
    if ($st -eq 'healthy') { $healthy = $true; break }
}
if ($healthy) { Info "Central no ar e saudavel" }
else { Warn "A API ainda nao reportou 'healthy'. Veja: docker compose logs api" }

# ── primeiro usuario do dashboard ────────────────────────────────────────────
Write-Host ""
$createUser = Read-Host "  Criar agora um usuario de login do dashboard? [S/n]"
if ($createUser -notmatch '^[nN]') {
    $user = Read-Host "  Nome de usuario [admin]"
    if (-not $user) { $user = 'admin' }
    Write-Host "  (a senha sera pedida de forma oculta a seguir)" -ForegroundColor Gray
    docker compose exec api python manage.py create-user --username $user
}

# ── resumo ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host " ============================================================" -ForegroundColor Green
Write-Host "   Central instalada!" -ForegroundColor Green
Write-Host " ============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "   Acesso       : https://$argusHost   (faca login com o usuario criado)"
Write-Host "   Estado       : docker compose ps"
Write-Host "   Logs da API  : docker compose logs -f api"
Write-Host ""
Write-Host "   Registrar um servidor monitorado (gera o token do agente):"
Write-Host "     docker compose exec api python manage.py create-server --hostname SRV01 --os windows" -ForegroundColor Gray
Write-Host ""
Write-Host "   Instalar o agente nesse servidor (PowerShell como Administrador):"
Write-Host "     `$env:ARGUS_HOST=`"$argusHost`"; `$env:ARGUS_TOKEN=`"<token>`"; ``" -ForegroundColor Gray
Write-Host "       irm `"http://$argusHost/install/install.ps1`" | iex" -ForegroundColor Gray
Write-Host ""
Write-Host "   Para cadeado HTTPS valido + instalar a PWA: confie a CA do Caddy nos"
Write-Host "   clientes (ver install/DEPLOY.md)."
Write-Host ""

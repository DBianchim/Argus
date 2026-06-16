# =============================================================================
# install.ps1 - Instalador do agente Argus para Windows (bootstrap pela central)
#
# Uso (PowerShell COMO ADMINISTRADOR), em uma linha:
#   $env:ARGUS_HOST="<central>"; $env:ARGUS_TOKEN="<token>"; `
#     irm "http://$($env:ARGUS_HOST)/install/install.ps1" | iex
#
# O script:
#   1. Baixa a CA e o codigo do agente da central (HTTP, porta 80)
#   2. Instala o Python "para todos os usuarios" se necessario (winget)
#   3. Confia na CA (LocalMachine\Root) e salva uma copia para o agente (ca_cert)
#   4. Instala o agente e o registra como servico (NT SERVICE\argus-agent)
#   5. Grava o token como variavel de ambiente do servico (fora do config.toml)
#   6. Valida a coleta (--dry-run) e inicia o servico
#
# Por que HTTP no download: para confiar no HTTPS da central e preciso pegar a CA
# antes; CA e codigo nao sao segredos. O token e informado aqui (nunca trafega) e
# as metricas vao por HTTPS. Ver install/INSTALL.md.
# =============================================================================

$ErrorActionPreference = 'Stop'

# ── constantes ────────────────────────────────────────────────────────────────
$AppName     = 'argus-agent'
$AppDisplay  = 'Argus - Agente de Monitoramento de Infraestrutura'
$InstallDir  = 'C:\Program Files\Argus\agent-monitor'
$DataDir     = 'C:\ProgramData\Argus\agent-monitor'
$ConfigFile  = Join-Path $DataDir 'config.toml'
$QueueDir    = Join-Path $DataDir 'queue'
$LogDir      = Join-Path $DataDir 'logs'
$CaFile      = Join-Path $DataDir 'argus-ca.crt'

function Info($m){ Write-Host "[INFO]  $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[WARN]  $m" -ForegroundColor Yellow }
function Fail($m){ Write-Host "[ERRO]  $m" -ForegroundColor Red; throw $m }

Write-Host ""
Write-Host " ============================================================" -ForegroundColor Cyan
Write-Host "   Argus Agent - Instalador Windows (bootstrap)" -ForegroundColor Cyan
Write-Host " ============================================================" -ForegroundColor Cyan
Write-Host ""

# ── privilegios de administrador ──────────────────────────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) {
    Fail "Execute em um PowerShell aberto COMO ADMINISTRADOR e rode o comando de novo."
}
Info "Privilegios de Administrador confirmados"

# ── parametros (env vars ou prompt) ─────────────────────────────────────────────
$ArgusHost = $env:ARGUS_HOST
if (-not $ArgusHost) { $ArgusHost = Read-Host "Endereco da central (ex: argus.empresa.local ou localhost)" }
if (-not $ArgusHost) { Fail "ARGUS_HOST nao informado." }

$ArgusToken = $env:ARGUS_TOKEN
if (-not $ArgusToken) {
    $sec = Read-Host "Token do agente (gerado na central com create-server)" -AsSecureString
    $ArgusToken = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
if (-not $ArgusToken) { Fail "Token nao informado." }

$Interval = $env:ARGUS_INTERVAL; if (-not $Interval) { $Interval = '300' }
$Base = "http://$ArgusHost/install"
Info "Central: $ArgusHost"

# ── download dos artefatos (CA + codigo do agente) ──────────────────────────────
$Tmp = Join-Path $env:TEMP "argus-install-$(Get-Random)"
New-Item -ItemType Directory -Path $Tmp -Force | Out-Null
$caTmp  = Join-Path $Tmp 'argus-ca.crt'
$zipTmp = Join-Path $Tmp 'argus-agent.zip'
$srcDir = Join-Path $Tmp 'agent'

Info "Baixando a CA da central..."
Invoke-WebRequest "$Base/ca.crt" -OutFile $caTmp -UseBasicParsing
Info "Baixando o codigo do agente..."
Invoke-WebRequest "$Base/argus-agent.zip" -OutFile $zipTmp -UseBasicParsing
Expand-Archive -Path $zipTmp -DestinationPath $srcDir -Force
Info "Artefatos baixados"

# ── Python "para todos os usuarios" ─────────────────────────────────────────────
function Find-MachinePython {
    $globs = @(
        'C:\Program Files\Python3*\python.exe',
        'C:\Program Files (x86)\Python3*\python.exe',
        'C:\Python3*\python.exe'
    )
    foreach ($g in $globs) {
        $hit = Get-ChildItem $g -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

$Python = Find-MachinePython
if (-not $Python) {
    Warn "Python (todos os usuarios) nao encontrado. Instalando via winget..."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail ("winget indisponivel. Instale o Python 3.11+ marcando 'Install for all users' " +
              "em https://www.python.org/downloads/ e rode o instalador de novo.")
    }
    winget install --id Python.Python.3.12 --scope machine --silent `
        --accept-package-agreements --accept-source-agreements | Out-Null
    $Python = Find-MachinePython
    if (-not $Python) {
        Fail ("Python machine-wide nao encontrado apos a instalacao. Instale 'for all users' " +
              "e rode de novo.")
    }
}
Info "Python: $Python"

# Dependencias do agente (requests) no python da maquina
Info "Instalando dependencias do agente..."
$req = Join-Path $srcDir 'requirements.txt'
if (Test-Path $req) { & $Python -m pip install -r $req --quiet }
else                { & $Python -m pip install requests --quiet }

# ── diretorios de dados ──────────────────────────────────────────────────────────
Info "Criando diretorios de dados..."
New-Item -ItemType Directory -Path $DataDir  -Force | Out-Null
New-Item -ItemType Directory -Path $QueueDir -Force | Out-Null
New-Item -ItemType Directory -Path $LogDir   -Force | Out-Null
# Normaliza permissoes de arquivos de execucoes anteriores: uma instalacao que falhou
# no meio pode ter deixado a ACL travada (ate para o Administrador). Como o Admin e
# dono, o /reset restaura o acesso herdado e torna o script re-executavel, permitindo
# (re)gravar CA/config/token abaixo. As permissoes finais sao aplicadas no fim.
icacls $DataDir /reset /T /C /Q | Out-Null

# ── confiar na CA + copia para o agente ─────────────────────────────────────────
Info "Instalando a CA da central no repositorio confiavel (LocalMachine\Root)..."
Import-Certificate -FilePath $caTmp -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
Copy-Item $caTmp $CaFile -Force
Info "CA confiada e copiada para $CaFile"

# ── instalar o codigo do agente ─────────────────────────────────────────────────
Info "Instalando binarios em $InstallDir..."
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item (Join-Path $srcDir '*') $InstallDir -Recurse -Force

# ── gerar config.toml (com ca_cert; sem token) ──────────────────────────────────
Info "Gerando config.toml..."
if (Test-Path $ConfigFile) {
    Copy-Item $ConfigFile "$ConfigFile.bak.$(Get-Date -Format yyyyMMdd_HHmmss)" -Force
    Warn "Config anterior salvo como backup"
}
$cfg = @"
# =============================================================================
# config.toml - Argus Agent (gerado pelo install.ps1)
#
# SEGURANCA: api_token fica vazio. O token vem da variavel AGENT_API_TOKEN,
# lida de um arquivo protegido (agent.token) pelo lancador da Tarefa Agendada.
# =============================================================================

[global]
api_url   = "https://$ArgusHost"
api_token = ""
hostname  = ""
# CA interna da central (Caddy tls internal). O agente Python valida o HTTPS
# contra este arquivo (nao usa o repositorio de certificados do Windows).
ca_cert   = "$($CaFile -replace '\\','\\')"

[schedule]
interval_seconds = $Interval

[retry]
max_attempts    = 3
backoff_seconds = 10
http_timeout    = 10
queue_path      = "$($QueueDir -replace '\\','\\')"
queue_max_size  = 1000

[operacional]
enabled        = true
cpu_threshold  = 90
mem_threshold  = 85
disk_threshold = 90
critical_services_windows = ["W3SVC", "MSSQLSERVER", "LanmanServer", "WinRM"]

[backup]
enabled       = true
sla_hours     = 24
min_size_mb   = 5
extensions    = [".tar.gz", ".zip", ".dump", ".vhd", ".vhdx"]
paths_windows = ["E:\\Backups", "D:\\Backups"]

[acesso]
enabled = true

[logs]
enabled = true
"@
# UTF-8 SEM BOM: o `Set-Content -Encoding UTF8` do PowerShell 5.1 adiciona um BOM
# que o parser TOML (tomllib) rejeita ("Invalid statement at line 1, column 1").
# WriteAllText grava UTF-8 sem BOM.
[System.IO.File]::WriteAllText($ConfigFile, $cfg)
Info "config.toml gerado em $ConfigFile (com ca_cert, sem token)"

# ── token em arquivo protegido + lancador ────────────────────────────────────────
# O runner.py NAO e um Servico nativo do Windows (nao fala o protocolo do SCM),
# entao rodamos via Tarefa Agendada como SYSTEM, iniciada no boot. O token fica
# num arquivo (agent.token), lido em runtime pelo lancador — fora do config.toml.
$TokenFile = Join-Path $DataDir 'agent.token'
Set-Content -Path $TokenFile -Value $ArgusToken -Encoding ASCII -NoNewline

# Lancador: le o token do arquivo, exporta como AGENT_API_TOKEN e chama o runner.
$LauncherFile = Join-Path $InstallDir 'run-agent.ps1'
$launcher = @"
`$env:AGENT_API_TOKEN = (Get-Content '$TokenFile' -Raw).Trim()
& '$Python' '$InstallDir\runner.py' --config '$ConfigFile'
"@
[System.IO.File]::WriteAllText($LauncherFile, $launcher)

# ── proteger APENAS o token (o unico segredo) ─────────────────────────────────────
# Nao mexemos na ACL da pasta: o C:\ProgramData ja concede SYSTEM:F e
# Administradores:F por heranca, entao a Tarefa (SYSTEM) le config/CA e escreve
# logs/fila normalmente. config.toml e a CA nao sao segredos. So o token precisa
# ficar fora do alcance de usuarios comuns: removemos a heranca e deixamos apenas
# SYSTEM e Administradores (SIDs bem-conhecidos, independem do idioma do Windows):
#   *S-1-5-18 = SYSTEM | *S-1-5-32-544 = BUILTIN\Administradores
Info "Protegendo o arquivo de token (SYSTEM + Administradores)..."
icacls $TokenFile /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" /C /Q | Out-Null

# ── remover instalacoes antigas (servico e/ou tarefa) ────────────────────────────
if (Get-Service $AppName -ErrorAction SilentlyContinue) {
    Warn "Removendo servico antigo (migrando para Tarefa Agendada)"
    & sc.exe stop $AppName   | Out-Null
    & sc.exe delete $AppName | Out-Null
}
if (Get-ScheduledTask -TaskName $AppName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $AppName -Confirm:$false -ErrorAction SilentlyContinue
}

# ── Tarefa Agendada (SYSTEM, inicia no boot, reinicia em falha) ───────────────────
Info "Registrando a Tarefa Agendada (conta SYSTEM, inicio no boot)..."
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$LauncherFile`""
$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $AppName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings `
    -Description 'Argus - coleta e envia metricas de monitoramento para a central.' -Force | Out-Null
Info "Tarefa '$AppName' registrada"

# ── validar coleta (dry-run) ─────────────────────────────────────────────────────
Info "Validando a coleta (dry-run, sem enviar)..."
$env:AGENT_API_TOKEN = $ArgusToken
& $Python "$InstallDir\runner.py" --config $ConfigFile --dry-run --log-level WARNING
Remove-Item Env:\AGENT_API_TOKEN -ErrorAction SilentlyContinue
Info "Dry-run concluido (exit!=0 pode ser esperado: findings com status=error)"

# ── iniciar agora (alem do boot) ──────────────────────────────────────────────────
if ($args -notcontains '--no-start') {
    Info "Iniciando a tarefa..."
    Start-ScheduledTask -TaskName $AppName
    Start-Sleep -Seconds 6
    $state = (Get-ScheduledTask -TaskName $AppName).State
    $proc  = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -EA SilentlyContinue |
             Where-Object { $_.CommandLine -match 'runner\.py' }
    if ($proc) { Info "Agente em execucao (tarefa: $state, pid: $($proc.ProcessId))" }
    else { Warn "Agente nao detectado em execucao (tarefa: $state). Veja $LogDir\agent-monitor.log" }
} else {
    Warn "--no-start ativo. Para iniciar: Start-ScheduledTask -TaskName $AppName"
}

# ── limpeza ──────────────────────────────────────────────────────────────────────
Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host " ============================================================" -ForegroundColor Green
Write-Host "   Argus Agent instalado!" -ForegroundColor Green
Write-Host " ============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "   Central       : https://$ArgusHost"
Write-Host "   Binarios      : $InstallDir"
Write-Host "   Config        : $ConfigFile (ca_cert; sem token)"
Write-Host "   Token         : $TokenFile (SYSTEM + Admins)"
Write-Host "   CA confiada   : LocalMachine\Root + $CaFile"
Write-Host "   Logs          : $LogDir"
Write-Host ""
Write-Host "   Execucao      : Tarefa Agendada '$AppName' (conta SYSTEM, inicia no boot)"
Write-Host "   Status        : Get-ScheduledTask -TaskName $AppName"
Write-Host "   Logs          : Get-Content '$LogDir\agent-monitor.log' -Tail 30"
Write-Host "   Reiniciar     : Stop-ScheduledTask $AppName; Start-ScheduledTask $AppName"
Write-Host "   Desinstalar   : Unregister-ScheduledTask -TaskName $AppName -Confirm:`$false"
Write-Host ""

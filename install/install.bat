@echo off
REM =============================================================================
REM install.bat — Instalador do agente Argus para Windows
REM
REM O que este script faz:
REM   1. Verifica privilegios de Administrador
REM   2. Verifica Python 3.11+ — instala via winget se ausente
REM   3. Verifica arquivos do agente (estrutura core\ + 4 agentes)
REM   4. Copia binarios para C:\Program Files\Argus\agent-monitor\ (incl. core\)
REM   5. Instala dependencias Python (requests)
REM   6. Cria diretorios de dados em C:\ProgramData\Argus\agent-monitor\
REM   7. Solicita URL da API e token ao operador
REM   8. Gera config.toml SEM o token (api_token vazio)
REM   9. Registra o servico com Virtual Service Account (sem LocalSystem)
REM  10. Grava o token como variavel de ambiente do servico (registro)
REM  11. Restringe ACLs dos diretorios de dados
REM  12. Inicia o servico e exibe o status final
REM
REM Seguranca:
REM   - O token NUNCA fica no config.toml. Vive como variavel de ambiente
REM     exclusiva do servico (AGENT_API_TOKEN) e e injetado em runtime.
REM   - O servico roda como Virtual Service Account, nao como LocalSystem.
REM
REM Uso (como Administrador):
REM   install.bat
REM   install.bat --no-start
REM
REM Autores: Equipe de Infraestrutura — Argus
REM =============================================================================

setlocal EnableDelayedExpansion

REM ── constantes ────────────────────────────────────────────────────────────────

set APP_NAME=argus-agent
set APP_DISPLAY=Argus - Agente de Monitoramento de Infraestrutura
set INSTALL_DIR=C:\Program Files\Argus\agent-monitor
set DATA_DIR=C:\ProgramData\Argus\agent-monitor
set CONFIG_FILE=%DATA_DIR%\config.toml
set QUEUE_DIR=%DATA_DIR%\queue
set LOG_DIR=%DATA_DIR%\logs

REM Argumento --no-start
set NO_START=0
for %%a in (%*) do if "%%a"=="--no-start" set NO_START=1

echo.
echo  ============================================================
echo    Argus Agent — Instalador Windows
echo  ============================================================
echo.

REM ── verificacao de privilegios ────────────────────────────────────────────────

echo [INFO]  Verificando privilegios de Administrador...
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRO]  Execute como Administrador.
    echo         Clique com o botao direito em install.bat e selecione
    echo         "Executar como administrador".
    pause & exit /b 1
)
echo [INFO]  Privilegios de Administrador confirmados

REM ── verificacao e instalacao do Python ───────────────────────────────────────

echo.
echo [INFO]  Verificando Python 3.11+...

python --version >nul 2>&1
if %errorLevel% neq 0 goto install_python

REM Valida versao minima
python -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if %errorLevel% equ 0 goto python_ok

:install_python
echo [WARN]  Python 3.11+ nao encontrado. Tentando instalar via winget...

REM Verifica se winget esta disponivel (Windows 10 1709+ / Server 2022+)
winget --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [WARN]  winget nao disponivel neste sistema.
    echo.
    echo  Instale o Python 3.11 manualmente:
    echo    1. Acesse: https://www.python.org/downloads/
    echo    2. Baixe o instalador do Python 3.11 ou superior
    echo    3. Execute e marque "Add Python to PATH"
    echo    4. Apos instalar, execute este instalador novamente
    echo.
    pause & exit /b 1
)

echo [INFO]  Instalando Python via winget...
winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
if %errorLevel% neq 0 (
    echo [ERRO]  Falha ao instalar Python via winget.
    echo         Instale manualmente em: https://www.python.org/downloads/
    pause & exit /b 1
)

REM Recarrega o PATH para reconhecer o Python recem instalado
call refreshenv >nul 2>&1

python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRO]  Python instalado mas nao encontrado no PATH.
    echo         Feche este terminal, abra um novo e execute o instalador novamente.
    pause & exit /b 1
)

:python_ok
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYTHON_VER=%%v
echo [INFO]  Python %PYTHON_VER% pronto

REM ── verificacao dos arquivos do agente ────────────────────────────────────────

echo.
echo [INFO]  Verificando arquivos do agente...
set MISSING=0
cd /d "%~dp0"
for %%f in (runner.py scheduler.py agent_operacional.py agent_backup.py agent_acesso.py agent_logs.py) do (
    if not exist ".\%%f" (
        echo [ERRO]  Arquivo ausente: %%f
        set MISSING=1
    )
)
for %%f in (__init__.py config_loader.py sender.py queue_local.py) do (
    if not exist ".\core\%%f" (
        echo [ERRO]  Arquivo ausente: core\%%f
        set MISSING=1
    )
)
if %MISSING%==1 (
    echo [ERRO]  Execute o instalador na pasta agents\ que contem os arquivos do agente.
    pause & exit /b 1
)
echo [INFO]  Todos os arquivos encontrados ^(estrutura core\ + 4 agentes^)

REM ── criacao dos diretorios ────────────────────────────────────────────────────

echo.
echo [INFO]  Criando diretorios...

if not exist "%INSTALL_DIR%"      mkdir "%INSTALL_DIR%"
if not exist "%INSTALL_DIR%\core" mkdir "%INSTALL_DIR%\core"
echo [INFO]  Binarios     : %INSTALL_DIR%

if not exist "%DATA_DIR%"    mkdir "%DATA_DIR%"
if not exist "%QUEUE_DIR%"   mkdir "%QUEUE_DIR%"
if not exist "%LOG_DIR%"     mkdir "%LOG_DIR%"
echo [INFO]  Dados        : %DATA_DIR%
echo [INFO]  Fila local   : %QUEUE_DIR%
echo [INFO]  Logs         : %LOG_DIR%

REM ── copia dos binarios ────────────────────────────────────────────────────────

echo.
echo [INFO]  Copiando binarios...
for %%f in (runner.py scheduler.py agent_operacional.py agent_backup.py agent_acesso.py agent_logs.py) do (
    copy /Y ".\%%f" "%INSTALL_DIR%\%%f" >nul
    echo [INFO]    %%f
)
for %%f in (__init__.py config_loader.py sender.py queue_local.py) do (
    copy /Y ".\core\%%f" "%INSTALL_DIR%\core\%%f" >nul
    echo [INFO]    core\%%f
)
echo [INFO]  Binarios instalados em %INSTALL_DIR%

REM ── dependencias Python ───────────────────────────────────────────────────────

echo.
echo [INFO]  Instalando dependencias Python...

REM Dependencias (requests; tomli em Python^<3.11) em requirements.txt
if exist ".\requirements.txt" (
    pip install -r ".\requirements.txt" -q
    if %errorLevel% neq 0 (
        echo [ERRO]  Falha ao instalar dependencias de requirements.txt.
        pause & exit /b 1
    )
    echo [INFO]  Dependencias instaladas a partir de requirements.txt
) else (
    echo [AVISO] requirements.txt nao encontrado — instalando requests diretamente
    pip install requests -q
    if %errorLevel% neq 0 (
        echo [ERRO]  Falha ao instalar requests.
        pause & exit /b 1
    )
)

REM ── coleta de parametros ──────────────────────────────────────────────────────

echo.
echo  ── Configuracao do agente ───────────────────────────────────────────────────
echo.
echo   Informe os parametros de conexao com o sistema central Argus.
echo   Pressione ENTER para usar o valor padrao indicado entre colchetes.
echo.

:input_url
set /p API_URL="  URL da API central [http://localhost:8000]: "
if "!API_URL!"=="" set API_URL=http://localhost:8000
echo !API_URL! | findstr /r "^http" >nul
if %errorLevel% neq 0 (
    echo [WARN]  URL invalida. Deve comecar com http:// ou https://
    goto input_url
)

:input_token
set /p API_TOKEN="  Token de autenticacao: "
if "!API_TOKEN!"=="" (
    echo [WARN]  Token nao pode estar vazio
    goto input_token
)

set /p INTERVAL="  Intervalo de coleta em segundos [300]: "
if "!INTERVAL!"=="" set INTERVAL=300

echo.
echo [INFO]  Parametros coletados

REM ── geracao do config.toml ────────────────────────────────────────────────────

echo.
echo [INFO]  Gerando config.toml...

if exist "%CONFIG_FILE%" (
    for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set DT=%%c%%a%%b
    copy /Y "%CONFIG_FILE%" "%CONFIG_FILE%.bak.%DT%" >nul
    echo [WARN]  Config anterior salvo como backup
)

(
echo # =============================================================================
echo # config.toml - Argus Agent
echo # Gerado automaticamente pelo install.bat
echo #
echo # SEGURANCA: api_token fica vazio de proposito. O token e fornecido pela
echo # variavel de ambiente AGENT_API_TOKEN, definida no escopo do servico
echo # ^(registro: HKLM\SYSTEM\CurrentControlSet\Services\%APP_NAME%\Environment^).
echo # =============================================================================
echo.
echo [global]
echo api_url   = "!API_URL!"
echo api_token = ""
echo hostname  = ""
echo.
echo [schedule]
echo interval_seconds = !INTERVAL!
echo.
echo [retry]
echo max_attempts    = 3
echo backoff_seconds = 10
echo http_timeout    = 10
echo queue_path      = "C:\\ProgramData\\Argus\\agent-monitor\\queue"
echo queue_max_size  = 1000
echo.
echo [operacional]
echo enabled        = true
echo cpu_threshold  = 90
echo mem_threshold  = 85
echo disk_threshold = 90
echo critical_services_windows = ["W3SVC", "MSSQLSERVER", "LanmanServer", "WinRM"]
echo.
echo [backup]
echo enabled       = true
echo sla_hours     = 24
echo min_size_mb   = 5
echo extensions    = [".tar.gz", ".zip", ".dump", ".vhd", ".vhdx"]
echo paths_windows = ["E:\\Backups", "D:\\Backups"]
echo.
echo [acesso]
echo enabled = true
echo.
echo [logs]
echo enabled = true
) > "%CONFIG_FILE%"

echo [INFO]  config.toml gerado em %CONFIG_FILE% ^(sem token^)

REM ── registro do servico Windows ───────────────────────────────────────────────

echo.
echo [INFO]  Registrando servico Windows...

sc query "%APP_NAME%" >nul 2>&1
if %errorLevel% equ 0 (
    echo [WARN]  Servico existente encontrado — removendo para reinstalar
    sc stop "%APP_NAME%" >nul 2>&1
    timeout /t 3 /nobreak >nul
    sc delete "%APP_NAME%" >nul 2>&1
    timeout /t 2 /nobreak >nul
)

for /f "tokens=*" %%p in ('where python') do set PYTHON_PATH=%%p

REM Virtual Service Account "NT SERVICE\%APP_NAME%": conta gerenciada pelo
REM Windows, sem senha manual e com privilegios minimos. Mais segura que
REM LocalSystem (que tem privilegio total na maquina).
sc create "%APP_NAME%" ^
    binPath= "\"%PYTHON_PATH%\" \"%INSTALL_DIR%\runner.py\" --config \"%CONFIG_FILE%\"" ^
    DisplayName= "%APP_DISPLAY%" ^
    start= auto ^
    obj= "NT SERVICE\%APP_NAME%" >nul

if %errorLevel% neq 0 (
    echo [ERRO]  Falha ao registrar o servico.
    pause & exit /b 1
)

sc description "%APP_NAME%" "Argus — coleta e envia metricas de monitoramento para o sistema central." >nul
sc failure "%APP_NAME%" reset= 86400 actions= restart/30000/restart/60000/restart/120000 >nul
echo [INFO]  Servico registrado ^(Virtual Service Account, inicio automatico, reinicio em falha^)

REM ── token via variavel de ambiente do servico ─────────────────────────────────

echo.
echo [INFO]  Definindo AGENT_API_TOKEN no escopo do servico...

REM O token e gravado como variavel de ambiente exclusiva do servico, no
REM registro (REG_MULTI_SZ). Nao fica no config.toml. Apenas o processo do
REM servico (e Administradores) consegue ler esta chave.
reg add "HKLM\SYSTEM\CurrentControlSet\Services\%APP_NAME%" ^
    /v Environment /t REG_MULTI_SZ /d "AGENT_API_TOKEN=!API_TOKEN!" /f >nul

if %errorLevel% neq 0 (
    echo [ERRO]  Falha ao definir o token no registro do servico.
    pause & exit /b 1
)
echo [INFO]  Token definido como variavel de ambiente do servico ^(fora do config.toml^)

REM ── restricao de ACL nos diretorios ───────────────────────────────────────────

echo.
echo [INFO]  Restringindo permissoes...
REM Fila e config acessiveis apenas pelo servico, SYSTEM e Administradores.
icacls "%DATA_DIR%" /inheritance:r >nul 2>&1
icacls "%DATA_DIR%" /grant "NT SERVICE\%APP_NAME%:(OI)(CI)M" "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" >nul 2>&1
echo [INFO]  Permissoes aplicadas em %DATA_DIR%

REM ── inicio do servico ─────────────────────────────────────────────────────────

if %NO_START%==0 (
    echo.
    echo [INFO]  Iniciando o servico...
    sc start "%APP_NAME%" >nul
    timeout /t 3 /nobreak >nul

    sc query "%APP_NAME%" | findstr "RUNNING" >nul
    if %errorLevel% equ 0 (
        echo [INFO]  Servico iniciado com sucesso
    ) else (
        echo [ERRO]  Servico nao iniciou. Verifique os logs em:
        echo         %LOG_DIR%
        pause & exit /b 1
    )
) else (
    echo [WARN]  Opcao --no-start ativa — servico nao iniciado
    echo [INFO]  Para iniciar: sc start %APP_NAME%
)

REM ── resumo final ──────────────────────────────────────────────────────────────

echo.
echo  ============================================================
echo    Argus Agent instalado com sucesso!
echo  ============================================================
echo.
echo   Binarios        : %INSTALL_DIR%
echo   Configuracao    : %CONFIG_FILE% (sem token)
echo   Token           : variavel de ambiente do servico (registro)
echo   Logs            : %LOG_DIR%
echo   Fila local      : %QUEUE_DIR%
echo.
echo   Comandos uteis:
echo     Status        : sc query %APP_NAME%
echo     Ver logs      : type "%LOG_DIR%\argus-agent.log"
echo     Parar         : sc stop %APP_NAME%
echo     Reiniciar     : sc stop %APP_NAME% ^& sc start %APP_NAME%
echo     Rotacionar token : reg add "HKLM\SYSTEM\CurrentControlSet\Services\%APP_NAME%" /v Environment /t REG_MULTI_SZ /d "AGENT_API_TOKEN=novo-token" /f ^& sc stop %APP_NAME% ^& sc start %APP_NAME%
echo     Validar coleta   : python "%INSTALL_DIR%\runner.py" --config "%CONFIG_FILE%" --dry-run
echo     Desinstalar   : sc stop %APP_NAME% ^& sc delete %APP_NAME%
echo.
pause
endlocal

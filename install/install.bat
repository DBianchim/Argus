@echo off
REM =============================================================================
REM install.bat — atalho de compatibilidade para o instalador Windows do Argus.
REM
REM O instalador real e o install.ps1 (PowerShell). O jeito recomendado de
REM instalar e o "bootstrap" pela central, em um PowerShell como Administrador:
REM
REM   $env:ARGUS_HOST="<central>"; $env:ARGUS_TOKEN="<token>"; ^
REM     irm "http://$($env:ARGUS_HOST)/install/install.ps1" | iex
REM
REM Este .bat existe so para quem tem os arquivos localmente e da duplo-clique:
REM ele eleva para Administrador e executa o install.ps1 ao lado. O script vai
REM perguntar o endereco da central e o token, se nao estiverem no ambiente.
REM =============================================================================

REM Eleva para Administrador se ainda nao estiver
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Solicitando privilegios de Administrador...
    powershell -Command "Start-Process -Verb RunAs -FilePath cmd -ArgumentList '/c','\"%~f0\"'"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause

# Instalação dos Agentes Argus (bootstrap pela central)

Cada **servidor monitorado** roda um agente que coleta métricas e as envia para a
**central**. A instalação é feita com **um único comando** que baixa tudo da própria
central — sem copiar arquivos nem extrair certificado à mão.

> Pré-requisito: a central já deve estar no ar (ver [DEPLOY.md](DEPLOY.md)).

---

## Passo 1 — Na central: registrar o servidor e pegar o token

Para cada servidor que será monitorado, gere um token (exibido **uma única vez**):

```bash
docker compose exec api python manage.py create-server --hostname SRV-WEB-01 --os linux
# ⮕ copie o token retornado
```

---

## Passo 2 — No servidor monitorado: um comando

Troque `<central>` pelo nome/IP da central (o mesmo `ARGUS_HOST` do deploy) e
`<token>` pelo token do passo 1.

### Linux

```bash
curl -fsSL http://<central>/install/install.sh \
  | sudo ARGUS_HOST=<central> ARGUS_TOKEN=<token> bash
```

### Windows (PowerShell **como Administrador**)

```powershell
$env:ARGUS_HOST="<central>"; $env:ARGUS_TOKEN="<token>"; `
  irm "http://$($env:ARGUS_HOST)/install/install.ps1" | iex
```

Pronto. O agente é instalado como **serviço** (systemd no Linux, serviço do Windows),
sobe no boot, valida a coleta e começa a enviar por HTTPS. Em ~1 min o servidor
aparece online no dashboard.

> Sem passar as variáveis, o script **pergunta** o endereço da central e o token.
> No Windows, quem tem os arquivos localmente pode dar duplo-clique em `install.bat`
> (ele eleva e chama o `install.ps1`).

---

## O que o instalador faz (e por quê) — para você replicar

```
SERVIDOR-ALVO                                CENTRAL (Docker: caddy + api)
  comando único ───── HTTP/80 ─────────────▶ /install/install.(ps1|sh)  script
                                              /install/argus-agent.zip   código
                                              /install/ca.crt            CA do Caddy
  baixa CA + código
  confia na CA + salva p/ o agente (ca_cert)
  instala Python (all-users no Win) + serviço
  envia métricas ──── HTTPS/443 (valida CA) ─▶ /api/v1/ingest
```

Três conceitos importantes:

1. **Por que o download é por HTTP (porta 80)?**
   Para confiar no HTTPS da central, o servidor precisa **primeiro** ter a CA — mas
   baixá-la por HTTPS exigiria já confiar nela (ovo e galinha). A CA e o código do
   agente **não são segredos**, então o download inicial vai por HTTP. O **token** é
   informado no servidor-alvo (nunca trafega no download) e as **métricas vão por
   HTTPS**. Em modo nuvem (domínio público), até o download é HTTPS.

2. **Por que `ca_cert` no agente?**
   O agente é Python (`requests`), que valida o certificado contra a sua própria lista
   (`certifi`), **não** contra o repositório de certificados do sistema operacional.
   Por isso o instalador salva a CA da central e aponta `ca_cert` para ela no
   `config.toml`. (No Windows, a CA também é instalada no trust do SO, para o navegador.)

3. **Por que Python "para todos os usuários" no Windows?**
   A execução roda como conta **SYSTEM**, que **não acessa o perfil de um usuário**.
   Se o Python estiver em `C:\Users\<voce>\...`, falha com "Acesso negado". O
   instalador garante um Python em `C:\Program Files\...`.

4. **Por que Tarefa Agendada no Windows (e não um Serviço)?**
   Um Serviço do Windows precisa "falar" o protocolo do gerenciador de serviços (SCM)
   e reportar "estou no ar" em até 30s. O `runner.py` é um script comum — não faz isso,
   então como Serviço ele seria morto com timeout (erro 1053). A solução nativa é uma
   **Tarefa Agendada** iniciada no boot, rodando como **SYSTEM** (que também consegue
   ler o **log de Segurança** do Windows, usado pelos pilares *acesso* e *logs*). No
   Linux, o systemd não exige esse protocolo, então lá é um serviço systemd normal.

---

## Modelo de segurança

- **Token nunca no `config.toml`.** Fica em arquivo protegido, lido em runtime:
  - Linux: `/etc/argus/agent-monitor/agent.env` (chmod 600, dono root), via systemd.
  - Windows: `C:\ProgramData\Argus\agent-monitor\agent.token` (ACL só SYSTEM +
    Administradores), lido pelo lançador da Tarefa Agendada.
- **Conta de execução:**
  - Linux: usuário `argus-agent` (nologin), com hardening do systemd
    (`NoNewPrivileges`, `ProtectSystem=strict`).
  - Windows: Tarefa Agendada como **SYSTEM** — privilegiada, mas necessária para ler o
    log de Segurança; o token e os dados ficam restritos a SYSTEM/Administradores.
- **HTTPS sempre** para as métricas (token e dados criptografados em trânsito).

---

## Operação

**Linux (systemd):**
```bash
systemctl status argus-agent        # estado
journalctl -u argus-agent -f        # logs ao vivo
systemctl restart argus-agent       # reiniciar
```

**Windows (PowerShell):**
```powershell
Get-ScheduledTask -TaskName argus-agent | Get-ScheduledTaskInfo   # estado/ultima exec.
Get-Content 'C:\ProgramData\Argus\agent-monitor\logs\agent-monitor.log' -Tail 30
Stop-ScheduledTask -TaskName argus-agent; Start-ScheduledTask -TaskName argus-agent
```

### Rotacionar o token (sem reinstalar)

**Linux:** edite `/etc/argus/agent-monitor/agent.env` e `systemctl restart argus-agent`.

**Windows:**
```powershell
Set-Content 'C:\ProgramData\Argus\agent-monitor\agent.token' -Value 'novo-token' -NoNewline
Stop-ScheduledTask -TaskName argus-agent; Start-ScheduledTask -TaskName argus-agent
```

### Desinstalar

**Linux:**
```bash
sudo systemctl stop argus-agent && sudo systemctl disable argus-agent
sudo rm /etc/systemd/system/argus-agent.service && sudo systemctl daemon-reload
sudo rm -rf /opt/argus /etc/argus /var/lib/argus /var/log/argus
sudo userdel argus-agent
```

**Windows (PowerShell admin):**
```powershell
Unregister-ScheduledTask -TaskName argus-agent -Confirm:$false
Remove-Item -Recurse -Force 'C:\Program Files\Argus','C:\ProgramData\Argus'
```

---

## Validar a coleta sem enviar (dry-run)

O instalador já roda um `--dry-run` ao final. Para rodar manualmente depois:

**Linux:**
```bash
sudo runuser -u argus-agent -- python3 /opt/argus/agent-monitor/runner.py \
  --config /etc/argus/agent-monitor/config.toml --dry-run
```
**Windows:**
```powershell
& "C:\Program Files\Python312\python.exe" "C:\Program Files\Argus\agent-monitor\runner.py" `
  --config "C:\ProgramData\Argus\agent-monitor\config.toml" --dry-run
```
Exit `0` = tudo coletado; exit `1` = algum finding com `status=error` (pode ser
esperado, ex.: falta de permissão de auditoria).

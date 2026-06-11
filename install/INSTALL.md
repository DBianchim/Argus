# Instalação Segura do Argus Agent

Guia de instalação do agente de monitoramento Argus em servidores **Linux** e
**Windows**, com foco em segurança: token fora de arquivos de configuração,
conta de serviço sem privilégios e validação antes de ativar o envio.

---

## Pré-requisitos

| Item | Linux | Windows |
|------|-------|---------|
| Python | 3.11+ (instalado automaticamente) | 3.11+ (via winget) |
| Dependências | `requests` (+ `tomli` se Python < 3.11) | `requests` |
| Privilégio | `root` (sudo) | Administrador |
| Gerenciador de serviço | systemd | Serviços do Windows (sc.exe) |

Os instaladores cuidam de Python e dependências automaticamente.

---

## Modelo de segurança

O ponto central: **o token nunca fica em arquivo de configuração.**

```
config.toml          →  api_token = ""   (sem segredo, pode ser lido pelo grupo)
                         ↓
Linux:   agent.env   →  AGENT_API_TOKEN=... (chmod 600, dono root)
                         → systemd injeta como variável de ambiente
Windows: registro    →  HKLM\...\Services\argus-agent\Environment
                         → o serviço recebe AGENT_API_TOKEN em runtime
```

O agente lê `AGENT_API_TOKEN` da memória do processo. O token só existe em disco
em um arquivo protegido (Linux) ou na chave de serviço do registro (Windows),
nunca no `config.toml` que acompanha o projeto.

Camadas adicionais:

- **Conta dedicada sem login**: `argus-agent` (`nologin`) no Linux / Virtual
  Service Account `NT SERVICE\argus-agent` no Windows. Não há senha para esquecer.
- **Permissões restritas**: fila e config acessíveis apenas pelo serviço.
- **Hardening do systemd**: `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome`, `PrivateTmp`.
- **Token mascarado**: aparece como `argu****` em qualquer log ou traceback.

> **Nota sobre o root (Linux):** o root sempre lê qualquer arquivo — `chown` não
> protege contra um administrador, apenas contra outros usuários/serviços e
> reduz o raio de impacto se o agente for comprometido. O token via env var do
> systemd dificulta mesmo a leitura privilegiada (exige ler `/proc/<pid>/environ`
> do processo ativo, em vez de abrir um arquivo).

---

## Instalação — Linux

Na pasta `agents/` (que contém `runner.py`, `core/`, etc.), com os arquivos do
instalador disponíveis:

```bash
sudo bash install.sh
```

O script vai, em ordem:

1. Verificar/instalar Python 3.11+
2. Criar o usuário `argus-agent` (sem login)
3. Copiar binários para `/opt/argus/agent-monitor/` (incluindo `core/`)
4. Criar diretórios de dados com permissões corretas
5. **Pedir a URL da API e o token** (o token é digitado oculto)
6. Gerar `config.toml` **sem o token**
7. Gravar o token em `/etc/argus/agent-monitor/agent.env` (chmod 600)
8. Registrar o serviço systemd com `EnvironmentFile`
9. **Validar a coleta com `--dry-run`** antes de iniciar
10. Iniciar o serviço

Para instalar sem iniciar (ex.: validar manualmente antes):

```bash
sudo bash install.sh --no-start
```

---

## Instalação — Windows

Como **Administrador**, na pasta `agents\`:

```bat
install.bat
```

Equivalente ao Linux: cria o serviço com Virtual Service Account, grava o token
como variável de ambiente do serviço (registro), restringe ACLs e inicia.

```bat
install.bat --no-start
```

---

## Validar antes de ativar o envio (dry-run)

O modo `--dry-run` executa a coleta de todos os agentes e **imprime os payloads
sem enviar nada** pela rede. Ideal para confirmar, num servidor de produção, que
os agentes coletam corretamente antes de apontar para a API real.

**Linux:**
```bash
sudo runuser -u argus-agent -- \
  python3 /opt/argus/agent-monitor/runner.py \
  --config /etc/argus/agent-monitor/config.toml --dry-run
```

**Windows:**
```bat
python "C:\Program Files\Argus\agent-monitor\runner.py" ^
  --config "C:\ProgramData\Argus\agent-monitor\config.toml" --dry-run
```

- **Exit code 0** → todos os agentes coletaram sem erros.
- **Exit code 1** → algum finding teve `status=error` (revise a saída; pode ser
  esperado, ex.: falta de permissão de auditoria em ambiente restrito).

---

## Rotacionar o token

Sem reinstalar — basta atualizar o segredo e reiniciar o serviço.

**Linux:**
```bash
sudo nano /etc/argus/agent-monitor/agent.env   # edite AGENT_API_TOKEN=...
sudo systemctl restart argus-agent
```

**Windows:**
```bat
reg add "HKLM\SYSTEM\CurrentControlSet\Services\argus-agent" ^
  /v Environment /t REG_MULTI_SZ /d "AGENT_API_TOKEN=novo-token" /f
sc stop argus-agent & sc start argus-agent
```

---

## Verificar permissões

**Linux:**
```bash
ls -l /etc/argus/agent-monitor/agent.env      # -rw------- root root  (600)
ls -l /etc/argus/agent-monitor/config.toml    # -rw-r----- root argus-agent (640)
ls -ld /var/lib/argus/agent-monitor/queue     # drwx------ argus-agent (700)
```

**Windows:**
```bat
icacls "C:\ProgramData\Argus\agent-monitor"
REM Deve listar apenas NT SERVICE\argus-agent, SYSTEM e Administrators
```

---

## Operação

**Linux (systemd):**
```bash
systemctl status argus-agent       # estado do serviço
journalctl -u argus-agent -f       # logs ao vivo
systemctl restart argus-agent      # reiniciar
```

**Windows (sc.exe):**
```bat
sc query argus-agent
type "C:\ProgramData\Argus\agent-monitor\logs\argus-agent.log"
sc stop argus-agent & sc start argus-agent
```

---

## Desinstalar

**Linux:**
```bash
sudo systemctl stop argus-agent
sudo systemctl disable argus-agent
sudo rm /etc/systemd/system/argus-agent.service
sudo systemctl daemon-reload
# Opcional: remover dados e usuário
sudo rm -rf /opt/argus /etc/argus /var/lib/argus /var/log/argus
sudo userdel argus-agent
```

**Windows:**
```bat
sc stop argus-agent & sc delete argus-agent
rmdir /s /q "C:\Program Files\Argus" "C:\ProgramData\Argus"
```

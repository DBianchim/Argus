#!/usr/bin/env bash
# =============================================================================
# install.sh — Instalador do agente Argus para Linux
#
# O que este script faz:
#   1. Verifica privilegios de root
#   2. Verifica Python 3.11+ — instala automaticamente se ausente
#   3. Verifica pip e systemd
#   4. Verifica arquivos do agente (estrutura core/ + 4 agentes)
#   5. Cria usuario dedicado sem shell de login (argus-agent)
#   6. Copia binarios para /opt/argus/agent-monitor/ (incl. core/)
#   7. Instala dependencias Python (requests, tomli se necessario)
#   8. Cria diretorios de dados com permissoes corretas
#   9. Solicita URL da API e token ao operador
#  10. Gera config.toml SEM o token (api_token vazio)
#  11. Grava o token em agent.env protegido (chmod 600, dono root)
#  12. Registra o servico systemd com EnvironmentFile (token via env var)
#  13. Valida a coleta com --dry-run antes de iniciar o envio
#  14. Inicia o servico e exibe o status final
#
# Seguranca:
#   - O token NUNCA fica no config.toml. Vive apenas no agent.env (chmod 600)
#     e e injetado em runtime como AGENT_API_TOKEN pelo systemd.
#   - O agente roda como usuario sem login, com hardening do systemd.
#
# Uso:
#   sudo bash install.sh
#   sudo bash install.sh --no-start
#
# Autores: Equipe de Infraestrutura — Argus
# =============================================================================

set -euo pipefail

# ── constantes ────────────────────────────────────────────────────────────────

APP_NAME="argus-agent"
APP_USER="argus-agent"
INSTALL_DIR="/opt/argus/agent-monitor"
CONFIG_DIR="/etc/argus/agent-monitor"
QUEUE_DIR="/var/lib/argus/agent-monitor/queue"
LOG_DIR="/var/log/argus/agent-monitor"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
ENV_FILE="${CONFIG_DIR}/agent.env"
PYTHON_MIN_VERSION="3.11"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ── utilitarios ───────────────────────────────────────────────────────────────

log_info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERRO]${NC}  $*"; }
log_section() { echo -e "\n${BLUE}── $* ──────────────────────────────────────${NC}"; }

abort() { log_error "$*"; exit 1; }

require_cmd() {
    command -v "$1" &>/dev/null || abort "Comando nao encontrado: $1"
}

version_gte() {
    python3 -c "
import sys
a = tuple(int(x) for x in '$1'.split('.'))
b = tuple(int(x) for x in '$2'.split('.'))
sys.exit(0 if a >= b else 1)
"
}

# ── deteccao da distribuicao Linux ───────────────────────────────────────────

detect_distro() {
    if   command -v apt-get &>/dev/null; then echo "apt"
    elif command -v dnf     &>/dev/null; then echo "dnf"
    elif command -v yum     &>/dev/null; then echo "yum"
    else echo "unknown"
    fi
}

# ── instalacao automatica do Python ──────────────────────────────────────────

install_python() {
    local distro
    distro=$(detect_distro)

    log_warn "Python 3.11+ nao encontrado. Tentando instalar automaticamente..."

    case "$distro" in
        apt)
            log_info "Detectado: Debian/Ubuntu — usando apt-get"
            apt-get update -qq
            apt-get install -y python3 python3-pip
            ;;
        dnf)
            log_info "Detectado: RHEL/CentOS/Fedora — usando dnf"
            dnf install -y python3 python3-pip
            ;;
        yum)
            log_info "Detectado: CentOS 7 — usando yum"
            yum install -y python3 python3-pip
            ;;
        *)
            abort "Gerenciador de pacotes nao identificado.\nInstale o Python 3.11+ manualmente e execute o instalador novamente.\nDownload: https://www.python.org/downloads/"
            ;;
    esac

    # Verifica se a instalacao foi bem-sucedida
    command -v python3 &>/dev/null || abort "Falha ao instalar Python. Instale manualmente e tente novamente."
    log_info "Python instalado com sucesso"
}

# ── verificacao de pre-requisitos ─────────────────────────────────────────────

check_prerequisites() {
    log_section "Verificando pre-requisitos"

    [[ "$EUID" -eq 0 ]] || abort "Execute como root: sudo bash install.sh"

    # Python — instala automaticamente se ausente
    if ! command -v python3 &>/dev/null; then
        install_python
    fi

    # Valida versao minima
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    if ! version_gte "$PYTHON_VERSION" "$PYTHON_MIN_VERSION"; then
        log_warn "Python $PYTHON_VERSION encontrado — versao minima e $PYTHON_MIN_VERSION"
        install_python
        PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    fi
    log_info "Python $PYTHON_VERSION"

    require_cmd pip3
    require_cmd systemctl
    log_info "pip3 e systemd encontrados"

    # Verifica arquivos do agente na pasta atual.
    # Apos a reestruturacao, os modulos compartilhados ficam em core/ e os
    # quatro agentes sao todos integrados ao scheduler.
    local required=("runner.py" "scheduler.py"
                    "agent_operacional.py" "agent_backup.py"
                    "agent_acesso.py" "agent_logs.py"
                    "core/__init__.py" "core/sender.py" "core/queue_local.py"
                    "core/config_loader.py")
    for f in "${required[@]}"; do
        [[ -f "./$f" ]] || abort "Arquivo nao encontrado: $f\nExecute o instalador na pasta agents/ que contem os arquivos do agente."
    done
    log_info "Todos os arquivos do agente encontrados (estrutura core/ + 4 agentes)"
}

# ── usuario dedicado ──────────────────────────────────────────────────────────

create_user() {
    log_section "Configurando usuario do sistema"
    if id "$APP_USER" &>/dev/null; then
        log_warn "Usuario '$APP_USER' ja existe — pulando criacao"
    else
        useradd --system --no-create-home --shell /sbin/nologin "$APP_USER"
        log_info "Usuario '$APP_USER' criado"
    fi
}

# ── instalacao dos arquivos ───────────────────────────────────────────────────

install_files() {
    log_section "Instalando binarios"

    mkdir -p "$INSTALL_DIR/core"

    # Modulos de nivel superior (runner, scheduler e os 4 agentes)
    local top_files=("runner.py" "scheduler.py"
                     "agent_operacional.py" "agent_backup.py"
                     "agent_acesso.py" "agent_logs.py")
    for f in "${top_files[@]}"; do
        cp "./$f" "$INSTALL_DIR/$f"
        log_info "  $f → $INSTALL_DIR/$f"
    done

    # Subpacote core/ (config_loader, sender, queue_local)
    local core_files=("__init__.py" "config_loader.py" "sender.py" "queue_local.py")
    for f in "${core_files[@]}"; do
        cp "./core/$f" "$INSTALL_DIR/core/$f"
        log_info "  core/$f → $INSTALL_DIR/core/$f"
    done

    # Binarios: dono root, executavel pelo grupo do agente
    chown -R root:"$APP_USER" "$INSTALL_DIR"
    chmod -R 750 "$INSTALL_DIR"
    log_info "Binarios instalados em $INSTALL_DIR"
}

# ── dependencias Python ───────────────────────────────────────────────────────

install_dependencies() {
    log_section "Instalando dependencias Python"

    # As dependencias (requests; tomli em Python<3.11) ficam em requirements.txt.
    if [[ -f "./requirements.txt" ]]; then
        pip3 install -r ./requirements.txt --break-system-packages -q
        log_info "Dependencias instaladas a partir de requirements.txt"
    else
        log_warn "requirements.txt nao encontrado — instalando requests diretamente"
        pip3 install requests --break-system-packages -q
        if ! python3 -c "import tomllib" &>/dev/null; then
            pip3 install tomli --break-system-packages -q
        fi
    fi
}

# ── diretorios de dados ───────────────────────────────────────────────────────

create_directories() {
    log_section "Criando diretorios de dados"

    # Configuracao — leitura pelo agente, escrita apenas pelo root
    mkdir -p "$CONFIG_DIR"
    chown root:"$APP_USER" "$CONFIG_DIR"
    chmod 750 "$CONFIG_DIR"
    log_info "Configuracao : $CONFIG_DIR"

    # Fila local — escrita pelo agente durante operacao
    mkdir -p "$QUEUE_DIR"
    chown "$APP_USER":"$APP_USER" "$QUEUE_DIR"
    chmod 750 "$QUEUE_DIR"
    log_info "Fila local   : $QUEUE_DIR"

    # Logs — escrita pelo agente
    mkdir -p "$LOG_DIR"
    chown "$APP_USER":"$APP_USER" "$LOG_DIR"
    chmod 750 "$LOG_DIR"
    log_info "Logs         : $LOG_DIR"
}

# ── coleta de parametros ──────────────────────────────────────────────────────

collect_config_params() {
    log_section "Configuracao do agente"
    echo ""
    echo "  Informe os parametros de conexao com o sistema central Argus."
    echo "  Pressione ENTER para usar o valor padrao indicado entre colchetes."
    echo ""

    while true; do
        read -rp "  URL da API central [https://]: " API_URL
        [[ "$API_URL" =~ ^https?:// ]] && break
        log_warn "URL invalida. Deve comecar com http:// ou https://"
    done
    if [[ "$API_URL" =~ ^http:// ]]; then
        log_warn "URL usa HTTP sem criptografia — o token viajara em plaintext."
        log_warn "Recomendado: use https:// em producao."
    fi

    while true; do
        read -rsp "  Token de autenticacao: " API_TOKEN
        echo ""
        [[ -n "$API_TOKEN" ]] && break
        log_warn "Token nao pode estar vazio"
    done

    read -rp "  Intervalo de coleta em segundos [300]: " INTERVAL
    INTERVAL="${INTERVAL:-300}"

    log_info "Parametros coletados"
}

# ── geracao do config.toml ────────────────────────────────────────────────────

generate_config() {
    log_section "Gerando config.toml"

    local config_file="$CONFIG_DIR/config.toml"

    # Backup do config existente
    if [[ -f "$config_file" ]]; then
        local bak="$config_file.bak.$(date +%Y%m%d_%H%M%S)"
        cp "$config_file" "$bak"
        log_warn "Config anterior salvo em: $bak"
    fi

    # IMPORTANTE: api_token fica VAZIO aqui. O token e injetado em runtime
    # pela variavel de ambiente AGENT_API_TOKEN, carregada do EnvironmentFile
    # protegido (ver generate_env_file). Assim o token nunca fica em texto
    # neste arquivo, que pode ser legivel pelo grupo do agente.
    cat > "$config_file" << EOF
# =============================================================================
# config.toml - Argus Agent
# Gerado automaticamente pelo install.sh em $(date -u '+%Y-%m-%d %H:%M:%S UTC')
#
# SEGURANCA: api_token fica vazio de proposito. O token e fornecido pela
# variavel de ambiente AGENT_API_TOKEN (ver ${ENV_FILE}).
# =============================================================================

[global]
api_url   = "${API_URL}"
api_token = ""
hostname  = ""

[schedule]
interval_seconds = ${INTERVAL}

[retry]
max_attempts    = 3
backoff_seconds = 10
http_timeout    = 10
queue_path      = "${QUEUE_DIR}"
queue_max_size  = 1000

[operacional]
enabled        = true
cpu_threshold  = 90
mem_threshold  = 85
disk_threshold = 90
critical_services_linux = ["sshd", "nginx", "mysql", "postgresql", "cron"]

[backup]
enabled     = true
sla_hours   = 24
min_size_mb = 5
extensions  = [".tar.gz", ".zip", ".dump", ".vhd", ".vhdx"]
paths_linux = ["/mnt/backups", "/var/backups"]

[acesso]
enabled = true

[logs]
enabled = true
EOF

    # config.toml nao contem segredos — legivel pelo grupo do agente
    chown root:"$APP_USER" "$config_file"
    chmod 640 "$config_file"
    log_info "config.toml gerado em $config_file (sem token)"
}

# ── arquivo de ambiente com o token (protegido) ──────────────────────────────

generate_env_file() {
    log_section "Gravando token em arquivo de ambiente protegido"

    # Backup do env file existente
    if [[ -f "$ENV_FILE" ]]; then
        local bak="$ENV_FILE.bak.$(date +%Y%m%d_%H%M%S)"
        cp "$ENV_FILE" "$bak"
        chmod 600 "$bak"
        log_warn "Env file anterior salvo em: $bak"
    fi

    # O token vive APENAS neste arquivo, lido pelo systemd (EnvironmentFile).
    # Permissao 600 e dono root: nem o usuario do agente le o arquivo em disco;
    # o token so existe na memoria do processo em execucao.
    cat > "$ENV_FILE" << EOF
# Token de autenticacao do Argus Agent — NAO compartilhe nem versione.
# Carregado pelo systemd como variavel de ambiente AGENT_API_TOKEN.
# Para rotacionar: edite este arquivo e execute 'systemctl restart ${APP_NAME}'.
AGENT_API_TOKEN=${API_TOKEN}
EOF

    chown root:root "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    log_info "Token gravado em $ENV_FILE (chmod 600, dono root)"
}

# ── servico systemd ───────────────────────────────────────────────────────────

create_service() {
    log_section "Registrando servico systemd"

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Argus — Agente de Monitoramento de Infraestrutura
Documentation=https://github.com/equipe-infraestrutura/argus
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${INSTALL_DIR}
# Token injetado como AGENT_API_TOKEN a partir do arquivo protegido (chmod 600).
# O segredo nunca aparece neste unit file nem no config.toml.
EnvironmentFile=${ENV_FILE}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/runner.py --config ${CONFIG_DIR}/config.toml
Restart=on-failure
RestartSec=30s
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=${QUEUE_DIR} ${LOG_DIR}
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${APP_NAME}

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$APP_NAME"
    log_info "Servico systemd registrado e habilitado no boot"
}

# ── inicio do servico ─────────────────────────────────────────────────────────

start_service() {
    log_section "Iniciando o servico"
    systemctl start "$APP_NAME"
    sleep 3

    if systemctl is-active --quiet "$APP_NAME"; then
        log_info "Servico iniciado com sucesso"
        echo ""
        systemctl status "$APP_NAME" --no-pager -l
    else
        log_error "Servico falhou ao iniciar. Verifique os logs:"
        echo "  journalctl -u $APP_NAME -n 50 --no-pager"
        exit 1
    fi
}

# ── resumo final ──────────────────────────────────────────────────────────────

print_summary() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║      Argus Agent instalado com sucesso!                  ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "  Binarios        : $INSTALL_DIR"
    echo "  Configuracao    : $CONFIG_DIR/config.toml (sem token)"
    echo "  Token (env)     : $ENV_FILE (chmod 600, dono root)"
    echo "  Logs            : $LOG_DIR"
    echo "  Fila local      : $QUEUE_DIR"
    echo ""
    echo "  Comandos uteis:"
    echo "    Status        : systemctl status $APP_NAME"
    echo "    Logs ao vivo  : journalctl -u $APP_NAME -f"
    echo "    Parar         : systemctl stop $APP_NAME"
    echo "    Reiniciar     : systemctl restart $APP_NAME"
    echo "    Rotacionar token : edite $ENV_FILE e rode systemctl restart $APP_NAME"
    echo "    Validar coleta   : runuser -u $APP_USER -- python3 $INSTALL_DIR/runner.py --config $CONFIG_DIR/config.toml --dry-run"
    echo "    Desinstalar   : systemctl stop $APP_NAME && systemctl disable $APP_NAME"
    echo ""
}

# ── execucao principal ────────────────────────────────────────────────────────

NO_START=false
for arg in "$@"; do [[ "$arg" == "--no-start" ]] && NO_START=true; done

check_prerequisites
create_user
install_files
install_dependencies
create_directories
collect_config_params
generate_config
generate_env_file
create_service

# Valida a coleta com --dry-run ANTES de iniciar o envio.
# Roda como o usuario do agente, com o token do EnvironmentFile, sem enviar nada.
log_section "Validando a coleta (dry-run)"
if AGENT_API_TOKEN="$API_TOKEN" runuser -u "$APP_USER" -- \
        python3 "$INSTALL_DIR/runner.py" --config "$CONFIG_DIR/config.toml" --dry-run \
        --log-level WARNING; then
    log_info "Dry-run concluido sem erros — agentes coletando corretamente"
else
    log_warn "Dry-run reportou findings com erro (exit!=0)."
    log_warn "Isso pode ser esperado (ex: permissao de auditoria). Revise a saida acima."
fi

if [[ "$NO_START" == false ]]; then
    start_service
else
    log_warn "Opcao --no-start ativa — servico nao iniciado"
    log_info "Para iniciar: systemctl start $APP_NAME"
fi

print_summary

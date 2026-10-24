#!/usr/bin/env bash
# =============================================================================
# install.sh — Instalador do agente Argus para Linux (bootstrap pela central)
#
# Uso (uma linha, como root):
#   curl -fsSL http://<central>/install/install.sh \
#     | sudo ARGUS_HOST=<central> ARGUS_TOKEN=<token> bash
#
# O script:
#   1. Baixa a CA e o codigo do agente da central (HTTP, porta 80)
#   2. Instala Python 3 / curl / unzip se necessario
#   3. Salva a CA para o agente confiar no HTTPS da central (ca_cert)
#   4. Cria usuario dedicado, instala o agente e registra o servico systemd
#   5. Grava o token em arquivo protegido (chmod 600), injetado pelo systemd
#   6. Valida a coleta (--dry-run) e inicia o servico
#
# Por que HTTP no download: para confiar no HTTPS da central e preciso pegar a CA
# antes; CA e codigo nao sao segredos. O token e informado aqui (nunca trafega) e
# as metricas vao por HTTPS. Ver install/INSTALL.md.
# =============================================================================

set -euo pipefail

# ── constantes ────────────────────────────────────────────────────────────────
APP_NAME="argus-agent"
APP_USER="argus-agent"
INSTALL_DIR="/opt/argus/agent-monitor"
CONFIG_DIR="/etc/argus/agent-monitor"
# STATE_DIR guarda o estado do agente (backup_state.json, config_cache.json) e a
# fila local: o agente grava ao lado de retry.queue_path (ver core/sysutils.py).
STATE_DIR="/var/lib/argus/agent-monitor"
QUEUE_DIR="${STATE_DIR}/queue"
LOG_DIR="/var/log/argus/agent-monitor"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
ENV_FILE="${CONFIG_DIR}/agent.env"
CONFIG_FILE="${CONFIG_DIR}/config.toml"
CA_FILE="${CONFIG_DIR}/argus-ca.crt"
PYTHON_MIN_VERSION="3.11"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERRO]${NC}  $*"; }
log_section() { echo -e "\n${BLUE}── $* ──────────────────────────────────────${NC}"; }
abort() { log_error "$*"; exit 1; }

NO_START=false
for arg in "$@"; do [[ "$arg" == "--no-start" ]] && NO_START=true; done

# ── distro / pacotes ────────────────────────────────────────────────────────────
detect_distro() {
    if   command -v apt-get &>/dev/null; then echo "apt"
    elif command -v dnf     &>/dev/null; then echo "dnf"
    elif command -v yum     &>/dev/null; then echo "yum"
    else echo "unknown"; fi
}

pkg_install() {  # instala pacotes do sistema conforme a distro
    local distro; distro=$(detect_distro)
    case "$distro" in
        apt) apt-get update -qq; apt-get install -y "$@" ;;
        dnf) dnf install -y "$@" ;;
        yum) yum install -y "$@" ;;
        *)   abort "Gerenciador de pacotes nao identificado. Instale manualmente: $*" ;;
    esac
}

version_gte() {
    python3 -c "import sys;a=tuple(int(x) for x in '$1'.split('.'));b=tuple(int(x) for x in '$2'.split('.'));sys.exit(0 if a>=b else 1)"
}

# ── pre-requisitos ───────────────────────────────────────────────────────────────
check_prerequisites() {
    log_section "Verificando pre-requisitos"
    [[ "$EUID" -eq 0 ]] || abort "Execute como root (use sudo)."

    # Ferramentas de download/extracao
    command -v curl  &>/dev/null || { log_warn "curl ausente — instalando";  pkg_install curl; }
    command -v unzip &>/dev/null || { log_warn "unzip ausente — instalando"; pkg_install unzip; }

    # Python 3.11+
    if ! command -v python3 &>/dev/null; then
        log_warn "Python 3 ausente — instalando"
        pkg_install python3 python3-pip
    fi
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    version_gte "$PYTHON_VERSION" "$PYTHON_MIN_VERSION" \
        || log_warn "Python $PYTHON_VERSION (< $PYTHON_MIN_VERSION) — pode exigir 'tomli'"
    command -v pip3 &>/dev/null || pkg_install python3-pip
    command -v systemctl &>/dev/null || abort "systemd (systemctl) nao encontrado."
    log_info "Python $PYTHON_VERSION, pip3, systemd e curl/unzip presentes"
}

# ── parametros (env vars ou prompt) ─────────────────────────────────────────────
collect_params() {
    log_section "Parametros de conexao"
    ARGUS_HOST="${ARGUS_HOST:-}"
    ARGUS_TOKEN="${ARGUS_TOKEN:-}"
    INTERVAL="${ARGUS_INTERVAL:-300}"

    if [[ -z "$ARGUS_HOST" ]]; then
        read -rp "  Endereco da central (ex: argus.empresa.local): " ARGUS_HOST < /dev/tty
    fi
    [[ -n "$ARGUS_HOST" ]] || abort "ARGUS_HOST nao informado."

    if [[ -z "$ARGUS_TOKEN" ]]; then
        read -rsp "  Token do agente: " ARGUS_TOKEN < /dev/tty; echo ""
    fi
    [[ -n "$ARGUS_TOKEN" ]] || abort "Token nao informado."

    API_URL="https://${ARGUS_HOST}"
    BASE="http://${ARGUS_HOST}/install"
    log_info "Central: $ARGUS_HOST"
}

# ── download dos artefatos ───────────────────────────────────────────────────────
download_artifacts() {
    log_section "Baixando artefatos da central"
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT
    SRC_DIR="$TMP/agent"
    mkdir -p "$SRC_DIR"

    log_info "Baixando a CA..."
    curl -fsSL "$BASE/ca.crt" -o "$TMP/argus-ca.crt"
    log_info "Baixando o codigo do agente..."
    curl -fsSL "$BASE/argus-agent.zip" -o "$TMP/argus-agent.zip"
    unzip -q "$TMP/argus-agent.zip" -d "$SRC_DIR"
    log_info "Artefatos baixados e extraidos"
}

# ── usuario, diretorios, arquivos ─────────────────────────────────────────────────
create_user() {
    log_section "Usuario do sistema"
    if id "$APP_USER" &>/dev/null; then
        log_warn "Usuario '$APP_USER' ja existe"
    else
        useradd --system --no-create-home --shell /sbin/nologin "$APP_USER"
        log_info "Usuario '$APP_USER' criado"
    fi
}

install_files() {
    log_section "Instalando binarios"
    mkdir -p "$INSTALL_DIR/core"
    cp "$SRC_DIR"/*.py "$INSTALL_DIR/"
    cp "$SRC_DIR"/core/*.py "$INSTALL_DIR/core/"
    chown -R root:"$APP_USER" "$INSTALL_DIR"
    chmod -R 750 "$INSTALL_DIR"
    log_info "Binarios instalados em $INSTALL_DIR"
}

install_dependencies() {
    log_section "Dependencias Python"
    if [[ -f "$SRC_DIR/requirements.txt" ]]; then
        pip3 install -r "$SRC_DIR/requirements.txt" --break-system-packages -q
    else
        pip3 install requests --break-system-packages -q
        python3 -c "import tomllib" &>/dev/null || pip3 install tomli --break-system-packages -q
    fi
    log_info "Dependencias instaladas"
}

create_directories() {
    log_section "Diretorios de dados"
    mkdir -p "$CONFIG_DIR"; chown root:"$APP_USER" "$CONFIG_DIR"; chmod 750 "$CONFIG_DIR"
    # A pasta de estado (pai da fila) precisa ser do usuario do servico; com
    # ProtectSystem=strict ela tambem entra no ReadWritePaths da unit. Reinstalar
    # corrige instalacoes antigas, em que ela ficava root:root (estado nao gravado).
    mkdir -p "$STATE_DIR"; chown "$APP_USER":"$APP_USER" "$STATE_DIR"; chmod 750 "$STATE_DIR"
    # agent.lock criado por um runner executado como root travaria o servico fora da trava
    [[ -e "$STATE_DIR/agent.lock" ]] && chown "$APP_USER":"$APP_USER" "$STATE_DIR/agent.lock"
    mkdir -p "$QUEUE_DIR"; chown "$APP_USER":"$APP_USER" "$QUEUE_DIR"; chmod 750 "$QUEUE_DIR"
    mkdir -p "$LOG_DIR";   chown "$APP_USER":"$APP_USER" "$LOG_DIR";   chmod 750 "$LOG_DIR"
    log_info "Config: $CONFIG_DIR | Estado: $STATE_DIR | Fila: $QUEUE_DIR | Logs: $LOG_DIR"
}

# ── CA (para o agente confiar no HTTPS da central) ──────────────────────────────
install_ca() {
    log_section "Certificado da central (CA)"
    # O agente Python valida o TLS contra este arquivo (ca_cert no config.toml).
    install -o root -g "$APP_USER" -m 640 "$TMP/argus-ca.crt" "$CA_FILE"
    log_info "CA salva em $CA_FILE (usada via ca_cert)"

    # Best-effort: tambem confia no nivel do SO (util para curl/navegador no host).
    if command -v update-ca-certificates &>/dev/null; then
        cp "$TMP/argus-ca.crt" /usr/local/share/ca-certificates/argus-ca.crt 2>/dev/null \
            && update-ca-certificates &>/dev/null \
            && log_info "CA tambem adicionada ao trust do SO" || true
    fi
}

# ── config.toml (com ca_cert; sem token) ─────────────────────────────────────────
generate_config() {
    log_section "Gerando config.toml"
    [[ -f "$CONFIG_FILE" ]] && cp "$CONFIG_FILE" "$CONFIG_FILE.bak.$(date +%Y%m%d_%H%M%S)"
    cat > "$CONFIG_FILE" << EOF
# =============================================================================
# config.toml - Argus Agent (gerado pelo install.sh em $(date -u '+%Y-%m-%d %H:%M:%S UTC'))
# SEGURANCA: api_token vazio; o token vem de AGENT_API_TOKEN (ver ${ENV_FILE}).
# =============================================================================

[global]
api_url   = "${API_URL}"
api_token = ""
hostname  = ""
# CA interna da central (Caddy tls internal). O agente Python valida o HTTPS
# contra este arquivo (nao usa o trust do SO).
ca_cert   = "${CA_FILE}"

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
    chown root:"$APP_USER" "$CONFIG_FILE"; chmod 640 "$CONFIG_FILE"
    log_info "config.toml gerado em $CONFIG_FILE (com ca_cert, sem token)"
}

generate_env_file() {
    log_section "Token (arquivo protegido)"
    [[ -f "$ENV_FILE" ]] && { cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d_%H%M%S)"; chmod 600 "$ENV_FILE.bak."*; }
    cat > "$ENV_FILE" << EOF
# Token do Argus Agent — NAO compartilhe nem versione.
# Carregado pelo systemd como AGENT_API_TOKEN. Rotacionar: edite e reinicie o servico.
AGENT_API_TOKEN=${ARGUS_TOKEN}
EOF
    chown root:root "$ENV_FILE"; chmod 600 "$ENV_FILE"
    log_info "Token gravado em $ENV_FILE (chmod 600, dono root)"
}

create_service() {
    log_section "Servico systemd"
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Argus — Agente de Monitoramento de Infraestrutura
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/runner.py --config ${CONFIG_FILE}
Restart=on-failure
RestartSec=30s
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=${STATE_DIR} ${LOG_DIR}
# Leitura do journal (falhas de logon e logs em sistemas sem auth.log/syslog)
SupplementaryGroups=systemd-journal
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${APP_NAME}

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$APP_NAME" &>/dev/null
    log_info "Servico systemd registrado e habilitado no boot"
}

# ── execucao ──────────────────────────────────────────────────────────────────────
check_prerequisites
collect_params
download_artifacts
create_user
install_files
install_dependencies
create_directories
install_ca
generate_config
generate_env_file
create_service

log_section "Validando a coleta (dry-run)"
if AGENT_API_TOKEN="$ARGUS_TOKEN" runuser -u "$APP_USER" -- \
        python3 "$INSTALL_DIR/runner.py" --config "$CONFIG_FILE" --dry-run --log-level WARNING; then
    log_info "Dry-run sem erros — agentes coletando"
else
    log_warn "Dry-run com findings status=error (pode ser esperado). Revise a saida acima."
fi

if [[ "$NO_START" == false ]]; then
    log_section "Iniciando o servico"
    systemctl start "$APP_NAME"; sleep 3
    if systemctl is-active --quiet "$APP_NAME"; then
        log_info "Servico iniciado com sucesso"
    else
        log_error "Servico falhou. Logs: journalctl -u $APP_NAME -n 50 --no-pager"; exit 1
    fi
else
    log_warn "--no-start ativo. Para iniciar: systemctl start $APP_NAME"
fi

echo ""
echo -e "${GREEN}== Argus Agent instalado ==${NC}"
echo "  Central     : ${API_URL}"
echo "  Binarios    : ${INSTALL_DIR}"
echo "  Config      : ${CONFIG_FILE} (ca_cert; sem token)"
echo "  CA          : ${CA_FILE}"
echo "  Token (env) : ${ENV_FILE} (chmod 600)"
echo "  Status      : systemctl status ${APP_NAME}"
echo "  Logs        : journalctl -u ${APP_NAME} -f"
echo ""

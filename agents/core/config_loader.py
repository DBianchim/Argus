#!/usr/bin/env python3
"""
config_loader.py — Leitura e validacao do arquivo de configuracao central

Responsabilidade:
    Carregar o config.toml, aplicar substituicoes por variaveis de ambiente,
    validar campos obrigatorios e retornar um objeto de configuracao tipado
    e pronto para uso pelos demais modulos.

Ordem de prioridade (maior para menor):
    1. Variaveis de ambiente  (AGENT_*)
    2. Valores do config.toml
    3. Valores padrao internos

Uso:
    from core.config_loader import load_config
    config = load_config()
    print(config.api_url)
    print(config.operacional.cpu_threshold)

Autores: Equipe de Infraestrutura
"""

import os
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Tentativa de importar tomllib (Python 3.11+) com fallback para tomli (pip)
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        print(
            '[ERRO] Biblioteca TOML nao encontrada.\n'
            'Execute: pip install tomli --break-system-packages',
            file=sys.stderr,
        )
        sys.exit(1)


# ── caminho padrao do arquivo de configuracao ─────────────────────────────────

# config.toml fica em agents/ (um nivel acima de core/)
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / 'config.toml'


# ── dataclasses de configuracao ───────────────────────────────────────────────

@dataclass
class GlobalConfig:
    """Configuracoes de conexao e identidade do servidor."""
    api_url:    str
    api_token:  str
    hostname:   str
    allow_http: bool = False

    def _mask_token(self) -> str:
        """Retorna uma versao mascarada do token, segura para exibir em logs."""
        if not self.api_token or len(self.api_token) <= 8:
            return '****'
        return f'{self.api_token[:4]}****'

    def __repr__(self) -> str:
        # __repr__ mascara o token para que ele nunca apareca em tracebacks,
        # debuggers ou logs que imprimam o objeto inteiro.
        return (
            f'GlobalConfig(api_url={self.api_url!r}, '
            f'api_token={self._mask_token()!r}, '
            f'hostname={self.hostname!r}, '
            f'allow_http={self.allow_http!r})'
        )

    def __str__(self) -> str:
        return self.__repr__()


@dataclass
class ScheduleConfig:
    """Frequencia de execucao dos agentes."""
    interval_seconds: int


@dataclass
class RetryConfig:
    """Politica de reenvio e fila local."""
    max_attempts:    int
    backoff_seconds: int
    http_timeout:    int
    queue_path:      str
    queue_max_size:  int


@dataclass
class OperacionalConfig:
    """Parametros do agente operacional."""
    enabled:                    bool
    cpu_threshold:              int
    mem_threshold:              int
    disk_threshold:             int
    critical_services_linux:    list[str]
    critical_services_windows:  list[str]


@dataclass
class BackupConfig:
    """Parametros do agente de backup."""
    enabled:       bool
    sla_hours:     int
    min_size_mb:   int
    extensions:    list[str]
    paths_linux:   list[str]
    paths_windows: list[str]


@dataclass
class AcessoConfig:
    """Parametros do agente de acesso."""
    enabled: bool


@dataclass
class LogsConfig:
    """Parametros do agente de logs."""
    enabled: bool


@dataclass
class AgentConfig:
    """
    Configuracao completa do agente.

    Objeto raiz retornado por load_config(). Agrega todas as secoes
    do config.toml em um unico objeto de acesso tipado.
    """
    global_:     GlobalConfig
    schedule:    ScheduleConfig
    retry:       RetryConfig
    operacional: OperacionalConfig
    backup:      BackupConfig
    acesso:      AcessoConfig
    logs:        LogsConfig


# ── substituicao por variaveis de ambiente ────────────────────────────────────

def _apply_env_overrides(raw: dict) -> dict:
    """
    Substitui valores do config.toml por variaveis de ambiente quando definidas.

    Mapeamento completo:
        AGENT_API_URL              → global.api_url
        AGENT_API_TOKEN            → global.api_token
        AGENT_HOSTNAME             → global.hostname
        AGENT_INTERVAL_SECONDS     → schedule.interval_seconds
        AGENT_RETRY_MAX_ATTEMPTS   → retry.max_attempts
        AGENT_RETRY_BACKOFF_SECONDS→ retry.backoff_seconds
        AGENT_HTTP_TIMEOUT         → retry.http_timeout
        AGENT_QUEUE_PATH           → retry.queue_path
        AGENT_QUEUE_MAX_SIZE       → retry.queue_max_size
        AGENT_CPU_THRESHOLD        → operacional.cpu_threshold
        AGENT_MEM_THRESHOLD        → operacional.mem_threshold
        AGENT_DISK_THRESHOLD       → operacional.disk_threshold
        AGENT_SLA_BACKUP_HOURS     → backup.sla_hours
        AGENT_MIN_BACKUP_MB        → backup.min_size_mb
    """
    env = os.environ

    # [global]
    g = raw.setdefault('global', {})
    if val := env.get('AGENT_API_URL'):
        g['api_url'] = val
    if val := env.get('AGENT_API_TOKEN'):
        g['api_token'] = val
    if val := env.get('AGENT_HOSTNAME'):
        g['hostname'] = val

    # [schedule]
    s = raw.setdefault('schedule', {})
    if val := env.get('AGENT_INTERVAL_SECONDS'):
        s['interval_seconds'] = int(val)

    # [retry]
    r = raw.setdefault('retry', {})
    if val := env.get('AGENT_RETRY_MAX_ATTEMPTS'):
        r['max_attempts'] = int(val)
    if val := env.get('AGENT_RETRY_BACKOFF_SECONDS'):
        r['backoff_seconds'] = int(val)
    if val := env.get('AGENT_HTTP_TIMEOUT'):
        r['http_timeout'] = int(val)
    if val := env.get('AGENT_QUEUE_PATH'):
        r['queue_path'] = val
    if val := env.get('AGENT_QUEUE_MAX_SIZE'):
        r['queue_max_size'] = int(val)

    # [operacional]
    op = raw.setdefault('operacional', {})
    if val := env.get('AGENT_CPU_THRESHOLD'):
        op['cpu_threshold'] = int(val)
    if val := env.get('AGENT_MEM_THRESHOLD'):
        op['mem_threshold'] = int(val)
    if val := env.get('AGENT_DISK_THRESHOLD'):
        op['disk_threshold'] = int(val)

    # [backup]
    bk = raw.setdefault('backup', {})
    if val := env.get('AGENT_SLA_BACKUP_HOURS'):
        bk['sla_hours'] = int(val)
    if val := env.get('AGENT_MIN_BACKUP_MB'):
        bk['min_size_mb'] = int(val)

    # Marca a origem do token para aviso/validacao posteriores.
    # 'env'  → veio da variavel de ambiente (recomendado)
    # 'toml' → veio do arquivo (aviso de seguranca)
    # 'none' → ausente em ambos (erro de validacao)
    if env.get('AGENT_API_TOKEN'):
        raw['_token_source'] = 'env'
    elif g.get('api_token') and g.get('api_token') != 'INSIRA_SEU_TOKEN_AQUI':
        raw['_token_source'] = 'toml'
    else:
        raw['_token_source'] = 'none'

    return raw


# ── avisos de seguranca ───────────────────────────────────────────────────────

def _warn_token_source(raw: dict) -> None:
    """
    Emite aviso quando o token vem do arquivo TOML em vez de variavel de ambiente.

    O uso de AGENT_API_TOKEN e a pratica recomendada para producao porque:
      - O arquivo TOML pode ser acidentalmente comitado em repositorios.
      - A env var e mais facil de rotacionar via secrets managers.
      - O TOML tem precedencia silenciosa quando a env var nao esta definida.

    Nao bloqueia a execucao — apenas avisa o operador.
    """
    if raw.get('_token_source') == 'toml':
        print(
            '[AVISO DE SEGURANCA] api_token lido do arquivo TOML.\n'
            '  Recomendado: defina a variavel de ambiente AGENT_API_TOKEN.\n'
            '  Linux:   export AGENT_API_TOKEN="seu-token-aqui"\n'
            '  Windows: $env:AGENT_API_TOKEN="seu-token-aqui"\n'
            '  A env var tem precedencia sobre o TOML quando definida.',
            file=sys.stderr,
        )


def _warn_insecure_http(raw: dict) -> None:
    """
    Emite aviso quando api_url usa HTTP sem criptografia e allow_http nao foi
    explicitamente habilitado. Nao bloqueia — preserva o fluxo de dev (mock_server).
    """
    g = raw.get('global', {})
    api_url = g.get('api_url', '')
    allow_http = bool(g.get('allow_http', False))

    if api_url.startswith('http://') and not allow_http:
        print(
            '[AVISO DE SEGURANCA] api_url usa HTTP sem criptografia.\n'
            f'  URL configurada: {api_url}\n'
            '  O token de autenticacao viajara em plaintext na rede.\n'
            '  Para producao: use https://\n'
            '  Para dev com HTTP intencional, adicione ao [global]:\n'
            '    allow_http = true',
            file=sys.stderr,
        )


# ── validacao ─────────────────────────────────────────────────────────────────

class ConfigError(Exception):
    """Excecao lancada quando o config.toml possui valores invalidos ou ausentes."""


def _validate(raw: dict) -> None:
    """
    Valida os campos obrigatorios e os tipos dos valores criticos.

    Raises:
        ConfigError: Se qualquer validacao falhar.
    """
    errors: list[str] = []

    # [global] — campos obrigatorios
    g = raw.get('global', {})
    if not g.get('api_url', '').startswith(('http://', 'https://')):
        errors.append('[global] api_url deve comecar com http:// ou https://')
    # Token: aceita vazio no TOML desde que AGENT_API_TOKEN esteja definida.
    # _token_source == 'none' significa ausente em ambos (TOML e env var).
    if raw.get('_token_source') == 'none':
        errors.append(
            '[global] api_token nao configurado — '
            'defina AGENT_API_TOKEN como variavel de ambiente ou no config.toml'
        )

    # [schedule] — valores positivos
    s = raw.get('schedule', {})
    if int(s.get('interval_seconds', 0)) < 10:
        errors.append('[schedule] interval_seconds deve ser >= 10 segundos')

    # [retry] — valores positivos
    r = raw.get('retry', {})
    if int(r.get('max_attempts', 0)) < 1:
        errors.append('[retry] max_attempts deve ser >= 1')
    if int(r.get('http_timeout', 0)) < 1:
        errors.append('[retry] http_timeout deve ser >= 1 segundo')
    if not r.get('queue_path'):
        errors.append('[retry] queue_path nao pode estar vazio')

    # [operacional] — thresholds entre 1 e 100
    op = raw.get('operacional', {})
    if op.get('enabled', False):
        for field_name in ('cpu_threshold', 'mem_threshold', 'disk_threshold'):
            val = int(op.get(field_name, 0))
            if not 1 <= val <= 100:
                errors.append(f'[operacional] {field_name} deve estar entre 1 e 100')

    # [backup] — valores positivos
    bk = raw.get('backup', {})
    if bk.get('enabled', False):
        if int(bk.get('sla_hours', 0)) < 1:
            errors.append('[backup] sla_hours deve ser >= 1')
        if int(bk.get('min_size_mb', 0)) < 1:
            errors.append('[backup] min_size_mb deve ser >= 1')
        if not bk.get('extensions'):
            errors.append('[backup] extensions nao pode estar vazia')

    if errors:
        msg = '\n'.join(f'  - {e}' for e in errors)
        raise ConfigError(f'Erros encontrados no config.toml:\n{msg}')


# ── construcao do objeto tipado ───────────────────────────────────────────────

def _build_config(raw: dict) -> AgentConfig:
    """
    Converte o dicionario bruto validado em um objeto AgentConfig tipado.
    """
    g  = raw.get('global',      {})
    s  = raw.get('schedule',    {})
    r  = raw.get('retry',       {})
    op = raw.get('operacional', {})
    bk = raw.get('backup',      {})
    ac = raw.get('acesso',      {})
    lg = raw.get('logs',        {})

    hostname = g.get('hostname', '').strip() or socket.gethostname()

    return AgentConfig(
        global_=GlobalConfig(
            api_url=g['api_url'].rstrip('/'),
            api_token=g.get('api_token', ''),
            hostname=hostname,
            allow_http=bool(g.get('allow_http', False)),
        ),
        schedule=ScheduleConfig(
            interval_seconds=int(s.get('interval_seconds', 300)),
        ),
        retry=RetryConfig(
            max_attempts=int(r.get('max_attempts',    3)),
            backoff_seconds=int(r.get('backoff_seconds', 10)),
            http_timeout=int(r.get('http_timeout',    10)),
            queue_path=r.get('queue_path', '/var/lib/argus/agent-monitor/queue'),
            queue_max_size=int(r.get('queue_max_size', 1000)),
        ),
        operacional=OperacionalConfig(
            enabled=bool(op.get('enabled', True)),
            cpu_threshold=int(op.get('cpu_threshold',  90)),
            mem_threshold=int(op.get('mem_threshold',  85)),
            disk_threshold=int(op.get('disk_threshold', 90)),
            critical_services_linux=list(op.get('critical_services_linux',   [])),
            critical_services_windows=list(op.get('critical_services_windows', [])),
        ),
        backup=BackupConfig(
            enabled=bool(bk.get('enabled', True)),
            sla_hours=int(bk.get('sla_hours',   24)),
            min_size_mb=int(bk.get('min_size_mb', 5)),
            extensions=list(bk.get('extensions',   ['.tar.gz', '.zip', '.dump'])),
            paths_linux=list(bk.get('paths_linux',   ['/mnt/backups', '/var/backups'])),
            paths_windows=list(bk.get('paths_windows', ['E:\\Backups'])),
        ),
        acesso=AcessoConfig(
            enabled=bool(ac.get('enabled', False)),
        ),
        logs=LogsConfig(
            enabled=bool(lg.get('enabled', False)),
        ),
    )


# ── funcao publica ────────────────────────────────────────────────────────────

def load_config(path: Optional[Path] = None) -> AgentConfig:
    """
    Carrega, valida e retorna a configuracao completa do agente.

    Args:
        path: Caminho alternativo para o config.toml. Opcional.

    Returns:
        AgentConfig com todos os valores validados e prontos para uso.

    Raises:
        SystemExit: Se o arquivo nao for encontrado ou a validacao falhar.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        print(
            f'[ERRO] Arquivo de configuracao nao encontrado: {config_path}\n'
            f'Copie o config.toml para o mesmo diretorio dos agentes e preencha os valores.',
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with open(config_path, 'rb') as f:
            raw = tomllib.load(f)
    except Exception as e:
        print(f'[ERRO] Falha ao ler o config.toml: {e}', file=sys.stderr)
        sys.exit(1)

    raw = _apply_env_overrides(raw)

    _warn_token_source(raw)
    _warn_insecure_http(raw)

    try:
        _validate(raw)
    except ConfigError as e:
        print(f'[ERRO] {e}', file=sys.stderr)
        sys.exit(1)

    return _build_config(raw)


# ── execucao direta (validacao rapida) ────────────────────────────────────────

if __name__ == '__main__':
    config = load_config()
    print('[OK] config.toml carregado e validado com sucesso.\n')
    print(f'  Servidor  : {config.global_.hostname}')
    print(f'  API URL   : {config.global_.api_url}')
    print(f'  Intervalo : {config.schedule.interval_seconds}s')
    print(f'  Fila local: {config.retry.queue_path}')
    print(f'  Agentes ativos:')
    print(f'    operacional : {config.operacional.enabled}')
    print(f'    backup      : {config.backup.enabled}')
    print(f'    acesso      : {config.acesso.enabled}')
    print(f'    logs        : {config.logs.enabled}')

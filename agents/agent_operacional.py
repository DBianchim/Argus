#!/usr/bin/env python3
"""
agent_operacional.py â€” Agente de monitoramento operacional
Coleta: CPU, memoria, disco e servicos criticos

Responsabilidade:
    Coletar metricas brutas do sistema operacional e retornar um payload
    padronizado para envio ao sistema central. Este agente NAO processa
    alertas â€” toda logica de analise e responsabilidade do sistema central.

Suporte de plataforma:
    - Windows: PowerShell + WMI (CimInstance)
    - Linux:   /proc filesystem + systemctl

Seguranca:
    - Todos os subprocessos usam shell=False e listas de argumentos
      para eliminar risco de injecao de comandos via shell.

Autores: Equipe de Infraestrutura
"""

import json

from core.config_loader import AgentConfig, load_config
# Utilitarios compartilhados (DRY): now_iso, detect_os e execucao de comandos.
from core.sysutils import AGENT_VERSION, now_iso, detect_os, run_cmd, run_powershell

# â”€â”€ constante de plataforma â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

OS_FAMILY: str = detect_os()

# â”€â”€ utilitarios gerais â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_command(args: list[str], timeout: int = 15) -> str:
    """
    Wrapper fino sobre core.sysutils.run_cmd que retorna apenas o stdout
    (sem espacos nas bordas), preservando a assinatura usada neste agente.
    A seguranca (shell=False) e garantida por run_cmd.

    Returns:
        stdout do comando, sem espacos nas bordas. String vazia em falha/timeout.
    """
    return run_cmd(args, timeout)[0].strip()


# â”€â”€ coletores Windows â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _win_run_powershell(script: str) -> str:
    """
    Executa um script PowerShell e retorna apenas o stdout (sem bordas).
    Usa core.sysutils.run_powershell (-NoProfile -NonInteractive, shell=False).
    """
    return run_powershell(script)[0].strip()


def win_cpu() -> dict:
    """
    Coleta uso de CPU, numero de nucleos fisicos e logicos via WMI.

    Usa Get-CimInstance Win32_Processor, que e a API moderna e
    recomendada pela Microsoft em substituicao ao WScript/WBEM legado.
    """
    script = (
        '$c = Get-CimInstance Win32_Processor; '
        '[pscustomobject]@{'
        '    pct     = ($c | Measure-Object LoadPercentage -Average).Average;'
        '    cores   = $c.NumberOfCores;'
        '    logical = $c.NumberOfLogicalProcessors'
        '} | ConvertTo-Json'
    )
    raw = _win_run_powershell(script)
    try:
        data = json.loads(raw)
        return {
            'usage_pct':     round(data['pct'], 2),
            'cores':         data['cores'],
            'logical_procs': data['logical'],
        }
    except (json.JSONDecodeError, KeyError):
        return {'usage_pct': None, 'error': 'wmi_unavailable'}


def win_memory() -> dict:
    """
    Coleta total e uso de memoria RAM via WMI.

    Os valores do WMI chegam em KB; convertemos para MB para
    consistencia com os coletores Linux.
    """
    script = (
        '$o = Get-CimInstance Win32_OperatingSystem; '
        '[pscustomobject]@{'
        '    total = [math]::Round($o.TotalVisibleMemorySize / 1024, 0);'
        '    free  = [math]::Round($o.FreePhysicalMemory      / 1024, 0)'
        '} | ConvertTo-Json'
    )
    raw = _win_run_powershell(script)
    try:
        data  = json.loads(raw)
        used  = data['total'] - data['free']
        return {
            'total_mb':  data['total'],
            'used_mb':   used,
            'free_mb':   data['free'],
            'usage_pct': round(used * 100 / data['total'], 2),
        }
    except (json.JSONDecodeError, KeyError, ZeroDivisionError):
        return {'total_mb': None, 'error': 'wmi_unavailable'}


def win_disk() -> list[dict]:
    """
    Coleta uso de disco para todos os volumes locais (DriveType=3) via WMI.

    DriveType=3 filtra apenas discos fixos, excluindo CD-ROMs (5),
    unidades de rede (4) e discos removiveis (2).
    """
    script = (
        "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
        'Select-Object DeviceID, Size, FreeSpace | ConvertTo-Json'
    )
    raw = _win_run_powershell(script)
    try:
        items = json.loads(raw)
        # ConvertTo-Json retorna objeto unico quando ha apenas um disco
        if isinstance(items, dict):
            items = [items]

        disks = []
        for item in items:
            total_gb = round(item['Size']      / 1_073_741_824, 2)
            free_gb  = round(item['FreeSpace'] / 1_073_741_824, 2)
            disks.append({
                'mount':     item['DeviceID'],
                'total_gb':  total_gb,
                'free_gb':   free_gb,
                'usage_pct': round((total_gb - free_gb) * 100 / total_gb, 2),
            })
        return disks
    except (json.JSONDecodeError, KeyError, ZeroDivisionError):
        return []


def win_services(service_list: list[str]) -> list[dict]:
    """
    Verifica o estado dos servicos criticos recebidos como parametro.

    A lista de servicos vem do config.toml via AgentConfig, eliminando
    a dependencia do CONFIG interno. Cada servico e consultado
    individualmente para isolar falhas: um servico nao encontrado
    nao interrompe a coleta dos demais.

    O PowerShell retorna Status e StartType como inteiros via ConvertTo-Json.
    Usamos o metodo .ToString() no script para forcar a conversao para
    string legivel antes da serializacao JSON.

    Mapeamento de Status:
        1=Stopped | 2=StartPending | 3=StopPending | 4=Running
        5=ContinuePending | 6=PausePending | 7=Paused

    Args:
        service_list: Lista de nomes de servicos Windows a verificar.
    """
    services = []
    for service_name in service_list:
        # .ToString() converte os enums Status e StartType para string
        # antes do ConvertTo-Json, evitando retorno como inteiro
        script = (
            f"$s = Get-Service -Name '{service_name}' -ErrorAction SilentlyContinue; "
            'if ($s) { [pscustomobject]@{ '
            '    name  = $s.Name; '
            '    status = $s.Status.ToString(); '
            '    start  = $s.StartType.ToString() '
            '} | ConvertTo-Json }'
        )
        raw = _win_run_powershell(script)
        try:
            data = json.loads(raw)
            services.append({
                'name':       data['name'],
                'status':     data['status'].lower(),
                'start_type': data['start'].lower(),
            })
        except (json.JSONDecodeError, KeyError):
            services.append({'name': service_name, 'status': 'not_found'})
    return services


# â”€â”€ coletores Linux â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def linux_cpu() -> dict:
    """
    Calcula o uso de CPU lendo /proc/stat em dois momentos espacados por 1s.

    A leitura dupla e necessaria porque /proc/stat acumula ticks desde o
    boot â€” a diferenca entre duas leituras representa o intervalo de 1 segundo.
    idle inclui iowait (campo [4]) para capturar espera por I/O de disco.
    """
    import time

    def read_cpu_ticks() -> list[int]:
        with open('/proc/stat', encoding='utf-8') as f:
            for line in f:
                if line.startswith('cpu '):
                    # Campos: user nice system idle iowait irq softirq
                    return list(map(int, line.split()[1:8]))
        return []

    ticks_1 = read_cpu_ticks()
    time.sleep(1)
    ticks_2 = read_cpu_ticks()

    idle_1  = ticks_1[3] + ticks_1[4]   # idle + iowait
    idle_2  = ticks_2[3] + ticks_2[4]
    total_1 = sum(ticks_1)
    total_2 = sum(ticks_2)

    usage_pct = round((1 - (idle_2 - idle_1) / (total_2 - total_1)) * 100, 2)
    cores     = int(run_command(['nproc']) or 0)

    return {'usage_pct': usage_pct, 'cores': cores}


def linux_memory() -> dict:
    """
    Coleta informacoes de memoria diretamente de /proc/meminfo.

    Usa MemAvailable (disponivel para novas alocacoes) em vez de MemFree
    (paginas fisicamente livres), pois MemAvailable considera o cache
    recuperavel pelo kernel â€” metrica mais precisa para monitoramento.
    """
    mem_info: dict[str, int] = {}
    with open('/proc/meminfo', encoding='utf-8') as f:
        for line in f:
            key, value = line.split(':', 1)
            mem_info[key.strip()] = int(value.strip().split()[0])  # valor em kB

    total_kb = mem_info.get('MemTotal',     0)
    avail_kb = mem_info.get('MemAvailable', 0)
    used_kb  = total_kb - avail_kb

    return {
        'total_mb':  round(total_kb / 1024, 0),
        'used_mb':   round(used_kb  / 1024, 0),
        'free_mb':   round(avail_kb / 1024, 0),
        'usage_pct': round(used_kb * 100 / total_kb, 2) if total_kb else 0,
    }


def linux_disk() -> list[dict]:
    """
    Coleta uso de disco via comando df, excluindo sistemas de arquivos virtuais.

    O pipe '| tail -n+2' foi substituido por fatiamento de lista no Python
    (splitlines()[1:]) pois pipes sao recursos do shell e nao funcionam
    com shell=False.

    tmpfs e devtmpfs sao excluidos pois sao sistemas virtuais em memoria
    e nao representam uso real de armazenamento persistente.
    """
    raw = run_command([
        'df',
        '-x', 'tmpfs',
        '-x', 'devtmpfs',
        '--output=target,size,used,avail,pcent',
    ])

    # Ignora a linha de cabecalho (equivalente ao antigo | tail -n+2)
    lines = raw.splitlines()[1:]

    disks = []
    for line in lines:
        parts = line.split()
        if len(parts) < 5:
            continue
        disks.append({
            'mount':     parts[0],
            'total_gb':  round(int(parts[1]) / 1_048_576, 2),
            'used_gb':   round(int(parts[2]) / 1_048_576, 2),
            'free_gb':   round(int(parts[3]) / 1_048_576, 2),
            'usage_pct': float(parts[4].rstrip('%')),
        })
    return disks


def linux_services(service_list: list[str]) -> list[dict]:
    """
    Verifica o estado e a configuracao de inicializacao dos servicos criticos.

    A lista de servicos vem do config.toml via AgentConfig, eliminando
    a dependencia do CONFIG interno. O nome do servico e passado como
    elemento separado da lista (shell=False), impedindo injecao de comandos.

    Exemplos de saida do systemctl:
        is-active:  active | inactive | failed | activating | not-found
        is-enabled: enabled | disabled | static | masked | not-found

    Args:
        service_list: Lista de nomes de servicos Linux a verificar.
    """
    services = []
    for service_name in service_list:
        status  = run_command(['systemctl', 'is-active',  service_name]) or 'not-found'
        enabled = run_command(['systemctl', 'is-enabled', service_name]) or 'unknown'
        services.append({
            'name':    service_name,
            'status':  status,
            'enabled': enabled,
        })
    return services


def linux_uptime() -> int:
    """
    Retorna o tempo de atividade do sistema em segundos, lido de /proc/uptime.

    O arquivo contem dois valores separados por espaco:
        [0] uptime total do sistema (segundos)
        [1] tempo ocioso somado de todos os nucleos
    """
    with open('/proc/uptime', encoding='utf-8') as f:
        return int(float(f.read().split()[0]))


# â”€â”€ ponto de entrada principal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def collect(config: AgentConfig) -> dict:
    """
    Orquestra a coleta de todas as metricas e monta o payload final.

    Recebe o objeto de configuracao como parametro em vez de usar um
    CONFIG global interno. Isso torna a funcao testavel e desacoplada
    do sistema de arquivos.

    O payload segue o envelope padronizado do contrato de API:
        timestamp, hostname, os_family, pilar, metrics

    IMPORTANTE: Este agente NAO inclui campos 'status' ou 'alerts'.
    Toda logica de analise e responsabilidade exclusiva do sistema central.

    Args:
        config: Objeto AgentConfig carregado pelo config_loader.

    Returns:
        Dicionario serializavel em JSON com as metricas brutas coletadas.
    """
    metrics: dict = {}

    if OS_FAMILY == 'windows':
        metrics['cpu']      = win_cpu()
        metrics['memory']   = win_memory()
        metrics['disk']     = win_disk()
        metrics['services'] = win_services(config.operacional.critical_services_windows)
    else:
        metrics['cpu']            = linux_cpu()
        metrics['memory']         = linux_memory()
        metrics['disk']           = linux_disk()
        metrics['services']       = linux_services(config.operacional.critical_services_linux)
        metrics['uptime_seconds'] = linux_uptime()

    return {
        'timestamp':     now_iso(),
        'hostname':      config.global_.hostname,
        'os_family':     OS_FAMILY,
        'pilar':         'operacional',
        'agent_version': AGENT_VERSION,
        'metrics':       metrics,
    }


if __name__ == '__main__':
    _config  = load_config()
    payload  = collect(_config)
    print(json.dumps(payload, indent=2, ensure_ascii=False))

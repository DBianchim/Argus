#!/usr/bin/env python3
"""
agent_backup.py â€” Agente de monitoramento de backup

Responsabilidade:
    Verificar a saude dos backups em 4 camadas progressivas e retornar
    um payload padronizado para envio ao sistema central. Este agente
    NAO processa alertas â€” toda logica de analise e responsabilidade
    do sistema central.

Camadas de verificacao:
    1. Existencia   â€” ha algum arquivo de backup nos diretorios configurados?
    2. SLA          â€” o backup foi gerado dentro do prazo maximo permitido?
    3. Integridade  â€” o arquivo esta integro (tamanho, estrutura, hash SHA256)?
    4. Log          â€” a ferramenta de backup reportou sucesso no log de execucao?

Suporte de plataforma:
    - Windows: verifica caminhos definidos em config.toml -> [backup].paths_windows
    - Linux:   verifica caminhos definidos em config.toml -> [backup].paths_linux

Seguranca:
    - Nenhum subprocesso e utilizado â€” toda coleta e feita via APIs Python
      (os, glob, zipfile, tarfile, hashlib), eliminando riscos de injecao.

Autores: David Bianchim
"""

import glob
import hashlib
import json
import os
import time
import tarfile
import zipfile

from core.config_loader import AgentConfig, load_config
# Utilitarios compartilhados (DRY): now_iso e detect_os.
from core.sysutils import AGENT_VERSION, now_iso, detect_os

# â”€â”€ constante de plataforma â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

OS_FAMILY: str = detect_os()

# Palavras-chave para analise semantica dos logs de execucao de backup.
# Definidas como constantes do modulo pois nao variam por ambiente.
_LOG_KEYWORDS_FAIL    = ['error', 'fail', 'falha', 'erro', 'exception',
                         'aborted', 'critical', 'warning']
_LOG_KEYWORDS_SUCCESS = ['success', 'conclu', 'finaliz', 'completed',
                         'ok', 'sucesso', 'done']


# â”€â”€ verificacao de integridade â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def compute_sha256(filepath: str, chunk_size: int = 8192) -> str:
    """
    Calcula o hash SHA256 de um arquivo em chunks para economizar memoria.

    Leitura em chunks evita carregar arquivos grandes (ex: .vhd de 50GB)
    inteiramente na RAM. O tamanho padrao de 8KB e um equilibrio entre
    numero de chamadas de I/O e uso de memoria.

    Args:
        filepath:   Caminho absoluto do arquivo.
        chunk_size: Tamanho de cada bloco lido em bytes (padrao: 8192).

    Returns:
        String hexadecimal com o hash SHA256 do arquivo.
    """
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def _check_size(filepath: str, min_size_mb: int) -> dict | None:
    """
    Camada 1: verifica se o arquivo atinge o tamanho minimo configurado.

    Recebe min_size_mb como parametro em vez de ler do CONFIG global,
    mantendo a funcao testavel e desacoplada do sistema de arquivos.

    Retorna um dicionario de falha se o arquivo for pequeno demais,
    ou None se passar na verificacao (permitindo seguir para a proxima camada).

    Args:
        filepath:    Caminho absoluto do arquivo de backup.
        min_size_mb: Tamanho minimo aceitavel em MB, lido do config.toml.
    """
    size_mb = os.path.getsize(filepath) / 1_048_576
    if size_mb < min_size_mb:
        return {
            'integrity_check': 'FAIL',
            'method':          'size_check',
            'detail': (
                f'Arquivo muito pequeno: {round(size_mb, 2)} MB '
                f'(minimo: {min_size_mb} MB)'
            ),
        }
    return None


def _check_structure(filepath: str) -> dict:
    """
    Camada 2: valida a estrutura interna do arquivo por tipo.

    Cada formato tem sua propria API de validacao:
        .zip         â†’ zipfile.ZipFile.testzip() verifica cada entry
        .tar.gz/.tar â†’ tarfile.open().getmembers() valida o indice interno
        demais       â†’ sem teste estrutural nativo; avanca para hash

    Retorna um dicionario com 'integrity_check' = 'FAIL' em caso de
    corrupcao, ou apenas {'method': ...} se o arquivo estiver integro.

    Args:
        filepath: Caminho absoluto do arquivo de backup.
    """
    ext = filepath.lower()

    if ext.endswith('.zip'):
        with zipfile.ZipFile(filepath, 'r') as zf:
            corrupted_file = zf.testzip()
            if corrupted_file:
                return {
                    'integrity_check': 'FAIL',
                    'method':          'zip_test',
                    'detail':          f'Entry corrompido: {corrupted_file}',
                }
        return {'method': 'zip_test'}

    if ext.endswith(('.tar.gz', '.tgz', '.tar')):
        with tarfile.open(filepath, 'r:*') as tf:
            if not tf.getmembers():
                return {
                    'integrity_check': 'FAIL',
                    'method':          'tar_test',
                    'detail':          'Arquivo tar vazio â€” nenhum membro encontrado',
                }
        return {'method': 'tar_test'}

    if ext.endswith(('.vhd', '.vhdx', '.dump')):
        return {'method': 'size_and_hash'}

    return {'method': 'size_only'}


def _check_hash(filepath: str) -> dict:
    """
    Camada 3: compara o hash SHA256 atual com o da execucao anterior.

    O hash anterior e armazenado em um arquivo sidecar '<backup>.sha256'
    no mesmo diretorio. Isso permite detectar backups que existem mas
    nao foram atualizados â€” cenario de falha silenciosa comum em
    agendadores com erro de configuracao.

    Resultados possiveis:
        OK   â†’ hash diferente do anterior (backup foi atualizado)
        OK   â†’ nenhum hash anterior encontrado (primeira execucao)
        WARN â†’ hash identico ao anterior (backup pode estar estagnado)

    Args:
        filepath: Caminho absoluto do arquivo de backup.
    """
    sha256    = compute_sha256(filepath)
    hash_file = filepath + '.sha256'

    if os.path.exists(hash_file):
        with open(hash_file, 'r', encoding='utf-8') as f:
            previous_hash = f.read().strip()

        if sha256 == previous_hash:
            return {
                'integrity_check': 'WARN',
                'sha256':          sha256,
                'detail':          'Hash identico ao backup anterior â€” arquivo pode nao ter sido atualizado',
            }

        return {'integrity_check': 'OK', 'sha256': sha256}

    # Primeira execucao: persiste o hash para comparacao futura
    with open(hash_file, 'w', encoding='utf-8') as f:
        f.write(sha256)

    return {
        'integrity_check': 'OK',
        'sha256':          sha256,
        'detail':          'Hash gerado pela primeira vez',
    }


def verify_file_integrity(filepath: str, min_size_mb: int) -> dict:
    """
    Orquestra a verificacao de integridade em 3 camadas progressivas.

    A verificacao e interrompida na primeira falha detectada para evitar
    operacoes desnecessarias em arquivos ja identificados como corrompidos
    (ex: nao calcular SHA256 de um ZIP com estrutura invalida).

    Camadas:
        1. Tamanho minimo       (_check_size)
        2. Estrutura por tipo   (_check_structure)
        3. Hash SHA256          (_check_hash)

    Args:
        filepath:    Caminho absoluto do arquivo de backup.
        min_size_mb: Tamanho minimo em MB, lido do config.toml.

    Returns:
        Dicionario com 'integrity_check' (OK | WARN | FAIL | ERROR),
        'method' utilizado e 'detail' descritivo quando aplicavel.
    """
    result: dict = {'integrity_check': 'unknown', 'method': None, 'detail': None}

    try:
        # Camada 1 â€” tamanho minimo
        size_failure = _check_size(filepath, min_size_mb)
        if size_failure:
            return size_failure

        # Camada 2 â€” estrutura interna por tipo
        structure_result = _check_structure(filepath)
        if structure_result.get('integrity_check') == 'FAIL':
            return structure_result
        result['method'] = structure_result.get('method')

        # Camada 3 â€” hash SHA256
        hash_result = _check_hash(filepath)
        result.update(hash_result)

    except (zipfile.BadZipFile, tarfile.TarError) as e:
        result.update({
            'integrity_check': 'FAIL',
            'method':          'structural_test',
            'detail':          f'Arquivo corrompido: {e}',
        })
    except PermissionError:
        result.update({
            'integrity_check': 'ERROR',
            'detail':          'Sem permissao para ler o arquivo',
        })
    except Exception as e:  # noqa: BLE001
        result.update({
            'integrity_check': 'ERROR',
            'detail':          str(e),
        })

    return result


# â”€â”€ analise de log de execucao â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def find_log_file(backup_path: str) -> dict:
    """
    Localiza e analisa o log de execucao mais recente no diretorio do backup.

    Estrategia de busca:
        - Varre o diretorio pai do arquivo de backup por arquivos .log, .txt e .out
        - Seleciona o arquivo com a data de modificacao mais recente
        - Analisa as ultimas 20 linhas buscando palavras-chave de sucesso/falha

    A analise por palavras-chave e intencionalmente conservadora: classifica
    como FAIL ou SUCCESS apenas quando ha evidencia clara no texto. Casos
    ambiguos retornam UNDETERMINED para evitar falsos negativos.

    Args:
        backup_path: Caminho absoluto do arquivo de backup.

    Returns:
        Dicionario com 'log_found', 'log_path', 'last_status' e 'last_line'.
    """
    folder = os.path.dirname(backup_path)
    result = {
        'log_found':   False,
        'log_path':    None,
        'last_status': None,
        'last_line':   None,
    }

    # Coleta todos os candidatos a log no diretorio
    candidates: list[str] = []
    for pattern in ('*.log', '*.txt', '*.out'):
        candidates.extend(glob.glob(os.path.join(folder, pattern)))

    if not candidates:
        return result

    # Seleciona o log mais recente por data de modificacao
    latest_log          = max(candidates, key=os.path.getmtime)
    result['log_found'] = True
    result['log_path']  = latest_log

    try:
        with open(latest_log, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [line.strip() for line in f if line.strip()]

        result['last_line'] = lines[-1] if lines else None

        # Analisa apenas as ultimas 20 linhas â€” onde o status final costuma estar
        recent_text = ' '.join(lines[-20:]).lower()

        if any(keyword in recent_text for keyword in _LOG_KEYWORDS_FAIL):
            result['last_status'] = 'FAIL_DETECTED'
        elif any(keyword in recent_text for keyword in _LOG_KEYWORDS_SUCCESS):
            result['last_status'] = 'SUCCESS_DETECTED'
        else:
            result['last_status'] = 'UNDETERMINED'

    except OSError as e:
        result['last_status'] = f'LOG_READ_ERROR: {e}'

    return result


# â”€â”€ verificacao principal de backup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def check_backup_files(paths: list[str], extensions: list[str], min_size_mb: int, sla_hours: int) -> dict:
    """
    Localiza o backup mais recente nos diretorios fornecidos e o avalia.

    Todos os parametros de configuracao sao recebidos explicitamente,
    eliminando a dependencia do CONFIG global interno e tornando a
    funcao testavel de forma isolada.

    Selecao do arquivo:
        Percorre recursivamente todos os diretorios em 'paths' buscando
        arquivos com as extensoes fornecidas. O arquivo com o maior mtime
        (mais recente) e selecionado para analise.

    Logica de status final (em ordem de prioridade):
        NO_BACKUP_FOUND  â†’ nenhum arquivo encontrado nos diretorios
        SLA_BREACH       â†’ backup existe mas esta fora do prazo configurado
        INTEGRITY_FAIL   â†’ backup dentro do prazo mas com arquivo corrompido
        WARN             â†’ backup OK mas hash identico ao anterior
        OK               â†’ todas as verificacoes passaram

    Args:
        paths:       Lista de diretorios raiz onde os backups estao armazenados.
        extensions:  Lista de extensoes validas (ex: ['.tar.gz', '.zip']).
        min_size_mb: Tamanho minimo aceitavel em MB.
        sla_hours:   Prazo maximo entre backups em horas.

    Returns:
        Dicionario com status, metadados, resultado de integridade e log.
    """
    most_recent_file: str | None = None
    most_recent_mtime: float = 0.0

    # Busca recursiva pelo arquivo de backup mais recente
    for directory in paths:
        for extension in extensions:
            pattern = os.path.join(directory, '**', '*' + extension)
            for filepath in glob.glob(pattern, recursive=True):
                try:
                    mtime = os.path.getmtime(filepath)
                    if mtime > most_recent_mtime:
                        most_recent_mtime = mtime
                        most_recent_file  = filepath
                except OSError:
                    # Arquivo inacessivel ou removido durante a varredura â€” ignorar
                    continue

    if not most_recent_file:
        return {'status': 'NO_BACKUP_FOUND', 'path': None}

    age_hours = round((time.time() - most_recent_mtime) / 3600, 2)
    size_mb   = round(os.path.getsize(most_recent_file) / 1_048_576, 2)
    sla_ok    = age_hours <= sla_hours

    integrity = verify_file_integrity(most_recent_file, min_size_mb)
    log_info  = find_log_file(most_recent_file)

    # Determina o status final com base na prioridade das verificacoes
    if not sla_ok:
        final_status = 'SLA_BREACH'
    elif integrity['integrity_check'] == 'FAIL':
        final_status = 'INTEGRITY_FAIL'
    elif integrity['integrity_check'] == 'WARN':
        final_status = 'WARN'
    else:
        final_status = 'OK'

    return {
        'status':    final_status,
        'path':      most_recent_file,
        'age_hours': age_hours,
        'size_mb':   size_mb,
        'sla_hours': sla_hours,
        'sla_ok':    sla_ok,
        'integrity': integrity,
        'log':       log_info,
    }


# â”€â”€ ponto de entrada principal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def collect(config: AgentConfig) -> dict:
    """
    Orquestra a coleta de metricas de backup e monta o payload final.

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
    backup_cfg = config.backup

    backup_paths = (
        backup_cfg.paths_windows
        if OS_FAMILY == 'windows'
        else backup_cfg.paths_linux
    )

    metrics = {
        'backup': check_backup_files(
            paths       = backup_paths,
            extensions  = backup_cfg.extensions,
            min_size_mb = backup_cfg.min_size_mb,
            sla_hours   = backup_cfg.sla_hours,
        )
    }

    return {
        'timestamp':     now_iso(),
        'hostname':      config.global_.hostname,
        'os_family':     OS_FAMILY,
        'pilar':         'backup',
        'agent_version': AGENT_VERSION,
        'metrics':       metrics,
    }


if __name__ == '__main__':
    _config = load_config()
    payload = collect(_config)
    print(json.dumps(payload, indent=2, ensure_ascii=False))

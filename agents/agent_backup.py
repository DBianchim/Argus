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
    3. Integridade  â€” o arquivo esta integro (tamanho, estrutura, hash SHA256)
                      e o backup mais recente difere do anterior (estagnacao)?
    4. Log          â€” a ferramenta de backup reportou sucesso no log de execucao?

Suporte de plataforma:
    - Windows: verifica caminhos definidos em config.toml -> [backup].paths_windows
    - Linux:   verifica caminhos definidos em config.toml -> [backup].paths_linux

Estado:
    - O ultimo backup observado (caminho, mtime, tamanho, SHA256) fica em
      'backup_state.json', ao lado da fila local (retry.queue_path) - nunca no
      diretorio de backup, que pode ser somente leitura.

Seguranca:
    - Nenhum subprocesso e utilizado â€” toda coleta e feita via APIs Python
      (os, glob, zipfile, tarfile, hashlib), eliminando riscos de injecao.

Autores: David Bianchim
"""

import glob
import hashlib
import json
import logging
import os
import time
import tarfile
import zipfile

from core.config_loader import AgentConfig, load_config
# Utilitarios compartilhados (DRY): now_iso e detect_os.
from core.sysutils import AGENT_VERSION, now_iso, detect_os, state_file_path

logger = logging.getLogger(__name__)

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


# -- estado persistente (ultimo backup observado) ----------------------------------------

STATE_FILENAME = 'backup_state.json'
_STATE_VERSION = 1

_STAGNANT_DETAIL = (
    'Backup novo com SHA256 identico ao backup anterior '
    '- o conteudo nao mudou entre as duas execucoes'
)


def _is_sha256(value) -> bool:
    """True se value e uma string hexadecimal de 64 caracteres."""
    return (isinstance(value, str) and len(value) == 64
            and all(c in '0123456789abcdef' for c in value.lower()))


def _file_signature(filepath: str) -> dict:
    """
    Assinatura barata de um arquivo: caminho, mtime (ns) e tamanho (bytes).

    Dois estados com a mesma assinatura sao tratados como o MESMO arquivo,
    inalterado, o que dispensa recalcular o SHA256 (caro em arquivos grandes).
    """
    st = os.stat(filepath)
    return {'path': filepath, 'mtime_ns': st.st_mtime_ns, 'size': st.st_size}


def load_state(state_path: str | None) -> dict | None:
    """
    Le o ultimo backup observado do arquivo de estado.

    Tolerante a ausencia e a corrupcao: nunca levanta excecao. Retorna None
    quando nao ha estado utilizavel (primeira execucao, arquivo invalido ou
    caminho de estado nao configurado) - o chamador trata como primeira
    observacao.

    Returns:
        Dicionario com path, mtime_ns, size, sha256, previous_sha256 e
        stagnant, ou None.
    """
    if not state_path:
        return None
    try:
        with open(state_path, 'r', encoding='utf-8') as f:
            last = json.load(f)['last']
        entry = {
            'path':            last['path'],
            'mtime_ns':        last['mtime_ns'],
            'size':            last['size'],
            'sha256':          last['sha256'],
            'previous_sha256': last.get('previous_sha256'),
            'stagnant':        bool(last.get('stagnant', False)),
        }
        valid = (
            isinstance(entry['path'], str)
            and isinstance(entry['mtime_ns'], int)
            and isinstance(entry['size'], int)
            and _is_sha256(entry['sha256'])
            and (entry['previous_sha256'] is None or _is_sha256(entry['previous_sha256']))
        )
        if not valid:
            raise ValueError('campos invalidos')
        return entry
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        logger.warning('Estado do backup invalido, sera recriado | erro=%s', type(e).__name__)
        return None


def save_state(state_path: str, entry: dict) -> str | None:
    """
    Grava o ultimo backup observado de forma atomica (tmp + os.replace).

    A escrita atomica evita deixar um JSON truncado se o agente for
    encerrado no meio da gravacao.

    Returns:
        None em sucesso; mensagem de erro (str) em falha - nunca levanta.
    """
    tmp_path = f'{state_path}.{os.getpid()}.tmp'
    try:
        os.makedirs(os.path.dirname(state_path) or '.', exist_ok=True)
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump({'version': _STATE_VERSION, 'last': entry}, f)
        os.replace(tmp_path, state_path)
        return None
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return str(e)


def _check_hash(filepath: str, previous: dict | None, signature: dict) -> dict:
    """
    Camada 3: detecta backup estagnado comparando o SHA256 com o do backup
    anterior observado.

    'previous' e a ultima observacao gravada no arquivo de estado (ver
    load_state). Estagnado significa: o backup mais recente e uma observacao
    NOVA (caminho diferente, ou mesmo caminho com mtime/tamanho alterados)
    mas com SHA256 identico ao da observacao anterior - cenario de falha
    silenciosa comum em agendadores mal configurados (o job roda, mas gera o
    mesmo conteudo de sempre).

    Observar o MESMO arquivo, inalterado, em ciclos consecutivos nao e
    estagnacao: a idade do backup e coberta pelo SLA. Nesse caso o hash
    guardado e reutilizado (sem reler o arquivo) e o veredito da observacao
    e mantido - um backup estagnado continua em WARN ate chegar um backup
    novo com conteudo diferente.

    Resultados possiveis:
        OK   -> primeira observacao (sem referencia anterior)
        OK   -> SHA256 diferente do backup anterior
        OK   -> mesmo arquivo, inalterado, ja considerado saudavel
        WARN -> backup novo com SHA256 identico ao anterior (estagnado)

    O dicionario inclui 'sha256', 'previous_sha256', 'stagnant' e
    'hash_source' ('computed' | 'cached'). A gravacao do estado e feita por
    check_backup_files, nao aqui.

    Args:
        filepath:  Caminho absoluto do arquivo de backup.
        previous:  Ultima observacao gravada, ou None na primeira execucao.
        signature: Assinatura atual do arquivo (ver _file_signature).
    """
    # Mesmo arquivo, inalterado: reaproveita hash e veredito guardados
    if previous and all(previous[k] == signature[k] for k in ('path', 'mtime_ns', 'size')):
        stagnant = previous['stagnant']
        result = {
            'integrity_check': 'WARN' if stagnant else 'OK',
            'sha256':          previous['sha256'],
            'previous_sha256': previous['previous_sha256'],
            'stagnant':        stagnant,
            'hash_source':     'cached',
        }
        if stagnant:
            result['detail'] = _STAGNANT_DETAIL
        return result

    sha256 = compute_sha256(filepath)

    if previous is None:
        return {
            'integrity_check': 'OK',
            'sha256':          sha256,
            'previous_sha256': None,
            'stagnant':        False,
            'hash_source':     'computed',
            'detail':          'Primeira observacao do backup (sem referencia anterior)',
        }

    stagnant = sha256 == previous['sha256']
    result = {
        'integrity_check': 'WARN' if stagnant else 'OK',
        'sha256':          sha256,
        'previous_sha256': previous['sha256'],
        'stagnant':        stagnant,
        'hash_source':     'computed',
    }
    if stagnant:
        result['detail'] = _STAGNANT_DETAIL
    return result


def verify_file_integrity(
    filepath: str,
    min_size_mb: int,
    previous: dict | None = None,
    signature: dict | None = None,
) -> dict:
    """
    Orquestra a verificacao de integridade em 3 camadas progressivas.

    A verificacao e interrompida na primeira falha detectada para evitar
    operacoes desnecessarias em arquivos ja identificados como corrompidos
    (ex: nao calcular SHA256 de um ZIP com estrutura invalida).

    Camadas:
        1. Tamanho minimo       (_check_size)
        2. Estrutura por tipo   (_check_structure)
        3. Hash SHA256 vs backup anterior (_check_hash)

    Args:
        filepath:    Caminho absoluto do arquivo de backup.
        min_size_mb: Tamanho minimo em MB, lido do config.toml.
        previous:    Ultima observacao gravada (load_state); None = primeira.
        signature:   Assinatura do arquivo (_file_signature); calculada aqui
                     se omitida.

    Returns:
        Dicionario com 'integrity_check' (OK | WARN | FAIL | ERROR),
        'method' utilizado e 'detail' descritivo quando aplicavel. Quando a
        camada 3 e alcancada, inclui tambem 'sha256', 'previous_sha256',
        'stagnant' e 'hash_source'.
    """
    result: dict = {'integrity_check': 'unknown', 'method': None, 'detail': None}

    try:
        # Camada 1 - tamanho minimo
        size_failure = _check_size(filepath, min_size_mb)
        if size_failure:
            return size_failure

        # Camada 2 - estrutura interna por tipo
        structure_result = _check_structure(filepath)
        if structure_result.get('integrity_check') == 'FAIL':
            return structure_result
        result['method'] = structure_result.get('method')

        # Camada 3 - hash SHA256 contra o backup anterior observado
        hash_result = _check_hash(filepath, previous, signature or _file_signature(filepath))
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

def check_backup_files(
    paths: list[str],
    extensions: list[str],
    min_size_mb: int,
    sla_hours: int,
    state_path: str | None = None,
) -> dict:
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
        WARN             â†’ backup estagnado (novo, mas SHA256 identico ao anterior)
                          ou integridade nao verificavel (ex: sem permissao de leitura)
        OK               â†’ todas as verificacoes passaram

    Estagnacao:
        Comparada com o ultimo backup observado, guardado em 'state_path'
        (fora do diretorio de backup). Sem state_path nao ha referencia
        anterior e a estagnacao nao e detectada. Ver _check_hash.

    Args:
        paths:       Lista de diretorios raiz onde os backups estao armazenados.
        extensions:  Lista de extensoes validas (ex: ['.tar.gz', '.zip']).
        min_size_mb: Tamanho minimo aceitavel em MB.
        sla_hours:   Prazo maximo entre backups em horas.
        state_path:  Arquivo de estado do ultimo backup observado (opcional).

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

    # Assinatura tomada ANTES do hash: se o arquivo mudar durante a leitura,
    # o proximo ciclo enxerga assinatura diferente e recalcula.
    signature = _file_signature(most_recent_file)
    age_hours = round((time.time() - most_recent_mtime) / 3600, 2)
    size_mb   = round(signature['size'] / 1_048_576, 2)
    sla_ok    = age_hours <= sla_hours

    previous  = load_state(state_path)
    integrity = verify_file_integrity(most_recent_file, min_size_mb, previous, signature)
    log_info  = find_log_file(most_recent_file)

    # Persiste a nova observacao (so quando o hash foi calculado agora; backups
    # que falharam em tamanho/estrutura ou deram ERROR nao viram referencia)
    if state_path and integrity.get('hash_source') == 'computed':
        entry = {
            **signature,
            'sha256':          integrity['sha256'],
            'previous_sha256': integrity['previous_sha256'],
            'stagnant':        integrity['stagnant'],
        }
        state_error = save_state(state_path, entry)
        if state_error:
            integrity['state_warning'] = f'Nao foi possivel gravar o estado do backup: {state_error}'
            logger.warning('Falha ao gravar estado do backup | erro=%s', state_error)

    # Determina o status final com base na prioridade das verificacoes.
    # ERROR (ex: leitura negada) nao pode virar OK - o backup nao foi verificado.
    if not sla_ok:
        final_status = 'SLA_BREACH'
    elif integrity['integrity_check'] == 'FAIL':
        final_status = 'INTEGRITY_FAIL'
    elif integrity['integrity_check'] in ('WARN', 'ERROR'):
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
            state_path  = state_file_path(config.retry.queue_path, STATE_FILENAME),
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

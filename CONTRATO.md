# Contrato Agente ↔ API — Argus

Este documento define o contrato entre os agentes e a API central. **Toda evolução
dos agentes ou da API deve respeitar estas regras** — elas são o que permite atualizar
a frota de servidores gradualmente, sem quebrar o dashboard nem o histórico.

---

## 1. Envelope do payload

Todo payload enviado em `POST /api/v1/ingest` tem este formato:

```json
{
  "timestamp":     "2026-06-09T23:02:21Z",
  "hostname":      "DESKTOP-G6ID80A",
  "os_family":     "windows",
  "pilar":         "operacional",
  "agent_version": "1.0.0",
  "metrics":       { ... }
}
```

| Campo | Tipo | Obrigatório | Regra |
|-------|------|-------------|-------|
| `timestamp` | string ISO 8601 UTC (`...Z`) | sim | Momento da coleta |
| `hostname` | string não-vazia | sim | Identidade informativa (a identidade real é o token) |
| `os_family` | `windows` \| `linux` | sim | — |
| `pilar` | `operacional` \| `backup` \| `acesso` \| `logs` | sim | Novo pilar = mudança de contrato (ver §4) |
| `agent_version` | string (ex.: `1.0.0`) | não* | Versão do pacote de agentes (`core/sysutils.py: AGENT_VERSION`) |
| `metrics` | objeto não-vazio | sim | Conteúdo livre por pilar — regido pela regra aditiva (§3) |

\* Opcional na API para tolerar agentes antigos; **todo agente atual deve enviá-lo**.

## 2. Códigos HTTP e comportamento do agente

A API **deve** usar estes códigos, pois o agente reage a eles (`agents/core/sender.py`):

| Código | Significado | Reação do agente |
|--------|-------------|------------------|
| **200** | Aceito (deve ser exatamente 200) | Sucesso — segue o ciclo |
| **401** | Token inválido/revogado | **Descarta** o payload (não retenta) |
| **422** | Corpo inválido (falha de schema) | **Descarta** o payload (não retenta) |
| **400 / 403** | Erro de dados/permissão | **Descarta** o payload |
| **503** / timeout / conexão | Indisponibilidade transitória | **Retenta** (backoff) e **enfileira** localmente |

Regra prática para a API: problema no *dado* → 4xx (descartar); problema no *servidor*
→ 503 (o dado é bom, virá de novo).

## 3. Regra de compatibilidade ADITIVA (a regra de ouro)

Em produção, a frota nunca é atualizada toda de uma vez — a API sempre receberá
versões diferentes de agente simultaneamente. Para isso funcionar:

**Os agentes podem:**
- ✅ ADICIONAR novas chaves dentro de `metrics` (em qualquer nível);
- ✅ ADICIONAR novos findings/coletores nos pilares `acesso`/`logs`.

**Os agentes NÃO podem:**
- ❌ RENOMEAR uma chave existente (`usage_pct` → `percent_used`);
- ❌ REMOVER uma chave existente;
- ❌ MUDAR O TIPO de um valor (`"count": 5` → `"count": "5"`);
- ❌ Mudar a semântica de um valor mantendo o nome (ex.: MB → GB).

**A central (API/dashboard) deve:**
- ✅ Tolerar chaves ausentes — sempre `dict.get("chave")`, nunca `dict["chave"]`;
- ✅ Ignorar chaves desconhecidas (agente mais novo que o dashboard);
- ✅ Nunca rejeitar um payload pelo *conteúdo* de `metrics` (a validação é só do envelope).

## 4. Mudanças que quebram (quando inevitáveis): processo de depreciação

1. A versão nova do agente envia **as duas chaves** (antiga e nova) lado a lado;
2. `AGENT_VERSION` é incrementada; o dashboard passa a ler a chave nova com fallback
   para a antiga;
3. A frota é atualizada gradualmente — `agent_version` em cada linha do banco mostra
   quem ainda envia o formato antigo (`manage.py list-servers` + consulta);
4. Quando 100% da frota estiver na versão nova, uma release futura remove a chave antiga.

Novo **pilar** segue o mesmo espírito: adicionar o valor ao `Literal` da API **antes**
de ativar o agente novo na frota (API tolera primeiro, agente envia depois).

## 5. Versionamento

- `AGENT_VERSION` vive em `agents/core/sysutils.py` — fonte única (runner e os 4
  agentes leem dela) e viaja em todo payload.
- Incrementar a cada release que altere coleta ou contrato:
  - **patch** (1.0.x): correções sem mudança de payload;
  - **minor** (1.x.0): chaves novas (aditivas);
  - **major** (x.0.0): processo de depreciação concluído (remoção de chave antiga).

## 6. Pilar `backup`: campos de integridade e estagnação (1.1.0)

Chaves **aditivas** em `metrics.backup.integrity`, enviadas pelo agente a partir da
`AGENT_VERSION` 1.1.0. Todas são opcionais para a central (`.get()`); agentes anteriores
não as enviam e continuam sendo aceitos.

| Chave | Tipo | Significado |
|-------|------|-------------|
| `sha256` | string | Hash do backup mais recente (já existia) |
| `previous_sha256` | string \| null | Hash do backup observado antes dele; `null` na primeira observação |
| `stagnant` | boolean | `true` quando o backup é **novo** (caminho diferente, ou mesmo caminho com mtime/tamanho alterados) mas tem o **mesmo** SHA-256 do anterior |
| `hash_source` | `computed` \| `cached` | `cached` = mesmo arquivo, inalterado, hash reaproveitado do estado do agente |
| `state_warning` | string | Só presente se o agente não conseguiu gravar seu estado local |

Semântica:

- Observar o **mesmo arquivo inalterado** em ciclos consecutivos **não** é estagnação — a
  idade do backup é tratada pelo SLA (`SLA_BREACH`). Um backup marcado `stagnant` continua
  assim até chegar um backup novo com conteúdo diferente.
- O agente guarda o último backup observado em `backup_state.json`, ao lado da fila local
  (`retry.queue_path`), nunca no diretório monitorado.
- `integrity.integrity_check = "ERROR"` (ex.: leitura negada) deixa de ser mascarado: o
  `status` do pilar passa a `WARN` e o motor da central gera o alerta
  "Integridade do backup não verificada" com o `detail`. A central também aplica essa regra
  a payloads de agentes anteriores que enviaram `ERROR` com `status: "OK"`.
- `status` desconhecido para a central é avaliado como `unknown` (sem alerta), e não mais `ok`.

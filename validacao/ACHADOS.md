# Catálogo de achados da validação do Argus

Este documento cataloga os **18 achados** registrados durante a validação do Argus, sistema descrito no artigo *Argus: sistema de monitoramento de infraestrutura com base nas práticas de SOC*. Para cada achado constam a causa raiz, o impacto, o status e a evidência. A contagem aqui apresentada é a referência dos números citados na Discussão e na Conclusão do artigo.

## 1. Escopo e convenções

**Definição de achado.** Defeito, limitação, divergência ou comportamento inesperado observado durante a validação e registrado com evidência. Dois registros que não representam defeito do sistema constam na seção 4 e não entram na contagem. As quatro correções da versão 1.3.0 do agente constam na seção 5, pois resultaram de revisão de código posterior aos cenários.

**Versões de referência**

| Marcação | Conteúdo |
|---|---|
| tag `validacao-cenarios` | código sobre o qual os cenários foram executados (21 a 24 de outubro de 2026) |
| tag `agente-1.2.0` | correções motivadas pela validação, verificadas em 24 de outubro de 2026 |
| agente 1.3.0 | versão atual do agente (seção 5) |

**Categorias**

| Sigla | Categoria |
|---|---|
| S | Defeito do sistema (agente ou central) |
| L | Limitação de projeto ou de coleta |
| U | Melhoria de usabilidade |
| E | Ambiente, implantação, ferramental ou documentação |

Os identificadores CT01 a CT14 correspondem aos cenários de teste do Quadro 2 do artigo.

## 2. Resumo

### Distribuição por categoria

| Categoria | Qtde. | IDs |
|---|---|---|
| S: defeito do sistema | 7 | A01, A03, A05, A07, A08, A09, A11 |
| L: limitação de projeto ou de coleta | 4 | A04, A10, A12, A13 |
| U: melhoria de usabilidade | 2 | A06, A18 |
| E: ambiente, implantação, ferramental e documentação | 5 | A02, A14, A15, A16, A17 |
| **Total** | **18** | |

### Distribuição por status

| Status | Qtde. | IDs |
|---|---|---|
| Corrigido na 1.2.0 | 5 | A01, A03, A07, A09, A11 |
| Corrigido antes dos cenários | 1 | A08 |
| Aberto (limitação conhecida) | 7 | A04, A05, A06, A10, A12, A13, A18 |
| Ambiente, ferramental ou documentação (sem correção de código) | 5 | A02, A14, A15, A16, A17 |
| **Total** | **18** | |

### Defeitos do sistema

Dos 7 defeitos classificados como categoria S, 5 foram corrigidos na versão 1.2.0 em resposta à validação (A01, A03, A07, A09 e A11), 1 foi corrigido antes da execução dos cenários (A08) e 1 permanece aberto (A05).

### Relação dos achados

| ID | Achado | Cat. | Gravidade | Cenário | Status |
|---|---|---|---|---|---|
| A01 | Estado do backup não é persistido no Linux; estagnação nunca detectada | S | Alta | CT03 | Corrigido na 1.2.0 |
| A02 | Agentes defasados na frota (1.0.0 com o repositório em 1.1.0) | E | Baixa | CT03 | Parcial |
| A03 | Execução duplicada do agente no Windows | S | Média | CT01, CT06, CT07 | Corrigido na 1.2.0 |
| A04 | Ausência de notificação quando o servidor já está crítico | L | Média | CT02, CT03 | Aberto |
| A05 | Reconhecimento antigo reaplicado a alerta novo | S | Média | CT02 | Aberto |
| A06 | Alerta de integridade sem a causa | U | Baixa | CT03 | Aberto |
| A07 | Falso positivo de `cron` e `sshd` no Ubuntu | S | Baixa | CT13 | Corrigido na 1.2.0 |
| A08 | Rajada de notificações repetidas | S | Média | CT05 (histórico) | Corrigido antes dos cenários |
| A09 | Falhas de logon no Linux não coletadas e sem sinalização | S | Alta | CT11, CT13 | Corrigido na 1.2.0 |
| A10 | Contagem de falhas de logon do Windows satura em 100 | L | Baixa | CT11, CT13 | Aberto |
| A11 | Lacunas de cobertura do Linux em instalação mínima | S | Média | CT13 | Corrigido na 1.2.0 (parcial) |
| A12 | Limite de requisições compartilhado por toda a frota | L | Média | CT12 | Aberto |
| A13 | Janela de notificações da API sem paginação retroativa | L | Baixa | CT05 | Aberto |
| A14 | Latência de persistência dependente do estado do host | E | Média | CT09 | Tratado no CT09 |
| A15 | Ferramenta de carga do repositório inoperante em implantação Compose | E | Baixa | CT09 | Parcial |
| A16 | Divergências de documentação | E | Baixa | CT10, CT13 | Aberto |
| A17 | Falhas do ambiente de teste (certificado, suspensão do host, relógio) | E | Baixa | preparo e reteste | Não aplicável |
| A18 | Nome de host divergente gera aviso em todo envio | U | Baixa | log da API (sem cenário específico) | Aberto |

## 3. Fichas

Os caminhos de evidência partem da raiz do repositório. Os arquivos de `validacao/evidencias/` são cópias das saídas originais, com endereços de rede internos e nomes de usuário substituídos por marcadores.

### A01: Estado do backup não é persistido no Linux; estagnação nunca detectada

| Campo | Valor |
|---|---|
| Categoria / gravidade | S / Alta |
| Cenário | CT03 |
| Descrição | Em instalações Linux feitas pelo instalador, o agente não gravava `backup_state.json` nem `config_cache.json`. Sem o registro do backup anterior, o resumo SHA-256 não era comparado e a estagnação não era detectada. |
| Causa raiz | A unit do systemd usava `ProtectSystem=strict` e liberava escrita apenas na pasta da fila e na de logs. O agente grava o estado na pasta pai da fila, criada pelo instalador com dono `root`. Os envios traziam `state_warning` com `Read-only file system`. |
| Impacto | A funcionalidade central do artigo, a detecção de estagnação, não operava no Linux na instalação padrão. |
| Evidência | `validacao/evidencias/A01/passo3-latest.json` (campo `state_warning`); `validacao/evidencias/A01/ct03-linux-acompanhamento.txt` (reteste) |
| Status | **Corrigido na 1.2.0** |
| Correção | O instalador passou a liberar a pasta de estado, definir o dono correto e conceder acesso ao journal (`a91656d`). O agente passou a emitir aviso quando a pasta de estado não é gravável (`4c98557`). |
| Verificação | Reteste do CT03 em instalação nova, sem ajuste manual, em 24/10/2026: aviso de estagnação em 79 s, retorno a normal em 34 s, falha de integridade em 63 s e nenhum envio com `state_warning`. Testes automatizados em `tests/test_agent_backup.py`. |

### A02: Agentes defasados na frota

| Campo | Valor |
|---|---|
| Categoria / gravidade | E / Baixa |
| Cenário | CT03 (preparo) |
| Descrição | No início da validação os três agentes reportavam a versão 1.0.0, enquanto o repositório estava na 1.1.0. Na 1.0.0, a detecção de estagnação grava o resumo em um arquivo `<backup>.sha256` dentro da pasta monitorada. |
| Causa raiz | A atualização do agente é manual; não há mecanismo de atualização da frota. |
| Impacto | O comportamento dos servidores diferia do código do repositório. |
| Evidência | `validacao/evidencias/A02/agentes-versao.txt` |
| Status | **Parcial** |
| Tratamento | UBUNTU26 e WINSRV2016-TEST foram atualizados (1.1.0 em 22/10 e 1.2.0 em 24/10). O DESKTOP-G6ID80A permanecia na 1.0.0 no último registro, de 23/10. O artigo declara que um servidor ainda operava com a 1.0.0 ao término do trabalho. |

### A03: Execução duplicada do agente no Windows

| Campo | Valor |
|---|---|
| Categoria / gravidade | S / Média |
| Cenário | CT01, CT06, CT07 |
| Descrição | O comando `Stop-ScheduledTask` deixa a tarefa em `Ready`, mas o processo `runner.py` continua em execução. O reinício recomendado (`Stop` seguido de `Start`) podia resultar em dois agentes simultâneos. |
| Causa raiz | O agente não implementa o protocolo de serviços do Windows e executa como tarefa agendada, de modo que parar a tarefa não encerra o processo. Não havia proteção contra instâncias duplicadas. |
| Impacto | Envios duplicados e ciclos irregulares: 24 ciclos em 12 min no CT01, com intervalos alternados de 17 s e 43 s; e reenvios duplicados da fila no CT06 de julho. |
| Evidência | `validacao/evidencias/A03/log-acoes.txt` (CT07); `validacao/evidencias/A03/winsrv-log-ct06-trecho.txt` (reenvio duplicado); `validacao/evidencias/A03/reteste-instancia-unica.md` (reteste) |
| Status | **Corrigido na 1.2.0** |
| Correção | Trava de instância única baseada em `agent.lock`, com encerramento do segundo processo com código 3 (`4c98557`), e correção do procedimento de reinício na documentação de instalação (`477882b`). |
| Verificação | WINSRV2016-TEST, 24/10/2026: o segundo `runner` foi recusado com código 3, e a sequência `Stop-ScheduledTask` e `Start-ScheduledTask` manteve um único processo. |

### A04: Ausência de notificação quando o servidor já está crítico

| Campo | Valor |
|---|---|
| Categoria / gravidade | L / Média |
| Cenário | CT02, CT03 |
| Descrição | A notificação é gerada na transição de status do **servidor**, e não do pilar. A piora do pilar de backup (aviso ou crítico) não gera notificação quando o servidor já estava crítico por outro motivo. |
| Causa raiz | Decisão de projeto: as notificações seguem as transições de estado do servidor. |
| Impacto | O problema de backup aparece no painel, mas não dispara aviso ativo. Os cenários CT02 e CT03 não demonstraram a notificação. |
| Evidência | `validacao/evidencias/A04/log-acoes.txt` |
| Status | **Aberto (limitação conhecida)**; declarado no artigo e listado como trabalho futuro |

### A05: Reconhecimento antigo reaplicado a alerta novo

| Campo | Valor |
|---|---|
| Categoria / gravidade | S / Média |
| Cenário | CT02 |
| Descrição | Alertas novos aparecem como já reconhecidos quando um alerta do mesmo item foi reconhecido anteriormente. No CT02, o alerta de backup chegou com reconhecimento de 18/07/2026. |
| Causa raiz | O reconhecimento é armazenado pela chave (servidor, pilar, item) e aplicado a qualquer alerta com a mesma chave, sem comparação com a data de início do alerta. Nenhum trecho do código remove o reconhecimento quando o alerta é resolvido. Os testes cobrem o reconhecimento repetido, mas não o reaparecimento do alerta. |
| Impacto | O operador pode interpretar uma ocorrência nova como já tratada. |
| Evidência | `validacao/evidencias/A05/health-ubuntu.json` (alerta de outubro com `acked_at` de julho) |
| Status | **Aberto (limitação conhecida)** |

### A06: Alerta de integridade sem a causa

| Campo | Valor |
|---|---|
| Categoria / gravidade | U / Baixa |
| Cenário | CT03 |
| Descrição | O alerta "Falha de integridade no backup" informa apenas o caminho do arquivo. A causa ("Arquivo corrompido: File is not a zip file") consta no envio do agente, mas não no alerta. |
| Causa raiz | Na central, o detalhe do alerta de `INTEGRITY_FAIL` é montado apenas com o caminho (`api/app/analysis.py`). |
| Impacto | O diagnóstico exige consultar o envio original. |
| Evidência | `validacao/evidencias/A06/passo6-health-ubuntu.json` |
| Status | **Aberto (limitação conhecida)** |

### A07: Falso positivo de `cron` e `sshd` no Ubuntu

| Campo | Valor |
|---|---|
| Categoria / gravidade | S / Baixa |
| Cenário | CT13 |
| Descrição | O padrão de serviços críticos no Linux era `sshd` e `cron`. Na UBUNTU26 (instalação mínima), ambos apareciam como `inactive`, mantendo o servidor em estado crítico. |
| Causa raiz | O `cron` não é instalado em imagens mínimas e não é crítico em todo servidor. Além disso, em Debian e Ubuntu a unit do OpenSSH chama-se `ssh`, e não `sshd`. |
| Impacto | Estado crítico permanente sem falha real. |
| Evidência | `validacao/evidencias/A07/matriz-itens.txt`; `validacao/evidencias/A07/servicos-padrao.txt` (padrão após a correção) |
| Status | **Corrigido na 1.2.0** |
| Correção | O padrão Linux passou a `sshd`, resolvido para `ssh` ou `sshd` conforme a distribuição, e o `cron` foi removido do padrão (`45e3fef`). |
| Verificação | Padrão conferido na central reconstruída em 24/10/2026; testes em `tests/test_agent_operacional_services.py`. Não houve reteste do estado do serviço na VM. |

### A08: Rajada de notificações repetidas

| Campo | Valor |
|---|---|
| Categoria / gravidade | S / Média |
| Cenário | CT05 (histórico de notificações consultado na conferência) |
| Descrição | Em 21/10/2026, entre 00:54Z e 01:56Z, a central gerou uma notificação `unknown` para `crit` a cada envio nos três servidores: ids 1290 a 1298 (DESKTOP, a cada cerca de 5 min) e ids 1300 a 1327 (28 notificações, 22 delas do WINSRV2016-TEST por `W32Time`, a cada cerca de 60 s). |
| Causa raiz | O laço de detecção de offline reavaliava servidores online com métricas vazias, rebaixando o status para `unknown` a cada ciclo. O envio seguinte o devolvia a `crit` e gerava nova notificação. |
| Impacto | Excesso de notificações duplicadas. |
| Evidência | `validacao/evidencias/A08/notificacoes-200.json` |
| Status | **Corrigido antes dos cenários** |
| Correção | Commit `7992efa` (2026-10-20 23:16 -03, 20 minutos após a última notificação da rajada), contido na tag `validacao-cenarios`. |
| Verificação | Não houve repetição nas notificações 1328 a 1376, embora o WINSRV2016-TEST tenha permanecido crítico por mais de um dia com ciclos de 60 s. Testes em `api/tests/test_notifications.py`. A data de criação da imagem da central durante a sessão não foi registrada; que a central executava o código corrigido é inferência a partir desse histórico. |

### A09: Falhas de logon no Linux não coletadas e sem sinalização

| Campo | Valor |
|---|---|
| Categoria / gravidade | S / Alta |
| Cenário | CT11, CT13 |
| Descrição | Doze tentativas SSH inválidas na UBUNTU26 não apareceram em nenhum envio: o pilar de acesso não trazia o item de falhas de logon, e nenhum erro ou aviso indicava a ausência. |
| Causa raiz | O coletor lia apenas `/var/log/auth.log` e `/var/log/secure`, ausentes no Ubuntu 26.04 mínimo (que registra no journald), e retornava vazio sem sinalizar. |
| Impacto | O requisito RF03 não era atendido no Linux, e a falha era silenciosa. |
| Evidência | `validacao/evidencias/A09/CT11.md`; `validacao/evidencias/A09/ssh-tentativas-ubuntu.txt` (tentativas geradas); `validacao/evidencias/A09/acesso-ubuntu-itens.txt`; `validacao/evidencias/A09/ct11-linux-contagem.txt` (reteste) |
| Status | **Corrigido na 1.2.0** |
| Correção | O agente passou a ler o journald quando os arquivos não existem e a emitir um achado explícito de indisponibilidade quando nenhuma fonte é legível (`710e313`). |
| Verificação | CT11 repetido em 24/10/2026: 12 falhas contadas e, após mais 12 tentativas, 24. Testes em `tests/test_agent_acesso.py`. |

### A10: Contagem de falhas de logon do Windows satura em 100

| Campo | Valor |
|---|---|
| Categoria / gravidade | L / Baixa |
| Cenário | CT11, CT13 |
| Descrição | A contagem de eventos 4625 lê no máximo 100 eventos e não considera a idade deles, de modo que satura em 100 e falhas antigas continuam sendo contadas. No CT11, o limiar já estava excedido antes do teste (18 contra 10); o cenário demonstrou a contagem refletida (de 18 para 30), e não a transposição do limiar. |
| Causa raiz | A consulta usa `Get-WinEvent` com `-MaxEvents 100` e sem filtro de tempo. |
| Evidência | `validacao/evidencias/A10/contagem-4625-winsrv.txt`; `validacao/evidencias/A10/transicao-18-30.txt` |
| Status | **Aberto (limitação conhecida)**; declarado no artigo |

### A11: Lacunas de cobertura do Linux em instalação mínima

| Campo | Valor |
|---|---|
| Categoria / gravidade | S / Média |
| Cenário | CT13 |
| Descrição | Na UBUNTU26, o pilar de logs gerou 9 avisos e 1 erro: arquivos de log tradicionais ausentes (`auth.log`, `syslog`, `secure`, `messages`, `audit.log`) e falha do coletor do `auditd`. O pilar de acesso também apresentou a falha de `auditd_service`. |
| Causa raiz | Instalação mínima que registra apenas no journald e não possui `auditd`. O agente tratava a ausência dos arquivos como problema mesmo com o journald ativo. |
| Impacto | Avisos sem falha real correspondente e cobertura menor no Linux do que no Windows. |
| Evidência | `validacao/evidencias/A11/CT13.md`; `validacao/evidencias/A11/matriz-itens.txt` |
| Status | **Corrigido na 1.2.0 (parcial)** |
| Correção | O pilar de logs passou a tratar o journald ativo como fonte válida e a registrar a ausência dos arquivos como informação (`ffcc56c`). A ausência do `auditd` continua sendo reportada, o que é o comportamento correto, pois constitui lacuna de cobertura do servidor monitorado. |
| Verificação | Testes em `tests/test_agent_logs.py`. Não houve reteste desses avisos na VM. O artigo declara a cobertura menor no Linux. |

### A12: Limite de requisições compartilhado por toda a frota

| Campo | Valor |
|---|---|
| Categoria / gravidade | L / Média |
| Cenário | CT12 |
| Descrição | O limite de requisições, previsto por endereço de origem, opera como um contador único para toda a frota. |
| Causa raiz | O limitador usa o endereço remoto da conexão (`get_remote_address`), e todos os clientes chegam à API pelo mesmo proxy. |
| Impacto | Um cliente pode consumir a cota dos demais, e o limite não distingue agentes. |
| Evidência | `validacao/evidencias/A12/CT12.md`; `validacao/evidencias/A12/verificacoes-parte1.txt`; `validacao/evidencias/A12/verificacoes-parte2.txt`; `validacao/evidencias/A12/tls.txt` |
| Status | **Aberto (limitação conhecida)**; declarado no artigo e listado como trabalho futuro (limite por agente) |

### A13: Janela de notificações da API sem paginação retroativa

| Campo | Valor |
|---|---|
| Categoria / gravidade | L / Baixa |
| Cenário | CT05 |
| Descrição | A rota de notificações aceita `limit` de até 200 e `since_id`, mas não permite paginar para trás, e o histórico antigo não pode ser consultado. |
| Impacto | No CT05, a notificação original da limpeza do log de segurança (julho) ficou fora da janela consultável, e o cenário foi classificado como parcial. |
| Evidência | `validacao/evidencias/A13/conferencia.txt` |
| Status | **Aberto (limitação conhecida)** |

### A14: Latência de persistência dependente do estado do host

| Campo | Valor |
|---|---|
| Categoria / gravidade | E / Média |
| Cenário | CT09 |
| Descrição | Das cinco execuções medidas, quatro apresentaram p95 de persistência abaixo de 200 ms (15,2 a 44,2 ms). A execução 1 atingiu 416,2 ms, coincidindo com um checkpoint do PostgreSQL de 21,3 s. Sete execuções exploratórias variaram de cerca de 15 a 878 ms. |
| Causa raiz | **Hipótese, não confirmada:** contenção de E/S de disco no notebook, que hospedava a frota, a central e o teste, com memória superalocada pelas máquinas virtuais. |
| Evidência | `validacao/evidencias/A14/RESUMO.md` (pilha em contêineres); `validacao/evidencias/A14/RESUMO-tabela.txt`; `validacao/evidencias/A14/run-0.json`, `validacao/evidencias/A14/run-1.json`, `validacao/evidencias/A14/run-2.json`, `validacao/evidencias/A14/run-3.json`, `validacao/evidencias/A14/run-4.json`, `validacao/evidencias/A14/run-5.json`; `validacao/evidencias/A14/checkpoints-db-lab.txt`; `validacao/evidencias/A14/RESUMO-repeticoes.md` (execuções exploratórias) |
| Status | **Tratado no CT09** (cenário parcial) |

### A15: Ferramenta de carga do repositório inoperante em implantação Compose

| Campo | Valor |
|---|---|
| Categoria / gravidade | E / Baixa |
| Cenário | CT09 |
| Descrição | O `tools/load_test.py` acessa o banco diretamente e usa a porta 8000, que não são publicados em implantações Compose, e depende do `httpx`, ausente da imagem. A ferramenta que gerou os números do CT09, que envia apenas pela API HTTPS, não estava versionada no repositório. |
| Evidência | `tools/load_test.py` (cabeçalho); `validacao/evidencias/A14/RESUMO.md` (identifica a ferramenta usada no CT09) |
| Status | **Parcial** |
| Tratamento | A ferramenta usada no CT09 foi versionada em `tools/load_test_api.py`. O `tools/load_test.py` mantém a dependência de acesso direto ao banco. |

### A16: Divergências de documentação

| Campo | Valor |
|---|---|
| Categoria / gravidade | E / Baixa |
| Cenário | CT10, CT13 |
| Descrição | A documentação indicava 111 testes da API, e a execução do CT10 contabilizou 113. Também descrevia o agente do Windows como "serviço", embora o instalador registre uma Tarefa Agendada executada com a conta SYSTEM, pois o processo do agente não implementa o protocolo de serviços do Windows. |
| Evidência | `validacao/evidencias/A16/api-pytest.txt` (113 testes); `validacao/evidencias/A16/CT13.md` |
| Status | **Aberto**; o artigo já descreve a Tarefa Agendada no Quadro 1 |

### A17: Falhas do ambiente de teste

| Campo | Valor |
|---|---|
| Categoria / gravidade | E / Baixa |
| Cenário | preparo e reteste da 1.2.0 |
| Descrição | (a) O certificado do Caddy local tem validade de 12 h, e a central permaneceu parada com o host suspenso por cerca de 20 h. O `curl` do Windows falhou com `CRYPT_E_NO_REVOCATION_CHECK` até o uso de `--ssl-no-revoke`. (b) No reteste, o relógio da UBUNTU26 estava cerca de 14 h atrasado, o que impediu o handshake TLS do agente: o servidor ficou sem contato e 65 envios permaneceram na fila local, sendo enviados após a sincronização por NTP. |
| Observação | Não constitui defeito do Argus. O item (b) evidencia a fila local retendo os envios durante a falha de conexão. |
| Evidência | `validacao/evidencias/A17/certificado.txt`; `validacao/evidencias/A17/log-acoes.txt` |
| Status | **Não aplicável (ambiente)** |

### A18: Nome de host divergente gera aviso em todo envio

| Campo | Valor |
|---|---|
| Categoria / gravidade | U / Baixa |
| Cenário | observado no log da API durante a validação, sem cenário específico |
| Descrição | O WINSRV2016-TEST envia o nome de host `WIN-2D2Q7RM5CP0`, diferente do nome em que foi registrado. A API registra um aviso a cada envio. |
| Causa raiz | A divergência não bloqueia a ingestão, pois a identidade do agente é o token, mas o aviso é emitido em todo payload. |
| Evidência | `validacao/evidencias/A18/diagnostico.txt` |
| Status | **Aberto (limitação conhecida)** |

## 4. Observações (fora da contagem)

| ID | Observação |
|---|---|
| O1 | UBUNTU26 e WINSRV2016-TEST ficaram offline após o encerramento porque as máquinas virtuais foram desligadas. Não é defeito; os agentes retomaram o envio no boot. |
| O2 | Restaurar a data de modificação de um backup gera aviso de estagnação: mesmo caminho, data alterada e SHA-256 idêntico. É efeito esperado da definição de estagnação do contrato, relevante para quem ajusta datas de backups. |

## 5. Fora do escopo: correções da versão 1.3.0

Uma revisão de código posterior aos cenários identificou quatro defeitos não cobertos por eles, corrigidos na versão 1.3.0 do agente com testes automatizados: tempo de atividade não coletado no Windows; nome de serviço configurado na central inserido em script PowerShell, o que permitia injeção de comandos; arquivos `.tar.gz` truncados classificados como aviso e não como falha; e caminhos com `..` que permitiam ler arquivos fora do diretório do painel. Esses itens não entram na contagem, pois os cenários não os revelaram, e foram verificados apenas por testes automatizados.

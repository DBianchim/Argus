# CT09: repetições do teste de carga (3 execuções + a execução original)

Mesmos parâmetros em todas: `load_test.py run --count 20 --duration 60 --interval 10 --api-url http://localhost:8000`, dentro do contêiner `api` (sem Caddy/TLS). Critério fixado antes: p95 de persistência na central < 200 ms e nenhuma falha atribuível à central.

| | Execução 0 (21:30 -03) | Rep. 1 (22:45) | Rep. 2 (22:47) | Rep. 3 (22:49) | Mediana das 3 reps | Máximo das 3 reps |
|---|---|---|---|---|---|---|
| Requisições enviadas | 476 | 248 | 472 | 400 | 400 | 472 |
| HTTP 200 | 476 | 170 | 472 | 400 | 400 | 472 |
| Falhas de rede (ReadTimeout, 15 s) | 0 | **78** | 0 | 0 | 0 | 78 |
| Vazão no cliente (req/s) | 6,9 | 1,4 | 6,8 | 6,3 | 6,3 | 6,8 |
| Cliente p50 (ms) | 22,2 | 21,2 | 30,6 | 119,3 | 30,6 | 119,3 |
| Cliente p95 (ms) | 38,2 | 368,1 | 284,7 | 2119,8 | **368,1** | **2119,8** |
| Cliente máx (ms) | 498,3 | 877,0 | 2148,6 | 4093,5 | 2148,6 | 4093,5 |
| Central: persistência p50 (ms) | 8,53 | 8,69 | 9,92 | 18,47 | 9,92 | 18,47 |
| Central: persistência p95 (ms) | 15,9 | 88,67 | 316,81 | 878,78 | **316,81** | **878,78** |
| Central: máx na janela (ms) | 5853,3 | 55128,58 | 55128,58 | 55128,58 | — | — |
| Critério p95 < 200 ms (central) | **atende** | atende | **não atende** | **não atende** | não atende | |
| Sem falhas | atende | **não atende** | atende (no cliente) | atende (no cliente) | | |

Incluindo a execução 0 (4 execuções): mediana do p95 da central = 202,7 ms; mediana do p95 do cliente = 326,4 ms. **Só a execução 0 atende os dois critérios.**

## Ressalvas de leitura
- O `stats` da central usa a janela dos **últimos 1000 eventos**, então o p95 da central de cada repetição mistura eventos da repetição anterior (e o máximo de 55 s da rep. 1 permanece na janela nas reps. 2 e 3). O p95 do cliente é só da respectiva execução.
- Rep. 1: as 78 falhas foram `ReadTimeout` (a central não respondeu em 15 s) enquanto a central mostrava 0 falhas na leitura anterior à limpeza. A limpeza do script (apagar os servidores simulados) ocorreu com requisições ainda em andamento e gerou, às 01:47:26Z, erros na API (`InvalidRequestError` ao persistir, `StaleDataError`, uma exceção ASGI) e **2 persistências falhas** no contador (visíveis a partir da rep. 2: `total_failed=2`).
- Rep. 2 e 3: nenhuma falha vista pelo cliente (todos HTTP 200), mas com latências muito acima do critério.

## Causa provável (não confirmada)
Contenção de recursos do host durante as repetições, não uma mudança no código:
- log do PostgreSQL: `checkpoint complete: wrote 453 buffers (2.8%) … write=78.516 s` às 01:49:52Z (às 01:43:36Z, um checkpoint de 20 buffers levou 2,0 s): 453 buffers em 78 s indica **escrita em disco muito lenta/bloqueada**;
- host às 22:51 -03: **1,3 GB livres de 11,9 GB**, CPU a 37%, navegador e IDE abertos, disco C: com 11,7 GB livres de 222,6 GB (95% cheio); Docker com 6,17 GB;
- na rep. 1, um evento de persistência de 55,1 s (sem checkpoint no período).

O efeito do disco não foi separado do da memória. Condições a controlar em repetições futuras: fechar aplicações, verificar memória e disco livres, aguardar o banco ficar ocioso entre execuções, não limpar os servidores simulados enquanto há requisições em voo, e reportar todas as execuções.

## Estado após as repetições
`/app/tools` e `/tmp/lt` removidos do contêiner; 0 servidores `loadtest-*` no banco; 3 servidores reais registrados.

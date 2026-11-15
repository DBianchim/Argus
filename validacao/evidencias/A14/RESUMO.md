# CT09 em ambiente controlado por contêineres (pilha `argus-lab`)

**Ambiente:** pilha Docker isolada (composição própria do laboratório), com PostgreSQL 18 (1 CPU, 1 GB), API (2 CPU, 1 GB), Caddy (0,5 CPU) e um contêiner cliente (1 CPU, 512 MB) na mesma rede, gerando a carga **por HTTPS passando pelo Caddy** (caminho real do agente) com `load_test_api.py`. Reaproveita as imagens `argus-api`, `postgres:18` e `caddy:2-alpine`; não toca na central real. **Executado no mesmo notebook** (i5-8250U, 11,9 GB, Docker com 8 CPUs e 6,17 GB) com as VMs e a central real ligadas; RAM livre do host entre 1,6 e 1,9 GB. **Não é isolamento de hardware.**

**Protocolo:** 1 aquecimento + 5 execuções medidas, 20 servidores simulados, 4 pilares por ciclo, intervalo de 10 s, 60 s; `restart` da API antes de cada execução (zera a janela de 1000 eventos do `/ingest/stats`, então o p95 da central é de cada execução); 120 s entre execuções. 2026-10-23 de 20:xx -03. Critério: p95 de persistência na central < 200 ms e nenhuma falha atribuível à central, **em todas** as medidas.

| Exec. | Requisições / HTTP 200 | Falhas de rede | Vazão (req/s) | Cliente p50 / p95 / p99 / máx (ms) | Central p50 / p95 / máx (ms) | Falhas na central | Checkpoint do PostgreSQL |
|---|---|---|---|---|---|---|---|
| aquecimento | 480 / 480 | 0 | 6,89 | 26,0 / 65,1 / 355,5 / 419,9 | 9,3 / 34,7 / 406,8 | 0 | nenhum no período |
| 1 | 460 / 460 | 0 | 6,60 | 29,2 / **436,8** / 866,1 / 1312,7 | 9,9 / **416,2** / 1290,6 | 0 | **205 buffers em 21,3 s** |
| 2 | 472 / 472 | 0 | 6,73 | 29,2 / 113,3 / 208,9 / 406,8 | 9,7 / 44,2 / 89,4 | 0 | nenhum no período |
| 3 | 476 / 476 | 0 | 6,80 | 22,5 / 45,7 / 67,4 / 82,5 | 7,8 / 15,2 / 55,9 | 0 | nenhum no período |
| 4 | 476 / 476 | 0 | 6,77 | 31,0 / 104,0 / 202,3 / 364,4 | 10,0 / 36,3 / 145,7 | 0 | nenhum no período |
| 5 | 476 / 476 | 0 | 6,87 | 26,2 / 54,6 / 75,3 / 131,1 | 8,6 / 18,8 / 61,3 | 0 | 84 buffers em 8,5 s |

**Estatística das 5 execuções medidas:**
- p95 da **central**: mediana **36,3 ms**, máximo **416,2 ms**, mínimo 15,2 ms.
- p95 do **cliente** (inclui TLS e rede do contêiner): mediana **104,0 ms**, máximo **436,8 ms**.
- Vazão: mediana 6,77 req/s. Falhas de rede: 0. Falhas na central: 0. Servidores simulados removidos: 20/20 em todas.

**Veredito pelo protocolo:** o critério "p95 < 200 ms em todas as medidas" foi **atendido em 4 de 5**. A execução 1 (p95 da central 416,2 ms) coincide com um checkpoint do PostgreSQL de **21,3 s** (escrita lenta em disco), o mesmo sintoma de contenção de E/S visto nas execuções anteriores. **Não há falhas de requisição em nenhuma execução**; o desvio é de latência. Pelo critério estrito do protocolo o CT09 **não fecha como aprovado**; a mediana e as 4 execuções limpas mostram p95 de 15 a 44 ms na central.

**Limites:** mesmo notebook, memória do host baixa (superalocada com as VMs), carga sintética de um único cliente, uma pilha de laboratório única. Para um resultado definitivo, repetir em VMs/hardware dedicados.

**Limpeza:** `docker compose down -v` removeu contêineres, volume e rede do laboratório; a central real não foi alterada (continua `api`, `backup`, `caddy`, `db` em execução). Arquivos: `run-0.json` a `run-5.json`, `checkpoints-db-lab.txt` e `RESUMO-tabela.txt`.

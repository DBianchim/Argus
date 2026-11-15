# Reteste da instancia unica no Windows (WINSRV2016-TEST), agente 1.2.0
Pre-requisito: central reconstruida (serve o agente 1.2.0). Procedimento executado no PowerShell, com privilegios de administrador, na VM.

## Procedimento
1. Atualizar pelo instalador (encerra o runner antigo, registra a tarefa, inicia) e confirmar 1 processo, versao 1.2.0 e agent.lock.
2. Tentar iniciar um segundo runner manualmente: esperado, mensagem "Ja existe outro agente em execucao neste host" e codigo de saida 3.
3. Start-ScheduledTask com o agente rodando: esperado, continuar com 1 processo (mesmo PID e CreationDate) e a mensagem no log.
4. Pela API: intervalos de 60 s sem o padrao alternado 17/43 s.
Criterio: nunca mais de um runner.py ativo; a segunda instancia encerra com codigo 3 sem consumir a fila.

## Resultado (2026-10-24, WINSRV2016-TEST; horarios do relogio da VM em -02:00, UTC = +2 h)
1. Atualizacao pelo install.ps1: antes, 1 runner (PID 1568, de 22/10 22:25:42, agente 1.0.0); depois, 1 runner (PID 3872, criado 24/10 14:46:59 = 16:46:59Z). O instalador encerrou o processo antigo. API: payload 1.0.0 as 16:46:31Z, depois 1.2.0 as 16:47:03Z e 16:48:04Z (61 s: um agente so).
   (O comando de verificacao do agent.lock falhou: a variavel $cfg foi sobrescrita pelo instalador executado via iex, entao o Get-Item nao funcionou; a existencia da trava e provada pelo erro do passo 2, que cita agent.lock.)
2. Segundo runner manual com o agente rodando: log "Ja existe outro agente em execucao neste host (pid=3872 | trava=C:\ProgramData\Argus\agent-monitor\agent.lock)" e codigo de saida 3 (16:47:41Z). APROVADO.
3. Start-ScheduledTask com a tarefa ja Running: continuou 1 processo (PID 3872, mesma CreationDate). Ressalva: com a tarefa Running o Agendador nao inicia nova instancia, entao este passo NAO exercita a trava; a falha original (Stop-ScheduledTask + Start-ScheduledTask) esta no passo 4 abaixo.
4. Reproducao da falha original (Stop-ScheduledTask seguido de Start-ScheduledTask), 14:54:44 (VM, -02:00) = 16:54:44Z: estado da tarefa apos o Stop = Ready; apos o Start e 25 s, **1 processo runner.py** (PID 3872, CreationDate 24/10 14:46:59, o mesmo de antes); o log segue com ciclos normais (#9 as 16:55:04Z, proximo em 53,2 s). APROVADO pelo criterio "nunca mais de um runner.py ativo". A mensagem de instancia duplicada desse Start nao aparece no trecho final do log registrado (as ultimas 8 linhas); a mensagem ja foi comprovada no passo 2. Conferencia opcional: Select-String 'Ja existe outro agente' no log.
Veredito: instancia unica verificada na VM Windows real com o agente 1.2.0 (passos 1, 2 e 4).

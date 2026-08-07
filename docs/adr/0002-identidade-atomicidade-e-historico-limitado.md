# ADR 0002: identidade estável, atomicidade e histórico limitado

- Estado: aceita
- Data: 2026-07-18

## Contexto

Nome e assento são atributos mutáveis: um jogador pode trocar de cadeira, sair e outro
usar o mesmo nome. Além disso, uma ação pode alterar o domínio antes de o log durável ser
gravado. Cache idempotente com simples descarte dos itens antigos permite que um retry
tardio repita o efeito. Leituras sem limite e trabalho síncrono no event loop ampliam
latência e consumo de memória.

## Decisão

1. Cada participante recebe `player_id` hexadecimal de 32 caracteres, opaco e estável.
   Placar, estatísticas e séries de fichas usam essa identidade; nome e assento servem
   somente para apresentação/contexto. Logs legados sem o campo continuam legíveis, mas
   não recebem retroativamente uma identidade inventada.
2. Uma mutação de mesa é uma unidade atômica: estado do jogo, estatísticas derivadas,
   versão, idempotência e append durável devem concordar. Falha de persistência restaura
   o estado anterior e não publica snapshot parcial.
3. Chaves idempotentes ativas têm armazenamento limitado. Ao expirar, deixam um
   tombstone limitado; reutilização tardia é rejeitada com conflito e jamais repete o
   comando silenciosamente.
4. `If-Match`, corpos JSON e mensagens WebSocket são validados com limites de bytes,
   profundidade e faixa antes da execução do domínio.
5. Catálogo, replay e séries temporais são paginados ou limitados. Toda página declara
   total e `next_offset`; toda série truncada declara contagem total, mão inicial e o
   indicador de truncamento. O log durável não é apagado por causa da janela da UI.
6. O WebSocket publica snapshots monotônicos a todos os pares da mesa. Trabalho síncrono
   potencialmente caro sai do event loop; clientes mortos são isolados e removidos.

## Consequências

- Contratos de API e frontend carregam `player_id` e metadados de página/janela.
- Uma falha de transporte pode repetir o comando uma vez com o mesmo identificador;
  conflito de versão provoca ressincronização explícita antes de nova intenção do usuário.
- O limite de histórico protege navegador e servidor sem fingir que a auditoria completa
  foi transferida em uma única resposta.

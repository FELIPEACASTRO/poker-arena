# ADR-0006: promoção visual v3 com independência por sessão

## Status

Aceita em 2026-08-07. Supera a ADR-0005 para novos receipts.

## Contexto

Métricas por frame tratam capturas correlacionadas da mesma sessão como se fossem ensaios
independentes. Um detector de 52 classes também não observa assentos/botão e, portanto, não
pode comprovar o estado estratégico completo prometido pelo produto.

## Decisão

O perfil `poker-arena-external-vision-v3-2026-08-07`:

- aceita somente o contrato ONNX de 54 classes (52 cartas, assento e botão);
- exige manifesto temporal por grupos, protocolo pré-registrado anterior à coleta e ao menos
  99 sessões (95 sessões inteiramente exatas são o evento crítico do desenho de poder);
- rejeita duplicatas exatas e colisões idênticas do hash perceptual entre splits e dentro
  do holdout; frames distintos correlacionados são tratados pelo limite por sessão, sem
  confundir a repetição legítima do layout de um cliente com vazamento;
- exige cobertura de pré-flop/flop/turn/river, mesas de 2 a 9 jogadores e todos os rótulos de
  posição compatíveis, com ao menos 40 itens em cada subgrupo observado;
- aplica Wilson 95% ao estado exato global, a cada subgrupo e a sessões inteiramente exatas;
- liga o receipt ao modelo, lock, configuração e a todo `poker_arena/**/*.py`, evitando
  omissão silenciosa de dependência transitiva;
- exige igualdade do ambiente instalado medido (CPU reportada e dependências de inferência)
  e reavaliação em no máximo 30 dias;
- autoriza decisão somente quando o contexto manual completo de apostas também foi enviado.

Qualquer ausência, ambiguidade ou receipt v2 produz `F2_PROMOTION=NOT_PROMOTED`. F1
sintético, VLM, uma tela real e detector de 52 classes permanecem diagnósticos e não
autorizam decisão. Esse estado não altera `release_decision=GO` da demonstração local.

## Consequências

O conjunto mínimo efetivo pode exceder 200 frames por causa da cobertura cruzada; isso é
intencional. A demo local continua disponível por abstenção, sem transformar evidência
sintética em validade externa.

# Requisitos não funcionais verificáveis

Status: normativo para esta distribuição. Metas sem medição são tratadas como não
comprovadas, nunca como aprovadas.

## Segurança e privacidade

- A API aceita apenas hosts/origens locais autorizados, impõe limites de corpo e imagem,
  normaliza bombas de descompressão para HTTP 413 e nunca registra o conteúdo capturado.
- Captura visual só prossegue quando `displaySurface` prova `window`; ausência, `unknown`,
  `browser` e `monitor` falham fechados.
- VLM remoto permanece desligado por padrão e exige token, opt-in da requisição e
  consentimento efêmero revogável. F1 e VLM nunca autorizam decisão.
- Segredos não podem existir na árvore distribuída. O scanner cobre a raiz canônica;
  credenciais anteriormente expostas devem ser revogadas externamente.

## Confiabilidade científica da visão

- Somente F2 ONNX com artefato, manifesto e recibo de promoção imutavelmente ligados por
  SHA-256 pode autorizar uma decisão.
- O holdout é externo, temporal e por grupos, sem duplicatas perceptuais entre splits,
  com no mínimo 200 observações, 142 previsões aceitas, 40 itens em cada subgrupo declarado,
  três fontes/clientes/resoluções, dois temas/decks e vinte sessões.
- Limites Wilson 95%: estado exato global >= 0,90; estado exato por subgrupo >= 0,80;
  falso aceite <= 0,05. ECE e Brier <= 0,05; latência P95 <= 1.000 ms.
- O desenho tem alfa <= 0,05 e poder >= 0,80 para alternativas pré-declaradas. O cálculo
  reproduzível está em `backend/scripts/power_analysis.py`.
- O recibo registra SO, arquitetura, CPU lógica, versões de Python/Pillow/ONNX Runtime,
  provider, ciclo da sessão, escopo cronometrado e política de warm-up.

## Desempenho e disponibilidade

- O endpoint de saúde deve responder sem carregar modelos pesados. Readiness degrada de
  modo explícito quando fronteiras remotas ou artefatos obrigatórios estão inválidos.
- Inferência OCR sobre o singleton é serializada para impedir corridas internas. Uploads,
  JSON, replay, histórico e paginação possuem limites definidos no código e cobertos por testes.
- Metas de latência da visão valem somente para o ambiente descrito no recibo; extrapolações
  para outra máquina ou provider são hipóteses, não evidência.

## Manutenibilidade, rastreabilidade e liberação

- Há uma única solução canônica (`CODEX`), uma única raiz Git e nenhuma árvore legada
  executável dentro da distribuição.
- Ruff, mypy, testes backend, cobertura, testes frontend, lint, build, E2E, auditorias de
  dependências, scanner de segredos e contrato de distribuição são gates de liberação.
- Uma liberação exige árvore Git limpa e `HEAD` imutável. Falha ou ausência de qualquer
  evidência mantém o estado `NO-GO`.

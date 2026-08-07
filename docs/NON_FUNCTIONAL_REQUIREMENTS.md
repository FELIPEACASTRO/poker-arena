# Requisitos não funcionais verificáveis

Status: normativo para esta distribuição. Metas sem medição são tratadas como não
comprovadas, nunca como aprovadas.

## Segurança e privacidade

- A API aceita apenas hosts/origens locais autorizados, impõe limites de corpo e imagem,
  normaliza bombas de descompressão para HTTP 413 e nunca registra o conteúdo capturado.
- Captura visual só prossegue quando `displaySurface` prova `window`; ausência, `unknown`,
  `browser` e `monitor` falham fechados.
- VLM remoto permanece desligado por padrão e exige token, opt-in da requisição e
  consentimento efêmero revogável. A máscara é uma fronteira de confiança do operador:
  mínimos de área evitam configuração nula e um hash das coordenadas registra a política,
  mas isso não prova que toda PII foi coberta. F1 e VLM nunca autorizam decisão.
- Materiais de credencial conhecidos não podem integrar a árvore distribuída. O scanner
  heurístico cobre a raiz canônica e falha fechado em arquivos de texto não examináveis,
  mas zero achados não prova a inexistência de todo segredo possível. Credenciais
  anteriormente expostas precisam ser revogadas externamente.

## Confiabilidade científica da visão

- Somente F2 ONNX com artefato, manifesto e recibo de promoção imutavelmente ligados por
  SHA-256 pode autorizar uma decisão. O verificador recompõe limites, contagens, partições
  de subgrupo e intervalos Wilson; SHA-256 prova integridade, não autoria.
- O holdout é externo, temporal e por grupos: a política do manifesto ordena os splits,
  proíbe fronteira temporal empatada e o protocolo precisa preceder cada coleta. Não há
  duplicatas exatas nem colisões idênticas do hash perceptual entre splits ou dentro de
  `external-test`; frames distintos da mesma sessão são agrupados estatisticamente.
- O perfil exige detector de 54 classes e cobertura de todas as ruas, mesas 2–9 e posições
  compatíveis. São necessárias no mínimo 200 observações, 142 previsões aceitas,
  40 itens em cada subgrupo declarado,
  três fontes/clientes/resoluções, dois temas/decks e noventa e nove sessões.
- Limites Wilson 95%: estado exato global >= 0,90; estado exato por subgrupo >= 0,80;
  sessão inteiramente exata >= 0,90; falso aceite <= 0,05. ECE e Brier <= 0,05;
  latência P95 <= 1.000 ms.
- O desenho tem alfa <= 0,05 e poder >= 0,80 para alternativas pré-declaradas. O cálculo
  reproduzível está em `backend/scripts/power_analysis.py`.
- O recibo registra SO, arquitetura, CPU lógica, versões de Python/Pillow/ONNX Runtime,
  provider, ciclo da sessão, escopo cronometrado e política de warm-up.
- Fronteira de confiança: o pacote local não assina receipts nem atesta a identidade do
  operador. Um autor com escrita no manifesto/holdout pode fabricar um novo conjunto
  internamente coerente; revisão independente dos dados brutos e custódia externa são
  obrigatórias antes de qualquer uso fora da banca. Receipts não expiram automaticamente,
  embora mudança no pipeline/lock os invalide.

## Desempenho e disponibilidade

- O endpoint de saúde deve responder sem carregar modelos pesados. Readiness degrada de
  modo explícito quando fronteiras remotas ou artefatos obrigatórios estão inválidos.
- Inferência OCR sobre o singleton é serializada para impedir corridas internas. Uploads,
  JSON, replay, histórico e paginação possuem limites definidos no código e cobertos por testes.
- Metas de latência da visão valem somente para o ambiente descrito no recibo; extrapolações
  para outra máquina ou provider são hipóteses, não evidência.
- A revisão local pós-mão do copiloto tem meta P95 <= 2.500 ms nos cinco cenários
  congelados (equity exata/amostrada, HU/6-max/9-max). O recibo separa latência de
  qualidade estratégica, liga medição aos hashes de implementação/cenários/lock e
  passar tempo não prova que a recomendação seja ótima.

## Manutenibilidade, rastreabilidade e liberação

- Há uma única solução canônica (`CODEX`), uma única raiz Git e nenhuma árvore legada
  executável dentro da distribuição.
- Ruff, mypy, testes backend, cobertura, testes frontend, lint, build, E2E, auditorias de
  dependências, scanner de segredos e contrato de distribuição são gates de liberação.
- Uma liberação exige árvore Git limpa e `HEAD` imutável. Falha ou ausência de qualquer
  evidência obrigatória mantém a decisão `BLOCKED`; somente o preflight integral emite `GO`.
- Para `LOCAL_MASTER_DEFENSE`, o sucesso exige `release_decision=GO`; capacidades declaradas
  fora do escopo são `N/A` e não alteram a decisão da release.

# Expert v2 — validação científica do candidato uniforme

Data da evidência: 2026-08-08/09
Run vigente: `poker-expert-v2-20260808t234837z-289f86e1`
Decisão: **CANDIDATE-ONLY; PROIBIDO PROMOVER, APROVAR OU EXPOR NO PERFIL EXPERT**

## Resumo executivo

O run vigente é um controle uniforme rastreável, não um Expert comprovado. Ele demonstra que o pipeline corrigido consegue treinar, calibrar e exportar um modelo ONNX determinístico, mas não demonstra estratégia GTO, lucro, baixa explorabilidade, força profissional ou generalização para mesas e stacks fora da cobertura observada.

| Evidência | Resultado |
|---|---:|
| Melhor seed / época | `1701` / `24` |
| Acurácia na validação interna | 85,4615% |
| NLL na validação interna | 0,373840 |
| Acurácia no teste público de desenvolvimento | 83,2815% |
| NLL no teste público de desenvolvimento | 0,411786 |
| Top-3 não trivial | 99,8118% |
| Exemplos em que top-3 é tautológico | 36,7607% |
| Acurácia pré-flop | 73,8693% |
| Acurácia no big blind | 57,1150% |
| Ações sem qualquer rótulo de treino | índices `3` e `8` |
| Erro máximo PyTorch → ONNX | `6,67572e-6` |

Uma revalidação independente do ONNX nas 10.922 linhas elegíveis, aplicando a mesma máscara legal do runtime, encontrou zero divergência da ação modal e erro absoluto máximo de probabilidade de `8,76e-6`.

Não se deve converter o top-3 em claim de “ACC próxima de 100%”. Em 36,76% do teste existem três ou menos ações legais, então top-3 é automaticamente correto nesses exemplos. A métrica primária continua sendo top-1/NLL, acompanhada de calibração, cobertura e desempenho por estrato.

## Separação contra contaminação

- treino, validação, calibração-fit, calibração-check, teste público e holdout selado usam máscaras distintas;
- redaction e partição usam o mesmo `stable_split_id` semântico, independente do tensor do encoder;
- o teste público foi carregado sem labels antes de seleção de seed/modelo/calibração;
- seus labels só foram carregados depois da seleção, para diagnóstico de desenvolvimento;
- 27.875 exemplos ficaram no holdout selado e nenhum label foi lido ou pontuado;
- 3.512 exemplos sobrepostos ao teste público foram excluídos de todas as partições;
- o teste público já influenciou iterações anteriores e, portanto, não é evidência promocional independente;
- consultar calibração-check para mudar o modelo consumiria esse check; ele não pode ser reutilizado como confirmação independente da mesma hipótese.

Scan integral do snapshot: 563.200 linhas de treino e 11.000 inputs de teste, zero falha de parse, features finitas em `[0,1]`, 510.773 grupos de feature, 510.773 identidades semânticas e zero grupo associado a mais de uma identidade de partição.

## Pesos, hiperparâmetros e calibração

O controle usou pesos uniformes `[1, 1, 1, 1, 1, 1, 1, 1, 1, 1]`. Isso evita que 122 exemplos da classe 7 ou classes ausentes recebam influência artificial de 5×, problema observado na hipótese antiga `inverse_sqrt_cap5`. Não significa que o desbalanceamento esteja resolvido; significa apenas que o controle não o mascara.

### A/B pré-registrado de pesos

O run `poker-expert-v2-20260809t000859z-c7537c65` alterou exclusivamente o perfil de pesos para `inverse_sqrt_cap5`, preservando source binding, dados, splits, seeds, arquitetura e demais hiperparâmetros. A decisão abaixo usa somente a validação interna:

| Métrica dos três seeds | Uniforme | Inverse-sqrt cap 5 |
|---|---:|---:|
| NLL médio | **0,375395** | 0,403080 |
| Acurácia média | **85,1902%** | 83,7089% |
| Melhor NLL | **0,373840** | 0,400625 |

Veredito: **rejeitar `inverse_sqrt_cap5` e manter o uniforme como baseline**. A ponderação aumentou recall de algumas classes raras, mas degradou de forma material o NLL e a acurácia globais. O teste público produziu a mesma direção, porém não foi usado para decidir o A/B. O holdout selado permaneceu intocado.

Configuração do run:

- AdamW, `lr=2e-3`, weight decay `1e-4` apenas em matrizes;
- bias e parâmetros de normalização com decay zero;
- batch 8.192, bfloat16, gradient clip 5,0;
- três seeds; checkpoint selecionado exclusivamente pelo menor NLL interno;
- máximo 24 épocas, mínimo 8, patience 4 e delta material `1e-4`;
- 4 de 3.816 passos foram clipados; portanto o threshold não dominou o treino;
- utilização GPU média por seed entre 78,46% e 82,71%; pico de memória ~3,6 GiB.

Nenhum seed acionou early stopping. O seed selecionado obteve seu menor NLL exatamente na época 24; isso deixa o teto de épocas como possível limitação e impede afirmar convergência. Uma extensão futura precisa ser pré-registrada e avaliada em desenvolvimento sem consultar o holdout selado.

A temperatura escalar ajustada foi 1,22739. No calibration-check independente dentro do desenvolvimento:

| Métrica | Antes | Depois |
|---|---:|---:|
| NLL | 0,381914 | 0,371967 |
| ECE adaptativo | 0,029277 | 0,006241 |
| Brier multiclasses | 0,218616 | 0,216424 |

A calibração melhorou os três diagnósticos no check, sem alterar a ação modal. Isso é evidência de calibração interna, não de força estratégica.

## Gaps de cobertura e qualidade

1. Os índices 3 (`raise_033_pot`) e 8 (`raise_200_pot`) têm suporte zero. Eles não podem ser considerados aprendidos.
2. Classes raras continuam frágeis no teste público: ação 4 tem 14 exemplos e 42,86% de recall; ação 7 tem 6 exemplos e 33,33% de recall.
3. Pré-flop (73,87%) e big blind (57,12%) são os maiores gaps visíveis.
4. O pós-flop público é essencialmente heads-up; isso não prova mesas 6-max/9-max pós-flop.
5. A acurácia mede imitação de um label abstraído. Não mede EV, bb/100, exploitability, robustez adversarial ou adaptação a oponentes.
6. O gate de mapping exclui sizings com erro relativo acima de 10%; todas as métricas são condicionadas a essa cobertura.
7. Há conflitos residuais de label em estados com features idênticas; o teto empírico top-1 por feature é ~99,93%, não 100% literal.
8. O melhor de três seeds é uma seleção otimista; todos os seeds devem continuar reportados.

## Gate de suporte das ações

O contrato ONNX continua com dez logits para preservar comparabilidade e permitir futura expansão, mas o runtime agora é fail-closed quanto ao suporte de treino. Todo manifesto Expert v2 precisa declarar `supported_action_indices` como subconjunto ordenado, único e não vazio. Para este candidato, o único conjunto defensável é `[0, 1, 2, 4, 5, 6, 7, 9]`; as ações 3 e 8 permanecem desabilitadas.

A máscara efetiva é a interseção entre legalidade do jogo e suporte declarado. Uma ação 3 ou 8 não modal recebe probabilidade exatamente zero. Se uma ação sem suporte for a modal bruta entre as ações legais, a inferência é recusada como `unsupported_action_modal`: a avaliação científica aborta, enquanto a demo local usa fallback determinístico conservador e registra a recusa. Isso evita transformar silenciosamente a segunda maior probabilidade em recomendação aparentemente válida.

O gate não prova força estratégica. Ele apenas impede que classes sem um único rótulo sejam apresentadas como conhecimento aprendido. As ações 3 e 8 só poderão ser habilitadas após novos labels solver, retraining, calibração e avaliação independente vinculados por hashes.

O candidato uniforme possui agora um `MANIFEST.json` próprio em seu bundle. O manifesto permanece no estado `candidate`, aponta para métricas e trace de treino por SHA-256 e só é aceito quando as contagens `optimization_training_class_counts` do trace produzem exatamente o mesmo conjunto de suporte. As métricas também precisam declarar o SHA-256 do ONNX e o mesmo `source_binding` do trace. Um manifesto que tenta habilitar uma classe com contagem zero é rejeitado como `expert_action_support_mismatch`.

## Proveniência imutável do candidato vigente

| Artefato | SHA-256 |
|---|---|
| ONNX | `37535bca9854aa1546d93bba2ae791f0091e6c575cb4d96f1ee4d79e9a9620bf` |
| Checkpoint PyTorch | `e0ecca5141320a83a5e0adf0e37143bcbdc27d1c31d599e9496256b38bbbe96c` |
| Trace de treino | `ab7c76d7cd10d14ac3836fc799b5311e367f098c6c9dc4be21dc82193f24d392` |
| Trace de inferência | `2a85bec71e05b579780ce1c1997283ec3af3c5ac0fcbead085117d4469aa1308` |
| Métricas | `0879127b0af546c28079114e373e6c1da1a918b2a0e2d1136c73a3792b17168e` |
| Source binding | `33d20f659e3bbdb19559ab90891e8b15a2b547933bc24dd76e5633f4e100a718` |

O receipt de lifecycle está em `docs/research/evidence/modal_runs/poker-expert-v2-20260808t234837z-289f86e1.json`.

## Modal e FinOps

A L4 foi adequada ao controle: pico de VRAM ~3,6 GiB e throughput médio de 650–672 mil exemplos/s durante as épocas. Uma GPU maior não corrige cobertura, labels ou qualidade estratégica.

O gargalo foi preparação: 336,50 s de 415,40 s (aproximadamente 81%). A próxima execução deve separar preprocessing CPU-bound e treino GPU-bound, com artefato de features hash-bound, validação do source binding e lifecycle próprio. Isso reduz custo sem alterar a hipótese.

O run custou US$ 0,13317952: L4 US$ 0,09333334, CPU US$ 0,02485111 e memória US$ 0,01499507. O inventário final confirmou os apps do run parados, zero tarefas e zero containers no ambiente `poker-arena`.

Referências oficiais: [preços](https://modal.com/pricing), [GPU](https://modal.com/docs/guide/gpu), [métricas GPU](https://modal.com/docs/guide/gpu-metrics), [Volumes](https://modal.com/docs/guide/volumes) e [profiling](https://modal.com/docs/examples/torch_profiling).

## Gates obrigatórios antes de qualquer promoção

- dataset/solver independente com todas as dez ações e cobertura por posição, street, stack e tamanho de mesa;
- política e labels ligados a EV ou estratégia solver, não apenas a uma ação observada;
- avaliação cross-play pré-registrada contra beginner/intermediate/advanced, com pares duplicados, rotação balanceada, intervalos simultâneos e correção de multiplicidade;
- validação externa ou holdout verdadeiramente longitudinal ainda não consultado;
- replay bruto ou trajetória determinística que permita recomputar cada resultado do receipt;
- fail-closed para suporte insuficiente, inputs fora de distribuição, NaN/Inf, aliases e divergência de contrato;
- parity real entre treinamento, ONNX e runtime de deploy;
- nenhum resultado de desenvolvimento pode ser rebatizado como evidência de promoção.

Até esses gates passarem, o perfil Expert deve permanecer indisponível e o candidato atual deve ser tratado somente como evidência de engenharia e diagnóstico.

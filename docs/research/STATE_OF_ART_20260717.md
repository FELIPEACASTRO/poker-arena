# Estado da arte, fontes de dados e plano experimental — 2026-07-17

> **Snapshot de pesquisa, não certificado de release.** Catálogos, preços, licenças e
> disponibilidade de hardware podem mudar. Para o contrato executável atual, consulte a
> [governança de datasets](../DATASET_GOVERNANCE.md), o
> [inventário de notebooks](../../ml/README.md), os
> [model cards/manifesto](../../backend/models/README.md) e a
> [documentação gerada da API](../../api-docs/README.md). Resultado de QA só é atual quando
> vem de uma execução do gate no mesmo checkout.

## Resumo executivo

Esta revisão combinou inspeção do código e dos artefatos locais, consultas públicas
metadata-only no Kaggle/Hugging Face, documentação oficial e literatura primária.
O resultado mais importante não é trocar imediatamente todos os modelos: é impedir
que dados, nomes de checkpoints e métricas frágeis sejam promovidos como evidência.

Decisões:

1. **Estratégia:** PHH v3 é a maior fonte comportamental **histórica** encontrada;
   PokerBench é somente warm-start/benchmark auxiliar. Depois do encoder v2, PPO é o controle obrigatório;
   PSRO só entra como challenger de diversidade empírica. O encoder e o simulador atuais
   ainda não autorizam alegações de CFR/GTO em NLHE 6-max.
2. **Visão:** o maior gap é um corpus real independente de screenshots com rótulo de
   estado completo. PP-OCRv6 é o challenger imediato de OCR; D-FINE-N e RF-DETR Nano
   são challengers de detecção. Nenhum checkpoint público encontrado deve substituir
   diretamente o modelo local.
3. **Governança:** toda ingestão e promoção deve ser pinada, hasheada, licenciada,
   agrupada contra leakage e avaliada fora do domínio de treino. O manifesto v1 e os
   gates fail-closed estáticos agora existem no projeto; eles não demonstram que um
   dataset, treino ou promoção concreta já passou em execução.
4. **Compute:** a hipótese inicial é usar CPU para parsing, QA, Monte Carlo e probes
   pequenos de PSRO/PPO; L4 é a primeira candidata para profiling de visão/behavioral
   cloning. A100/H100 só entram depois de medir throughput por dólar. Nenhum job Modal
   foi disparado nesta auditoria, portanto isso é sizing preliminar, não benchmark.

![Arquitetura proposta baseada em evidências](architecture.svg)

A auditoria complementar dos 156 serviços do catálogo, incluindo o recorte Ásia/Índia/
Rússia/Canadá, está no [relatório de plataformas](PLATFORM_SWEEP_20260717.md). Os três
receipts detalhados cobrem cada URL do anexo e sua união é verificada por teste.

## Escopo e método

O catálogo foi pesquisado por famílias de consultas relevantes; “exaustivo” significa
todos os resultados devolvidos por essas consultas paginadas, não todos os objetos que
possam existir nas plataformas.

O [receipt público e sanitizado de 2026-07-18 UTC](evidence/catalog_search_snapshot_20260718.md)
registra consulta, endpoint oficial, timestamp, status, tamanho e SHA-256 das respostas,
sem ler tokens nem baixar artefatos:

O coletor foi endurecido depois dessa coleta para ignorar proxies do ambiente/sistema,
recusar redirects e validar esquema/host/path antes de criar a requisição. O
[receipt de hardening](evidence/catalog_collector_hardening_20260718.json) preserva
separadamente o SHA do coletor histórico e o SHA do código endurecido; o snapshot não
foi retroativamente reetiquetado como se tivesse usado o transporte novo.

| Catálogo | Cobertura observada no receipt público |
|---|---:|
| Hugging Face datasets | 81 IDs únicos |
| Hugging Face models | 104 IDs únicos |
| Kaggle datasets | 67 IDs únicos |
| Kaggle Code | 5 consultas retornaram `401`; cobertura inconclusiva |

Foram 23 requisições: 18 concluídas e 5 bloqueadas. As contagens anteriores, obtidas em
uma sessão sem receipt completo, permanecem apenas como nota histórica e não sustentam
alegação de cobertura. O snapshot novo também não é censo: mede somente os resultados
devolvidos pelas consultas, limites e endpoints registrados.

Cada candidato foi avaliado por licença/proveniência, aderência ao domínio, integridade
dos rótulos, revisão imutável, duplicatas/leakage, avaliação independente, contrato
ONNX, custo/latência e adequação da métrica. Evidência observada é separada de proposta
experimental; valores futuros não são apresentados como resultados já obtidos.

## Achados locais que alteravam conclusões

### Priors do oponente

O notebook 07 usava `setdefault` ao agrupar a árvore PHH e acabava selecionando o
primeiro diretório de cada site. Na ordem do snapshot v3, isso concentrava os seis
sites em 1000NLH. Além disso, `cc` era contabilizado como call mesmo quando `owe == 0`,
misturando checks no denominador de agressividade. Portanto 0,70/0,46 não eram priors
populacionais demonstrados. Eles foram removidos do runtime e substituídos por um
prior fraco Beta(1,1), média 0,5.

O contrato estático do notebook corrigido exige:

- tag/commit PHH v3 `e2ec038d31a1a46a82d147db4bbfdb0910459705`;
- root tree `a1c33bedd561407860b2467bffb4257317e9d6ce`;
- verificação commit→tree, `truncated == false`, Git blob SHA-1 e SHA-256 local;
- amostragem determinística entre 27 estratos site×stake;
- checks fora de calls, parser fail-closed e cobertura integral da quota;
- 30 seeds, blocos pareados, bootstrap e intervalos simultâneos Bonferroni;
- seleção multi-seed, receipt de seleção e publicação opt-in em caminho de candidato
  content-addressed.

Esses itens descrevem o código do notebook, não um treino reproduzido nesta revisão:
nenhum checkpoint, receipt de execução ou métrica de promoção foi produzido aqui.

O [PHH v3 oficial](https://zenodo.org/records/17136841) contém 20,3 GB, MD5 publicado,
21,6 milhões de mãos humanas NLHE, 10 mil mãos Pluribus e centenas de milhões de mãos
ACPC, inclusive duplicatas declaradas. As mãos humanas são logs anonimizados coletados
entre **1 e 23 de julho de 2009**: são úteis para regressão histórica, não representam o
meta atual e não podem calibrar um opponent model contemporâneo sem holdout moderno,
autorizado, externo e temporal. O bundle local com 13 mãos Pluribus é adequado para
replay/demonstração, não para inferência estatística.

### Checkpoint visual

O notebook 08 declarava YOLO11n, treinava `yolo11s.pt` e publicava arquivos chamados
`table_yolo11n.*`. Uma reexecução poderia sobrescrever silenciosamente um nano por um
small. O notebook 08 agora exige um peso-base local com SHA-256 informado pelo operador,
usa uma constante única de arquitetura e gera somente um bundle candidato
content-addressed com manifesto e receipt. Publicação continua opt-in e não equivale a
promoção. Também foram removidas promessas de “qualquer UI”: held-out sintético mede
apenas estilos do gerador. Nenhum treino desse notebook foi executado nesta revisão.

### Integrações alegadas

Não havia integração executável de ingestão com Kaggle. Agora existe apenas um coletor
público de catálogo, metadata-only e sem credenciais; ele não baixa nem autoriza uso de
dataset. O notebook 07 usa GitHub/Zenodo e HF; o 08 gera dados sintéticos localmente;
o 09 exige checkout pinado e manifesto validado para qualquer corpus real; e o 11 gera
somente um candidato sintético para o leitor de cartas, explicitamente não promovível
sem validação real e governança. Esses são contratos de execução, não evidência de que
os dados ou modelos tenham sido aprovados.
Qualquer ingestão futura deve fixar `owner/slug`, versão, lista de arquivos, hashes e
licença. Presença de `kaggle.json` ou de um item no receipt não prova ingestão ou qualidade.

## Fontes estratégicas

| Fonte | Evidência e licença declaradas pela fonte | Uso técnico proposto | Risco/gate |
|---|---|---|---|
| [PHH v3 / Zenodo](https://zenodo.org/records/17136841) | CC BY 4.0; 11 variantes; humanos de julho/2009, ACPC, Pluribus | ETL, replay, cross-play histórico | dedup; split fonte/jogador/sessão/tempo; holdout moderno autorizado; ações humanas não são GTO |
| [takara-ai/poker_hands](https://huggingface.co/datasets/takara-ai/poker_hands) | 21.616.175 linhas, 35 colunas, 1,285 GB Parquet, revisão `6acb5afb6f43082e6a468fde578890d9188be393` | streaming/feature engineering mais eficiente | reconciliar amostras/hashes com o PHH oficial |
| [PokerBench](https://huggingface.co/datasets/RZ412/PokerBench) | 574.200 exemplos, Apache-2.0, decisões de solver | warm-start e action-agreement auxiliar | fixar revisão `7ac61f961c81a50fc0f667820b2fb0e432dfec0d`; nunca substituir bb/100 |
| [Kaggle Poker Heads-Up](https://www.kaggle.com/datasets/kaggle/poker-heads-up) | ~2,1 M mãos/105 matchups, CC BY 4.0 | OOD e diversidade de estilos LLM | não é GTO; manter mãos espelhadas no mesmo split |
| [Equity Monte Carlo](https://www.kaggle.com/datasets/benjaminniesmertelny/texas-holdem-monte-carlo-data) | preflop agregado por classe e nº de jogadores | oracle agregado/teste de convergência | flop/turn/river não são cache de combinações exatas |

As licenças acima são metadados declarados pelas fontes, não clearance jurídico. Antes
de redistribuir ou treinar, revisar proveniência, arquivos individuais e termos vigentes,
especialmente em coleções agregadas, raspadas ou derivadas de terceiros.

Notas locais históricas registravam alta concordância de PokerBench sem força no
cross-play, mas não há receipt/hash/métricas dessa execução ligado a este relatório.
Logo, a divergência é uma hipótese a reproduzir; action-agreement não pode ser a única
métrica de promoção.

### Algoritmos

O encoder atual perde histórico de apostas, agressor, raises por rua, estado/stack por
assento, stack efetivo, SPR e side pots. Estados estrategicamente diferentes podem
colidir no mesmo vetor. O self-play também reinicia stacks e não expõe chance nodes,
reach probabilities ou clone de estado no formato exigido por CFR.

Ordem proposta:

1. **Reformular o estado observável** e versionar o contrato do encoder.
2. **PPO como controle obrigatório**, com current-policy self-play e league/checkpoint
   como ablações, cross-play pareado e protocolo congelado. A versão v4 do
   [benchmark IIG](https://arxiv.org/abs/2502.08938v4) relata mais de 7.000 runs em cinco
   jogos e não encontrou vantagem de deep-RL baseado em FP/DO/CFR sobre policy gradients
   genéricos. Os autores enfatizam que quatro jogos são homogêneos, que a ordem relativa não
   é universal nem nos cinco, que só um representante FP/DO/CFR foi testado e que tuning e
   orçamento de 10 milhões de passos limitam a conclusão. Isso muda a ordem experimental,
   mas não prova PPO em NLHE 6-max.
3. **PSRO/SP-PSRO** para diversidade contra oponentes não transitivos somente após PPO,
   inicialmente no adaptador formal de dois jogadores. Em 6-max customizado isso mede
   robustez do meta-jogo, não exploitability/GTO. Veja a
   [implementação oficial OpenSpiel](https://github.com/google-deepmind/open_spiel) e a
   [lista oficial de algoritmos](https://github.com/google-deepmind/open_spiel/blob/master/docs/algorithms.md).
4. **NFSP** como baseline neural em Kuhn/Leduc e, depois, em adaptador formalmente
   verificado.
5. **CFR/MCCFR/DCFR/Deep CFR** somente numa trilha OpenSpiel separada, começando por
   Kuhn/Leduc/HU. O modelo de estado do OpenSpiel exige histórico e chance explícitos,
   conforme a [documentação conceitual](https://github.com/google-deepmind/open_spiel/blob/master/docs/concepts.md).
6. **Opponent modelling como cabeça separada:** testar histórico/tokenização e contextos
   no estilo [StratFormer](https://arxiv.org/abs/2604.25796v1), que só demonstrou seus
   resultados em Leduc; sem tratar seus números como evidência de NLHE.
7. Avaliar com matriz cross-play, troca de assentos, duplicate deals, seeds independentes,
   ICs pareados e pior confronto. Não chamar desempenho 6-max de “GTO”.
8. Na trilha NFSP formal, registrar a origem behavior-policy/exploração de cada transição e
   testar a exclusão de ações exploratórias da memória supervisionada, conforme o
   [experimento JSAI em Leduc](https://www.jstage.jst.go.jp/article/pjsai/JSAI2018/0/JSAI2018_1N301/_article/-char/en).
9. Comparar duplicate deals com [AIVAT](https://ojs.aaai.org/index.php/AAAI/article/view/11481)
   somente quando chance history, probabilidades da política conhecida e value estimate forem
   verificáveis; antes disso, a alegação de estimador não enviesado não é transferível.

Para gate externo final HUNL 200bb, o
[GTO Wizard Benchmark](https://gtowizard.com/benchmark/) oferece AIVAT e ranqueia pelo
limite inferior do IC de 95%. O uso requer aprovação e é estritamente avaliação: os
[termos](https://gtowizard.com/benchmark/terms) proíbem mineração, distilação, treino e
calibração com os dados da API. Ele não valida 6-max.

## Fontes e modelos de visão

### OCR

O runtime atual usa PP-OCRv4 (~15,60 MB no total). A família oficial PP-OCRv6 ONNX é
Apache-2.0 e deve entrar como challenger, não como troca cega.

| Variante | Detector | Recognizer | Total | Hipótese |
|---|---:|---:|---:|---|
| v6 tiny | 1,78 MB | 4,46 MB | 6,24 MB | eficiência |
| v6 small | 9,88 MB | 21,16 MB | 31,04 MB | melhor compromisso provável |
| v6 medium | 62,03 MB | 76,55 MB | 138,59 MB | teto de acurácia/custo |

Fontes oficiais: [visão geral PP-OCRv6](https://huggingface.co/blog/PaddlePaddle/pp-ocrv6),
[tiny det](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_det_onnx),
[tiny rec](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_rec_onnx),
[small det](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det_onnx) e
[small rec](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx).
Esses links são pontos de descoberta mutáveis: qualquer benchmark deve registrar commit
ou release, revisão do modelo, lista de arquivos e SHA-256 dos pesos usados.

O recognizer v6 não é drop-in no RapidOCR atual: usa altura 48, saída de 6.906 classes
e não traz a metadata `character` usada pelo v4. O benchmark precisa usar
`inference.yml`, dicionário e pré/pós-processamento oficiais. Métricas: exact-field,
CER, falsa leitura, coverage/abstenção, p50/p95 CPU e RSS, estratificadas por tema,
escala, blur e compressão.

### Detector e classificador

| Candidato | Licença observada | Papel | Condição de entrada |
|---|---|---|---|
| YOLO11n local | metadata AGPL-3.0 | baseline atual | decisão jurídica + manifesto/benchmark real |
| [D-FINE-N](https://github.com/Peterande/D-FINE) | Apache-2.0 | principal challenger de detector | fixar commit/release/pesos+SHA-256; export ONNX e latência no mesmo hardware |
| [RF-DETR Nano](https://github.com/roboflow/rf-detr) | Apache-2.0 para componentes designados | challenger de acurácia | fixar commit/release/pesos+SHA-256 e validar licença do artefato exato |
| MobileNetV3-small dual head | BSD-3-Clause no torchvision | rank/suit após crop | comparar erro semântico e calibração |

Arquitetura recomendada: detector de seis classes genéricas (hole card, board card,
seat, button, pot, stack), crop/retificação, classificador separado rank/suit, OCR só
em ROIs numéricas, geometria determinística e consenso temporal. Isso reduz o acoplamento
de 52 classes visuais com layout e permite calibrar/abster por campo.

### Datasets visuais

- O RF100 `poker-cards-cxcvz` está **em quarentena**. A inspeção do Viewer encontrou
  classes semanticamente desalinhadas (`59`, `10 Hearts`, `5 Trefoils`, `5 Spades`);
  não existe remapeamento simples seguro. Os mirrors
  [Francesco](https://huggingface.co/datasets/Francesco/poker-cards-cxcvz) e
  [LibreYOLO](https://huggingface.co/datasets/LibreYOLO/poker-cards-cxcvz) não devem
  alimentar treino automático antes de auditoria visual de todas as classes.
- [Playing Cards Object Detection](https://www.kaggle.com/datasets/andy8744/playing-cards-object-detection-dataset)
  é o melhor pré-treino físico encontrado (52 cartas, YOLO, CC0 segundo metadata), mas
  frames de vídeo devem ser agrupados por vídeo/deck/sessão. Não prova screenshot online.
- MRPH e os pequenos datasets PokerStars podem servir apenas como stress test/relabel
  autorizado; faltam boxes ou licença/proveniência suficiente.
- `screenparse` e grandes corpora genéricos de UI só fazem sentido como pré-treino
  opcional/streaming. Baixar centenas de GB antes de demonstrar ganho é injustificado.

O corpus decisivo precisa ser próprio/autorizado: sugestão de gate inicial, não
resultado, é ≥1.200 screenshots rotulados de ≥4 clientes, com splits por
cliente/sessão/tema/deck e OOD completo. Registrar SHA-256/pHash, rótulo de estado
completo, exact-state, FAR, coverage, AURC, ECE, latência, RAM e paridade ONNX.

## Modal: escolha de CPU/GPU e orçamento

Preços consultados na [página oficial do Modal](https://modal.com/pricing) em
2026-07-17; mudam ao longo do tempo.

| Recurso | USD/h aproximado | Hipótese inicial de uso |
|---|---:|---|
| CPU físico | 0,04716 por core | parsing, QA, Monte Carlo, CFR pequeno |
| T4 | 0,5904 | probe barato/compatibilidade |
| L4 | 0,7992 | primeira candidata a profiling para visão/BC |
| A10 | 1,1016 | controle opcional |
| L40S | 1,9512 | challenger quando memória/throughput limitarem L4 |
| A100 40 GB | 2,0988 | só após profiling |
| A100 80 GB | 2,4984 | modelos/batches que realmente usem memória extra |
| H100 | 3,9492 | não justificado no estágio atual |

A [documentação oficial de GPU](https://modal.com/docs/guide/gpu) permite selecionar
tipo/quantidade explicitamente. O primeiro probe proposto é 15 min em T4/L4/L40S/A100
40 GB, 8 CPU e 32 GiB, orçamento total estimado abaixo de USD 2,50. Cada job deve ter
timeout, `max_containers`, tags e revisão/hashes. Modal Volumes são mutáveis; artefatos
devem usar caminhos content-addressed/write-once, SHA-256 e manifesto, e consumidores
devem montá-los somente para leitura. Interromper se import, dataset ou métrica divergir.
Credenciais foram apenas validadas sem exposição.

## Gates de promoção

### Estratégia

- configuração, código, dataset, modelo e baseline pinados;
- desenho pré-registrado com ID, unidade de bloco, MDE, margem de não inferioridade e análise
  de dependência/poder antes de observar o candidato;
- ≥30 blocos pareados por confronto e seeds independentes;
- IC bootstrap agregado com limite inferior > 0 bb/100;
- IC simultâneo por matchup com FWER controlado, margem justificada no pré-registro e
  half-width compatível com o MDE; sem ID/MDE/margem, falha fechada;
- matriz completa, pior matchup, rotação e duplicate deals;
- nenhum resultado de PokerBench/PHH promovido como força sem cross-play.

### Visão

- corpus real independente e sem sobreposição de grupo/pHash;
- exact-state como métrica primária; métricas por campo/cliente/deck/tema;
- FAR e abstenção calibrados, além de mAP/CER;
- p50/p95/RSS no hardware alvo e paridade Python↔ONNX;
- falha fechada em modelo/dicionário/schema incompatível;
- licença e model card do artefato exato.

### Artefatos

Publicar primeiro em `candidates/<run-id-ou-hash>/`; validar hash retornado pelo Hub;
promover apenas atualizando manifesto canônico de forma atômica. Nunca sobrescrever o
canônico a partir de um notebook que também o usa como baseline.

## O que foi implementado nesta revisão

- manifesto de dataset, schema JSON, exemplo e CLI fail-closed, com revisão de perfil,
  receipt do próprio manifesto, detecção TOCTOU, caminhos/IDs canônicos, identidade de
  arquivo e limites por arquivo e agregados;
- parser PHH endurecido e notebook 07 pinado/estratificado;
- gate estratégico sem margem universal pós-hoc: 30 blocos, pré-registro, MDE, precisão e
  Bonferroni registrados no receipt;
- prior neutro no `OpponentModel` e regressão contra checks no denominador;
- contratos de identidade, determinismo, manifesto e publicação opt-in no notebook 08;
  checkout/manifesto/labels/splits pinados no 09; e bundle candidato não promovível no
  11. Nenhum desses notebooks foi treinado ou publicado nesta revisão;
- os notebooks 03/05/06/07/08/09 exigem `HF_REPO_ID` validado e não contêm namespace
  pessoal;
- contratos estáticos que parseiam/compilam todos os notebooks e bloqueiam tokens/URLs
  autenticadas, drift de arquitetura e revisões mutáveis críticas;
- oráculo diferencial PokerKit para ranking, ordem, blinds, side pots, odd chips,
  min-raise e reabertura de all-in;
- manifesto de modelos fechado por lifecycle/kind, contenção física sob a raiz do
  manifesto, limites de payload e separação fail-closed entre candidato e promovido;
- VLM remoto protegido por token obrigatório, origem local, consentimento efêmero emitido
  pelo servidor, revogação e prontidão degradada quando a configuração está incompleta;
- Swagger/OpenAPI e Insomnia gerados do runtime com verificação read-only de drift;
- tipagem, lint, segurança da API/frontend e documentação corrigidas;
- gate QA hermético com ambiente allowlisted, runtimes únicos, timeout por etapa,
  encerramento em árvore, coverage de branches, auditorias de dependência e navegação E2E;
- receipt regional adicional com J-STAGE, CiNii, KoreaScience, CPRG/Canadá, HSE/CyberLeninka
  e fontes indianas, incluindo bloqueio de provável SEO poisoning acadêmico.

## Lacunas residuais e sequência recomendada

1. Coletar/rotular o corpus real autorizado; sem isso, não gastar GPU em novo detector.
2. Executar benchmark PP-OCRv4×v6 e YOLO11n×D-FINE-N×RF-DETR Nano, um fator por vez.
3. Versionar encoder v2 com histórico/estado por assento e medir colisões antes do PSRO.
4. Rodar PHH v3 em CPU, publicar apenas priors/candidatos que passam manifestos e gates.
5. Fazer probe Modal L4 somente depois dos datasets e testes locais estarem congelados.
6. Solicitar GTO Wizard apenas para gate HUNL final e respeitar integralmente os termos.

Nenhum novo número de qualidade foi fabricado: modelos remotos não foram promovidos e
nenhum treino Modal foi iniciado nesta etapa de auditoria/engenharia.

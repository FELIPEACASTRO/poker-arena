# Varredura auditável das plataformas — seções 1 a 4

**Data do probe:** 17 de julho de 2026, America/Sao_Paulo

**Inventário de origem:** `plataformas_concorrentes_equivalentes_arxiv (3).md`, SHA-256
`8f411d8bac4d6f0ac4103d7eb9593406bd84b758e9ecc6e28dd8bc6364a08204`.

**Cobertura:** 54 de 54 plataformas; seções 1, 2, 3 e 4.

**Registro estruturado canônico:** [`platform_sweep_sections_1_4.json`](platform_sweep_sections_1_4.json)

## Resultado executivo

A busca encontrou dois ativos diretamente ligados a poker e um conjunto útil de técnicas de avaliação/arquitetura. Ela **não encontrou um novo peso treinado que possa substituir com segurança o stack atual sem benchmark local**.

Os resultados mais relevantes são:

1. [Poker Hand Histories v3 — Zenodo](https://zenodo.org/records/17136841): forte candidato para parser, replay, testes de regras e modelagem temporal, sujeito a deduplicação, splits por fonte/jogador/sessão e auditoria de licença por subfonte.
2. [Mandine's Real Poker Hands — HAL](https://hal.science/hal-05640595v1) / [Kaggle](https://www.kaggle.com/datasets/arnaudlewandowski/mandines-real-poker-hands-mrph-dataset): 2.277 imagens de mãos físicas de cinco cartas, mas com licença conflitante, mistura de fontes, provável leakage em split aleatório, rótulo apenas da mão inteira e forte desvio frente a screenshots Hold'em. O status correto é **quarentena**, não adoção.
3. [Poker Cards FMJIO — Roboflow](https://universe.roboflow.com/roboflow-jvuqo/poker-cards-fmjio): candidato visual mais alinhado à detecção por carta, com 52 classes e CC BY 4.0 observada; ainda requer fixar versão, separar imagens fonte de augmentations e validar fora do domínio Roboflow.
4. OpenReview e Preprints.org trouxeram hipóteses de self-play, league/checkpoint evaluation e ISMCTS. Todas permanecem challengers porque as evidências são preprints/submissões não reproduzidas.
5. ChemRxiv, medRxiv e EarthArXiv reforçam três mudanças metodológicas: decoder estrutural após visão, quality gates com abstenção e validação externa com calibração por domínio.

Não foi contornado robots.txt, CAPTCHA, login, paywall ou bloqueio anti-bot. Nenhuma credencial foi impressa ou incorporada aos artefatos.

## Método, cobertura e limites

Cada URL foi aberta diretamente no cliente de pesquisa. Depois foi feita pelo menos uma consulta `site:` por plataforma. Os acervos com sinal receberam buscas estreitas; HAL, Zenodo, OpenReview, OSF e Figshare foram também consultados pelas APIs públicas oficiais.

Uma falha no cliente significa apenas que aquela rota não pôde ser examinada diretamente naquele momento. Ela **não prova que a plataforma esteja fora do ar**. Quando uma página primária específica apareceu em índice público e pôde ser aberta, ela foi usada sem tentar contornar o bloqueio da homepage.

| Medida | Resultado observado |
|---|---:|
| Plataformas previstas / auditadas | 54 / 54 |
| Seção 1 / 2 / 3 / 4 | 24 / 7 / 16 / 7 |
| Conteúdo direto, parcial, shell ou redirecionamento útil | 34 |
| Acesso limitado, bloqueio ou erro no cliente | 20 |
| Consultas amplas site-specific | 54 |
| Consultas temáticas retidas via API oficial | 34 |
| Plataformas com evidência técnica diretamente acionável ou de alto sinal | 9 |
| Plataformas sem evidência técnica de alto sinal retida | 45 |

As contagens das APIs são snapshots e não devem ser comparadas entre si: cada índice tem campos, stemming, deduplicação e caps diferentes. Contagem de resultado também não implica relevância, licença ou disponibilidade de código/peso.

## Receipt regional verificável: Ásia, Canadá, Rússia e Índia

Este relatório cobre estritamente as seções 1–4. Nesse recorte, o inventário contém **uma** plataforma regional asiática explicitamente identificável — **Jxiv/Japão** — e **zero** plataformas explicitamente canadenses, russas ou indianas. Repositórios globais não foram reclassificados por suposição.

| Região solicitada | Plataformas no recorte 1–4 | Cobertura comprovável |
|---|---:|---|
| Ásia | 1 | [Jxiv — JST Preprint Server](https://jxiv.jst.go.jp/) aberta e pesquisada em japonês e inglês |
| Canadá | 0 | Nenhuma linha explicitamente canadense nas seções 1–4 |
| Rússia | 0 | `Preprints.ru` está na seção 7 e pertence ao artefato das seções 5–8 |
| Índia | 0 | `IndiaRxiv` está na seção 7 e pertence ao artefato das seções 5–8 |

Na Jxiv foram executadas três consultas regionais complementares:

1. `ポーカー OR テキサスホールデム OR 不完全情報ゲーム OR 自己対戦 OR 対戦相手モデリング`;
2. `光学文字認識 OR OCR OR コンピュータビジョン OR 画像認識 OR キャリブレーション`;
3. `poker OR "imperfect information" OR "self-play" OR "opponent modeling"`.

Nenhum dataset, peso, algoritmo ou paper diretamente ligado a poker/jogos de informação imperfeita foi retido. A busca local recuperou [um preprint Jxiv sobre microserviço local seguro com OCR](https://jxiv.jst.go.jp/index.php/jxiv/preprint/view/1364), DOI `10.51094/jxiv.1364`; ele descreve isolamento de OCR, processamento local e logs, mas não publica benchmark de cartas, modelo ou dataset aproveitável. Portanto, é evidência arquitetural indireta e não recomendação de troca tecnológica.

Para a auditoria global: [ChinaXiv](http://chinaxiv.org/), [IndiaRxiv](https://ops.iihr.res.in/index.php/IndiaRxiv) e [Preprints.ru](https://preprints.ru/) aparecem na seção 7 e devem ser contabilizados no relatório das seções 5–8, sem duplicação neste arquivo. Bloqueios regionais foram registrados sem contorno; quando possível, foi usado apenas índice oficial ou página primária pública.

## Contagens reproduzíveis das APIs oficiais

| Plataforma | poker | imperfect information | opponent modeling | self-play | OCR | computer vision | calibration | dataset |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| [HAL API](https://api.archives-ouvertes.fr/) | 179 | 338 | 10 | 28 | 954 | 9.768 | 20.874 | 32.290 |
| [Zenodo API](https://zenodo.org/api/records) | 203 | 92 | 7 | 62 | 3.370 | 10.954 | 20.398 | 258.298 |
| [OpenReview API v2](https://docs.openreview.net/reference/api-v2/openapi-definition) | 192 | 469 | 110 | 576 | 1.478 | >=10.000 | >=10.000 | >=10.000 |

No OpenReview, `>=10.000` é limite inferior/cap observado. No OSF, a busca usada era substring de título: quatro resultados para `poker`, nenhum técnico; zero para `imperfect information`, `opponent modeling` e `self-play`; termos amplos retornaram dez itens na primeira página com `has_next=true`, sem total confiável. No Figshare, a API devolveu 159 itens para `poker` e sete para `poker hand`; estes eram sobretudo figuras de desempenho, não um novo corpus utilizável.

## Auditoria dos datasets de poker

### PHH v3 — prioridade para regras, replay e opponent modelling

O [registro Zenodo](https://zenodo.org/records/17136841), DOI `10.5281/zenodo.17136841`, descreve um arquivo de 20,3 GB, MD5 `5a49377ab4ea30db3aa887c8e0ce580f`, com 11 variantes. O registro reporta:

- 341.172.750 mãos fixed-limit e 278.842.225 heads-up no-limit do ACPC, incluindo duplicatas;
- 21.605.687 mãos humanas NLHE não corrompidas;
- 10.000 mãos de Pluribus.

Isso é evidência forte para contratos de parsing e invariantes de estado, mas não autoriza misturar tudo em um treino. A ingestão deve preservar fonte/variante, deduplicar, verificar direitos de cada subfonte e separar treino/teste por jogador e sessão. PHH não resolve visão: é histórico textual.

### MRPH — quarentena obrigatória

O pacote [MRPH no Kaggle](https://www.kaggle.com/datasets/arnaudlewandowski/mandines-real-poker-hands-mrph-dataset), DOI `10.34740/kaggle/dsv/16370247`, tinha 288.086.864 bytes, 2.281 arquivos e atualização em 2 de junho de 2026. Foram auditados os metadados e três arquivos pequenos, sem baixar o corpus completo:

| Item | Evidência observada |
|---|---|
| Imagens | 2.277: 1.111 `.JPEG` e 1.166 `.JPG` |
| Labels | 2.277 linhas, sem filename/label vazio ou duplicado |
| Tarefa | uma classe de mão completa, exatamente cinco cartas; sem box/rank/suit por carta no CSV |
| Fontes no README | Poker Combos 140; Poker Cards 176; Doni Kurniawan 507; fotos do autor 1.454 |
| Licença nos metadados | CC BY 4.0 |
| Licença no README | CC BY-NC 4.0 — conflito material |
| README SHA-256 | `4641C06E5CB93C2094EFD6F5C1B321B93962618ACED36D307D755E1D0AD5EB87` |
| labels.csv SHA-256 | `FF929B98E126D2513A539C7F648F005968DAF1A3820A6A14B9EDE57B9B0BD209` |
| poker_hands.owl SHA-256 | `0E54BE7D0ECE528910E7BD315A5953C30D090A3EBB2FB30ED20EBD4864D8EE29` |

Distribuição observada: HighCard 320, Flush 309, TwoPairs 259, Straight 230, FourOfAKind 212, ThreeOfAKind 207, RoyalFlush 197, Pair 195, StraightFlush 179 e FullHouse 169. Essa distribuição quase balanceada é muito diferente dos priors naturais do poker. Portanto, o dataset não pode calibrar a probabilidade de ocorrência das mãos.

O risco de leakage é alto: imagens de três datasets Roboflow e fotos do autor podem compartilhar baralho, fundo, iluminação, captura e augmentations. Um random split pode medir memorização visual em vez de generalização. Mãos físicas de cinco cartas também diferem das ROIs de cartas comunitárias, hole cards e HUDs em screenshots.

Decisão: **não integrar ao treino principal agora**. Para reabrir a decisão são necessários:

1. resolver por escrito CC BY versus CC BY-NC e confirmar licença/proveniência das quatro fontes;
2. construir grupos por fonte, sessão, baralho, fundo e derivação/augmentation;
3. treinar apenas como auxiliary/challenger;
4. avaliar em holdout real de screenshots, com ECE, Brier, risco-cobertura, erro crítico e latência;
5. rejeitar se a melhoria desaparecer fora do domínio físico.

### Fontes Roboflow upstream

[Poker Cards FMJIO](https://universe.roboflow.com/roboflow-jvuqo/poker-cards-fmjio) declarava CC BY 4.0, 442 imagens fonte, 899 imagens na versão 4, 52 classes e tarefa de object detection. É mais próximo da necessidade de reconhecer rank/suit por carta, mas augmentations da mesma fonte não podem cruzar splits.

[Poker Hands by Doni Kurniawan](https://universe.roboflow.com/desides-citra/poker-hands-by-doni-kurniawan) declarava CC BY 4.0, 1.059 imagens e 56 classes; foram observadas classes extras/ruidosas como `d`, `h`, `TH` e `objects`. Exige normalização de ontologia e revisão manual antes de qualquer uso.

## Modelos, algoritmos e técnicas de maior sinal

| Evidência primária | Observação | Inferência limitada para a solução |
|---|---|---|
| [Self-Play RL under Imperfect Information in Big 2 — OpenReview](https://openreview.net/pdf/23db71c7221d2db821991ab3e6858d38fedb7b14.pdf) | Submissão relata PPO acima de MC-Q/SARSA/Q, entropia moderada útil e current-policy self-play melhor que oponente fixo/checkpoint sob orçamento finito. | Challenger de current-policy self-play versus league/checkpoint; medir contra população externa e exploitability/proxy. Em revisão e não reproduzido. |
| [Superhuman AI for Generals.io — OpenReview](https://openreview.net/pdf?id=Rb79jWnVDX) | Simulador JAX, policy gradient regularizado, quatro dias em 4xH200; código prometido após aceitação. | Transferir apenas padrão de simulador vetorizado/paridade. Não justificar 4xH200 sem código, licença, ablação e sinal local. |
| [From Minimax to Self-Play — Preprints.org](https://www.preprints.org/manuscript/202605.0057) | Survey não revisado sobre ISMCTS, strategy fusion, anytime planning e robustez multioponente. | Usar como taxonomia de benchmark/risco, não como prova para substituir algoritmo atual. |
| [Hybrid Multi-Agent AI/MCTS — SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5784417) | Nove páginas; 3.873 jogos MCTS; +15–25% win rate e belief accuracy de 70–80% autorrelatados. | Ideia de separar belief model, planner e executor; evidência fraca até haver código, seeds, IC e adversários externos. |
| [3D2SMILES — ChemRxiv](https://chemrxiv.org/engage/chemrxiv/article-details/67d9f6aa6dde43c908590f85) | Dados sintéticos+reais, múltiplas imagens, beam top-k; top-1 62,0 e top-3 80,3 no domínio químico. | Testar multi-crop/temporal ensemble e decoder estrutural que valide rank/suit/board. Métricas não transferem. |
| [Closed-Loop vision-guided control — ChemRxiv](https://chemrxiv.org/engage/chemrxiv/article-details/6842fee8c1cb1ecda0e37e5b) | YOLO + regras de fase + iluminação controlada. | Quality gates de resolução, blur, contraste, ROI e consistência temporal; falha deve gerar abstenção. |
| [VLMs e sinais vitais — medRxiv](https://www.medrxiv.org/content/10.64898/2026.06.10.26355351v1.full) | Em 200 fotos, preprint relata Qwen3.5-9B LoRA rank 8, 80–120 imagens, 0,953→0,994 e erro crítico 0,0313→0,0063. | Apenas challenger offline em ROIs ambíguas contra OCR+regras. Modelo pesado, amostra pequena, números não reproduzidos. |
| [Foundation models e external shift — medRxiv](https://www.medrxiv.org/content/10.64898/2026.04.17.26351092v1.full) | AUROC interna 0,90–0,98 teria caído para 0,70–0,85 externamente; calibração ruim. | Gate obrigatório por site/tema/resolução/dispositivo/sessão, com ECE, Brier e reliability. Transferir protocolo, não efeito. |
| [Reconstrução de níveis de rio — EarthArXiv](https://eartharxiv.org/repository/view/10491/) | Dewarping, transformer, pixel-to-curve, provenance por página, uncertainty flags, ground truth e revisão humana direcionada. | Split agrupado, lineage por ROI e adjudicação de baixa confiança/conflitos; nunca dividir fragmentos da mesma captura entre treino/teste. |
| [Visão com iluminação controlada — Organic Eprints](https://orgprints.org/id/eprint/36551/) | 4200K, câmera/Raspberry Pi, features simples de cor/morfologia e calibração; R²P >0,99 autorrelatado. | Baseline simples e controle de captura para modo câmera. Métrica agrícola não é evidência de poker. |

Também foi observado que [Cell Press Sneak Peek](https://www.ssrn.com/index.cfm/en/cell-press-sneak-peek/) reservava direitos de text/data mining e AI training. Conteúdo indexado não é automaticamente um corpus autorizado. Essa regra deve valer para qualquer paper, PDF, tabela ou imagem recuperada.

## Melhorias recomendadas, com gates mensuráveis

| Prioridade | Mudança | Gate mínimo |
|---|---|---|
| P0 | Split anti-leakage por fonte, site, sessão, tema, resolução, baralho/fundo e cadeia de augmentation | manifesto de grupos; hashes; detector de near-duplicate; holdout externo intocado |
| P0 | Calibração e selective prediction | ECE, Brier, NLL, reliability, risco-cobertura e erro crítico por domínio; thresholds derivados só em validação |
| P0 | Quarentena do MRPH | licença única comprovada; fontes/versionamento fixados; split por grupo e revisão de leakage |
| P1 | Decoder estrutural após visão | carta duplicada/impossível, street incoerente, pot/bet impossível ou conflito temporal geram abstenção, não autocorreção silenciosa |
| P1 | PHH v3 como contrato de regras/replay | parser round-trip; invariantes por variante; dedup; splits temporal/jogador/sessão; provenance por mão |
| P1 | Poker Cards FMJIO/MRPH só como challenger | ablação contra baseline em screenshot holdout real; IC e ausência de regressão em calibração/latência |
| P2 | Current-policy self-play versus league/checkpoint | seeds múltiplas; matriz de oponentes; IC; exploitability/proxy; custo e regressão contra baseline congelado |
| P2 | VLM/LoRA somente em fallback | orçamento de latência, licença do modelo, erro crítico inferior ao OCR+regras e abstenção calibrada |

## Varredura plataforma por plataforma

Legenda: **acessível/parcial** inclui conteúdo, shell JavaScript ou redirecionamento útil; **limitado** inclui bloqueio, erro upstream ou rota não renderizada. “Sem ativo retido” significa apenas que a busca não trouxe evidência forte o bastante para este projeto; não prova ausência no acervo.

### Seção 1 — plataformas gerais e multidisciplinares

| Plataforma | Acesso observado | Busca e conclusão |
|---|---|---|
| [Advance — SAGE](https://advance.sagepub.com/) | Limitado: 403. | Fallback site-specific; sem ativo técnico retido. |
| [AIJR Preprints](https://preprints.aijr.org/) | Acessível; busca e aviso de conteúdo não revisado. | Busca ampla; sem ativo de poker/visão retido. |
| [AiraXiv](https://airaxiv.com/) | Acessível; trilhas AI-generated/human e AI review. | Busca ampla; nenhum peso/dataset útil. |
| [ARPHA Preprints](https://preprints.arphahub.com/) | Limitado: 403. | Fallback; sem evidência retida. |
| [Authorea](https://www.authorea.com/) | Limitado: 403. | Fallback; sem evidência retida. |
| [Cambridge Open Engage](https://www.cambridge.org/engage/) | Acessível; beta, 3.801 conteúdos vivos observados e API pública. | Busca ampla; sem ativo direto. |
| [EasyChair Preprints](https://easychair.org/publications/preprints) | Índice acessível. | Busca ampla; nenhum candidato de alta relevância. |
| [F1000Research](https://f1000research.com/) | Portal/pesquisa acessíveis. | Sinal indireto apenas; sem ativo retido. |
| [Figshare](https://figshare.com/) | Portal e API acessíveis. | API: poker 159, poker hand 7; eram sobretudo figuras, não corpus novo. |
| [HAL](https://hal.science/) | Landing parcial; API oficial funcional. | Oito consultas; MRPH foi o principal novo candidato visual, colocado em quarentena. |
| [Jxiv](https://jxiv.jst.go.jp/) | Portal oficial JST acessível após redirecionamento. | Três consultas em japonês/inglês; nenhum ativo direto de poker. Jxiv.1364 foi apenas sinal arquitetural indireto de OCR local. |
| [Octopus](https://www.octopus.ac/) | Portal acessível. | Busca ampla; sem ativo relevante. |
| [OpenReview](https://openreview.net/) | Portal e API v2 acessíveis. | Self-play Big 2 e Generals.io retidos como hipóteses não reproduzidas. |
| [OSF Preprints](https://osf.io/preprints/) | Shell JavaScript; API funcional. | Quatro títulos com poker, nenhum técnico; nenhum ativo direto. |
| [Preprints.org](https://www.preprints.org/) | Conteúdo pesquisável. | Taxonomia self-play/ISMCTS retida como survey não revisado. |
| [PubPub](https://www.pubpub.org/) | Portal acessível. | Busca ampla; sem ativo direto. |
| [Qeios](https://www.qeios.com/) | Portal acessível. | Busca ampla; sem evidência técnica retida. |
| [Research Square](https://www.researchsquare.com/) | Portal acessível. | Busca ampla; sem ativo direto. |
| [ScienceOpen](https://www.scienceopen.com/) | Limitado: 403. | Fallback; sem evidência retida. |
| [SSRN](https://www.ssrn.com/) | Homepage 403; páginas específicas acessíveis via índice, sem bypass. | MCTS multiagente de baixa força; restrições TDM/AI nas páginas Cell Press. |
| [Synthical](https://synthical.com/) | Portal acessível. | Busca ampla; sem evidência retida. |
| [viXra](https://www.vixra.org/) | Acessível; 45.768 eprints e aviso de não endosso observados. | Nada retido por baixa força/ausência de artefato verificável. |
| [WikiJournal Preprints](https://en.wikiversity.org/wiki/WikiJournal_Preprints) | Página acessível. | Busca ampla; nenhum candidato técnico. |
| [Zenodo](https://zenodo.org/) | Portal e API acessíveis. | PHH v3 é o ativo mais forte para regras/replay/modelagem. |

### Seção 2 — matemática, computação, engenharia e tecnologia

| Plataforma | Acesso observado | Busca e conclusão |
|---|---|---|
| [CERN Document Server](https://cds.cern.ch/) | Acessível. | Busca ampla; sem candidato direto. |
| [Cryptology ePrint Archive](https://eprint.iacr.org/) | Limitado; abertura falhou e robots.txt bloqueou busca. | Nenhum contorno tentado; sem sinal relevante. |
| [ECCC](https://eccc.weizmann.ac.il/) | Acessível. | Busca ampla; sem ativo de poker/visão. |
| [ECSarXiv](https://ecsarxiv.org/) | Redireciona ao shell OSF. | Busca ampla; sem candidato. |
| [engrXiv](https://engrxiv.org/) | Acessível. | Busca ampla; nenhum ativo retido. |
| [Optimization Online](https://optimization-online.org/) | Acessível. | Nenhum algoritmo diretamente acionável encontrado. |
| [TechRxiv](https://www.techrxiv.org/) | Limitado: erro no cliente. | Fallback; sem evidência retida. |

### Seção 3 — biologia, medicina, saúde, química e esporte

| Plataforma | Acesso observado | Busca e conclusão |
|---|---|---|
| [Beilstein Archives](https://www.beilstein-archives.org/xiv/) | Acessível; busca fulltext/título/resumo/keyword. | Sem ativo relevante. |
| [BioHackrXiv](https://biohackrxiv.org/) | Limitado pelo cliente. | Fallback; nenhum candidato. |
| [bioRxiv](https://www.biorxiv.org/) | Homepage 403; páginas primárias específicas acessíveis via índice. | SAM/YOLO e PolliCrop eram sinais indiretos; nenhum ativo de poker. |
| [Cell Press Sneak Peek](https://www.ssrn.com/index.cfm/en/cell-press-sneak-peek/) | Acessível; 11.432 itens observados. | Direitos TDM/AI reservados; metadados apenas, sem ingestão autorizada. |
| [ChemRxiv](https://chemrxiv.org/) | Dashboard/artigos acessíveis. | 3D2SMILES e Closed-Loop retidos por estrutura, ensemble e quality gates. |
| [EyeXiv](https://eyexiv.org/) | Limitado: erro de resolução/acesso. | Fallback; sem candidato. |
| [FocUS Archive](https://osf.io/preprints/focusarchive) | Shell OSF acessível. | Busca ampla; sem evidência retida. |
| [JMIR Preprints](https://preprints.jmir.org/) | Portal acessível; alguns ativos restritos. | Validação real-world/certainty apenas como metodologia indireta. |
| [medRxiv](https://www.medrxiv.org/) | Homepage falhou; páginas específicas indexadas acessíveis. | VLM para telas e external shift/calibration retidos como evidência metodológica. |
| [MitoFit](https://www.mitofit.org/index.php/MitoFit_Preprints) | Limitado: erro de acesso. | Fallback; nenhum candidato. |
| [Preprints with The Lancet](https://www.thelancet.com/preprints) | Limitado: erro/bloqueio. | Fallback; sem ativo transferível. |
| [PsyArXiv](https://psyarxiv.com/) | Redireciona ao shell OSF. | Busca ampla; sem candidato técnico direto. |
| [SportRxiv](https://sportrxiv.org/) | Acessível após redirecionamento. | Pose por webcam era indireta; nada para implementação imediata. |
| [Surgery Open Science First Look](https://www.ssrn.com/index.cfm/en/surgery-open-science-first-look/) | Limitado: rota indisponível. | Fallback; sem candidato. |
| [Therapoid](https://therapoid.net/) | Limitado: redirecionamento sem acervo verificável. | Fallback; sem candidato. |
| [VeriXiv](https://verixiv.org/) | Shell/página parcial. | Busca ampla; nenhum ativo retido. |

### Seção 4 — Terra, ambiente, agricultura, ecologia e paleontologia

| Plataforma | Acesso observado | Busca e conclusão |
|---|---|---|
| [agriRxiv](https://agrirxiv.org/) | Limitado: 502/erro upstream. | Fallback; sem candidato. |
| [Earth-prints](https://www.earth-prints.org/) | DSpace acessível. | Busca ampla; nenhum item direto de poker. |
| [EarthArXiv](https://eartharxiv.org/) | Landing mínima; registros específicos acessíveis. | Workflow de scans retido por provenance, dewarping, calibração e split agrupado. |
| [EcoEvoRxiv](https://www.ecoevorxiv.com/) | Limitado: erro SSL/acesso. | Fallback; sem candidato. |
| [ESS Open Archive](https://essopenarchive.org/) | Limitado: erro/bloqueio. | Fallback; sem candidato. |
| [Organic Eprints](https://www.orgprints.org/) | Homepage limitada; páginas específicas indexadas acessíveis. | Iluminação controlada/features simples apenas como transferência metodológica. |
| [PaleorXiv](https://paleorxiv.org/) | Limitado no redirecionamento OSF. | Fallback; sem candidato. |

## Separação final: evidência, inferência e decisão

**Evidência observada:** metadados, contagens de API, páginas primárias, hashes dos três arquivos pequenos do MRPH, distribuição do CSV e afirmações claramente atribuídas aos próprios preprints/registros.

**Inferência de engenharia:** split por grupo, decoder estrutural, quality gate, current-policy self-play, LoRA/VLM em fallback e transferência de protocolos externos. Essas propostas são hipóteses a testar, não ganhos já demonstrados no Poker Arena.

**Decisão segura hoje:** PHH v3 pode avançar para auditoria de licença e ingestão controlada; Poker Cards FMJIO pode avançar para um experimento visual isolado; MRPH permanece em quarentena; nenhum novo peso/modelo deve substituir o baseline sem teste integrado, holdout externo, calibração, latência e regressão de regras.

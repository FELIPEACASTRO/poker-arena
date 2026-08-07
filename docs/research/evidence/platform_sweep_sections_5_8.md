# Varredura auditável das plataformas — seções 5 a 8

**Data do probe:** 17 de julho de 2026, America/Sao_Paulo

**Inventário de origem:** `plataformas_concorrentes_equivalentes_arxiv (3).md`, SHA-256
`8f411d8bac4d6f0ac4103d7eb9593406bd84b758e9ecc6e28dd8bc6364a08204`.

**Escopo:** 55 de 55 plataformas; seções 5, 6, 7 e 8.
**Registro estruturado canônico:** [`platform_sweep_sections_5_8.json`](platform_sweep_sections_5_8.json)

## Resultado executivo

A varredura encontrou melhorias plausíveis de **arquitetura e avaliação**, mas não encontrou, nessas quatro seções, um peso treinado ou dataset de poker/visão com licença, proveniência e evidência suficientes para substituir os ativos atuais.

Os cinco ganhos que devem entrar no roadmap são:

1. manter estimativas probabilísticas calibráveis separadas das preferências e custos do jogador;
2. testar automação seletiva/abstenção e medir o efeito do copilot sobre acerto, override, tempo e aprendizagem;
3. não tratar timeout, sit-out, ação forçada ou decisão automática como rótulos equivalentes de preferência;
4. validar por cliente/site/tema/resolução/sessão, com calibração por grupo e intervalos bootstrap;
5. usar dados sintéticos para injetar falhas em QA, nunca para substituir o holdout humano real.

Não foi contornado robots.txt, CAPTCHA, paywall ou login. Nenhuma credencial foi usada ou exposta.

## Método e semântica das contagens

Cada URL foi aberta diretamente. O resultado foi classificado como conteúdo renderizado, redirecionamento, shell JavaScript, anti-bot/CAPTCHA, página de erro, limitação do cliente, erro upstream/timeout ou rejeição de requisição.

Em seguida foi executada uma consulta ampla `site:` em cada plataforma. As 55 consultas amplas, com muitos termos unidos por `OR`, não devolveram blocos. Isso **não demonstra ausência**: consultas estreitas posteriores recuperaram conteúdo relevante. Foram então executadas 45 consultas temáticas mais estreitas, que retornaram 172 blocos candidatos brutos. Esses 172 blocos incluem duplicatas, versões, PDFs e ruído; não são total de acervo, recall completo nem 172 achados úteis.

| Medida | Contagem observada |
|---|---:|
| Plataformas previstas / auditadas | 55 / 55 |
| Seção 5 / 6 / 7 / 8 | 18 / 17 / 8 / 12 |
| Conteúdo direto | 21 |
| Redirecionamento com conteúdo | 3 |
| Shell JS direto ou após redirecionamento | 11 |
| Anti-bot/CAPTCHA | 3 |
| Página de erro de aplicação | 4 |
| Limitação do cliente | 7 |
| Erro upstream ou timeout | 5 |
| Request rejected | 1 |
| Consultas site-specific amplas | 55 |
| Consultas estreitas de follow-up | 45 |
| Blocos candidatos brutos nos follow-ups | 172 |
| Evidências de maior sinal retidas | 15 |

## Evidência de maior sinal

### Arquitetura do copilot e decisão

| Evidência primária | O que foi observado | Inferência limitada para o Poker Arena |
|---|---|---|
| [Optimal Use of Preferences in Artificial Intelligence Algorithms — NBER w34780](https://www.nber.org/papers/w34780) | O working paper separa preferências embutidas no treino de probabilidades calibradas com preferências/custos aplicados depois. | Manter equity, fold probability e incerteza como saídas neutras; aplicar perfil de risco e utilidade somente na camada de decisão. É princípio de desenho, não ganho de poker medido. |
| [Designing Human-AI Collaboration — NBER w33949](https://www.nber.org/papers/w33949) | Estuda automação seletiva, confiança, sub-resposta humana e redução de esforço diante de previsões confiantes. | Comparar sem dica, dica com confiança/razões e abstenção. Não autoexecutar ações. O domínio original é fact-checking. |
| [Algorithmic Recommendations and Human Discretion — NBER w31747](https://www.nber.org/papers/w31747) | Avalia overrides humanos com contrafactual no mesmo limiar e encontra forte heterogeneidade entre decisores. | Registrar recomendação, confiança, ação final e desfecho; medir override por usuário/contexto. Divergência não significa automaticamente erro. |
| [Automating Automaticity — NBER w30981](https://www.nber.org/papers/w30981) | Mostra que comportamento automático pode não representar preferência e pode contaminar o algoritmo treinado nessas escolhas. | Preservar tempo, timeout, sit-out, all-in forçado e exposição à dica como flags. A aplicação a poker é inferência. |
| [AI, Human Cognition and Knowledge Collapse — NBER w34910](https://www.nber.org/papers/w34910) | Modelo teórico em que recomendações agentic podem reduzir esforço humano e aprendizagem de longo prazo. | Manter modo treino, explicações verificáveis e avaliações de aprendizagem; não copiar conclusões quantitativas para o Poker Arena. |

### Modelagem de oponente e comportamento

| Evidência primária | O que foi observado | Inferência limitada para o Poker Arena |
|---|---|---|
| [Beyond Chance? The Persistence of Performance in Online Poker — RePEc/IDEAS](https://ideas.repec.org/a/plo/pone00/0115479.html) | O registro descreve centenas de milhões de observações jogador-mão e persistência temporal de desempenho. | Usar split temporal por jogador/sessão e medir persistência OOS. O dataset não apareceu como download licenciável; o índice não pode virar corpus de treino. |
| [On loss aversion, level-1 reasoning, and betting — RePEc/IDEAS](https://ideas.repec.org/a/spr/jogath/v44y2015i1p113-133.html) | O resumo relata betting persistente e um modelo baseado em experiências passadas semelhantes mais framing. | Challenger: memória recência×contexto e mistura de níveis de raciocínio, sempre comparada ao prior neutro. Sem código/pesos/ganho reproduzido. |
| [Learning to apply theory of mind — PhilArchive](https://philarchive.org/rec/VERLTA) | Em jogo estratégico de informação imperfeita, a maioria não adquiriu ToM de segunda ordem apenas por repetição; alguns já a usavam. | Começar com modelo simples e heterogêneo; ToM de ordem alta é challenger, não pressuposto universal. O jogo estudado não é poker. |
| [A Computational Model of Bounded Rationality — PhilArchive](https://philarchive.org/archive/AUGACM) | Usa autômatos finitos/Moore para racionalidade limitada em jogos repetidos. | Baseline finito-state interpretável por rua pode ser testado; não há evidência de superioridade em NLHE. |

### Visão, OCR, calibração e QA

| Evidência primária | O que foi observado | Inferência limitada para o Poker Arena |
|---|---|---|
| [External validation of ML models — Gates Open Research](https://gatesopenresearch.org/articles/4-164) | Validação interna/externa por países, MAE/RMSE, resíduos, calibração-in-the-large e IC bootstrap; houve degradação fora do ambiente de desenvolvimento. | Exigir split por cliente/site/tema/resolução, curva de calibração por grupo e bootstrap por sessão. Transferir o protocolo, não o modelo clínico. |
| [Automated post-run analysis with ML — Gates Open Research](https://gatesopenresearch.org/articles/9-1/v1) | Padrão-ouro humano, CV, métricas por classe/erro e validação externa multiavaliador. | Para visão: dupla anotação/adjudicação e sensibilidade, especificidade, PPV, NPV, erro e desacordo por campo. Sinais qPCR não são screenshots. |
| [A synthetic dataset for classification models — NIHR Open Research](https://openresearch.nihr.ac.uk/articles/4-67) | Dataset didático com missingness, erros de medição, variáveis inúteis e relações realistas. | Injetar campos ausentes, OCR corrompido, duplicação e atraso em testes; nunca usar o dataset clínico para poker. |
| [Reinforcement Learning Environment for Image Color Adjustment — Sciencepaper Online](https://www.paper.edu.cn/releasepaper/content/202602-16) | Preprint modela ajuste de cor como POMDP com filtros parametrizados discretos. | Apenas challenger offline de pré-processamento, com reward CER/FAR por grupos OOD. Preprint não reproduzido; RL em produção não está justificado. |
| [Hierarchical RL for ISP Hyperparameters — Sciencepaper Online](https://www.paper.edu.cn/releasepaper/content/202503-257) | Preprint hierarquiza ajuste de ISP com CNNs e atenção. | Rejeitado: screenshots já são raster/sRGB e não expõem RAW/ISP; alto desvio de domínio. |
| [Do DNNs explain the visual system? — PhilSci-Archive](https://philsci-archive.pitt.edu/26438/) | Distingue desempenho preditivo de explicação e exige dizer o que, como e para quem o modelo explica. | Separar explicação fiel a features/cálculos de justificativa narrativa; medir fidelidade, não só legibilidade. |

### Fatores humanos e navegação

| Evidência primária | O que foi observado | Inferência limitada para o Poker Arena |
|---|---|---|
| [INTERCEPT feasibility protocol — HRB Open Research](https://hrbopenresearch.org/articles/6-43/v1) | Protocolo co-desenhado mede aceitabilidade, usabilidade, engajamento e critérios Stop/Amend/Go. | Adotar SUS, carga, compreensão, confiança, logs e critérios próprios antes de ativação ampla; não copiar thresholds clínicos. |
| [Towards Transparent and Trustworthy Prediction — ERIC](https://eric.ed.gov/?ff1=subAcademic+Achievement&id=EJ1414261&q=prediction+AND+model) | Caso de XAI com especialista como co-designer. | Incluir jogadores/treinadores na revisão das explicações e dos erros; isso não prova aumento de acurácia. |

## Varredura plataforma por plataforma

Legenda curta: **direta** = conteúdo textual renderizado; **shell** = URL respondeu, mas a aplicação dependia de JS; **limitada** = o cliente recusou ou não conseguiu abrir; **fallback** = consulta `site:` sem contornar proteção.

### Seção 5 — sociais, economia, direito, educação e políticas públicas

| Plataforma | Acesso observado | Busca e relevância | Evidência versus inferência |
|---|---|---|---|
| [AgEcon Search](https://ageconsearch.umn.edu/) | Direta; busca por campo/avançada; 214.130 registros declarados. | Busca nativa descoberta + fallback; risco, teoria dos jogos, decisão — média. | Três blocos candidatos; útil para features comportamentais, não corpus de poker. |
| [APSA Preprints](https://preprints.apsanet.org/engage/apsa/public-dashboard) | Direta; busca, Browse, API pública; aviso beta; 1.270 conteúdos vivos. | Treze blocos em follow-up; informação incompleta, reputação, repetição — média. | Conceitos úteis a histórico/incerteza; preprints não viram algoritmos prontos. |
| [Bepress Legal Repository](https://law.bepress.com/) | Direta, mas erro de template `CANNOT FIND FILE` na busca. | Browse + fallback; gambling law/governança — baixa. | Nenhum ativo técnico. |
| [CEPR Discussion Papers](https://cepr.org/publications/discussion-papers) | Direta; busca; mais de 20 mil papers e mais de mil/ano declarados. | Follow-up não devolveu bloco; AI/risk — baixa-média. | Zero top-k não prova ausência. |
| [CESifo Working Papers](https://www.cesifo.org/en/publications/working-papers) | Limitada: URL marcada como não segura pelo cliente. | Fallback; economia comportamental — baixa-média. | Cobertura inconclusiva. |
| [CrimRxiv](https://www.crimrxiv.com/) | Direta; navegação e pesquisa. | Deception/comportamento adversarial — baixa-média; sem candidato útil. | Pode inspirar taxonomia, não modelo. |
| [EconStor](https://www.econstor.eu/) | Direta; DSpace com busca. | Quatro blocos em follow-ups; Bayesian learning/opponent beliefs — média. | Baseline de crenças/recência é hipótese, não ganho provado. |
| [EdArXiv](https://edarxiv.org/) | Redirecionou para [OSF](https://osf.io/preprints/edarxiv/); shell vazio. | Fallback; educação — baixa. | Possível desenho pedagógico, sem ativo retido. |
| [ERIC](https://eric.ed.gov/) | Homepage 502 no cliente; registros individuais indexados. | Quatro blocos; XAI/co-design/human-AI — média. | Co-design é aplicável; stack técnico não é transferível automaticamente. |
| [Federal Reserve FEDS](https://www.federalreserve.gov/econres/feds/index.htm) | Direta, oficial. | Econometria/incerteza — baixa; nada retido. | Sem mudança de stack. |
| [IMF Working Papers](https://www.imf.org/en/Publications/WP) | Limitada: URL marcada como não segura. | Fallback; risco — baixa. | Cobertura inconclusiva. |
| [IZA Discussion Papers](https://www.iza.org/publications/dp) | Direta; página IZA@LISER. | Economia experimental/risco — média. | Pode apoiar estudos de usuário; nenhum ativo de poker. |
| [MPRA](https://mpra.ub.uni-muenchen.de/) | Direta; EPrints. | Game theory/Bayesian decision — média. | Fonte de hipóteses, não benchmark. |
| [NBER Working Papers](https://www.nber.org/papers) | Direta; busca e papers acessíveis. | 33 blocos brutos em dois follow-ups; calibração, preferência e human-AI — alta. | Quatro itens de alto sinal retidos; efeito em poker ainda precisa ser testado. |
| [RePEc](https://repec.org/) | Raiz 502; [IDEAS/RePEc](https://ideas.repec.org/) acessível. | Onze blocos; poker, risco, opponent models — alta. | Metadados geram hipóteses; não são dataset ou licença. |
| [SocArXiv](https://osf.io/preprints/socarxiv/) | Shell OSF vazio. | Fallback; fatores humanos/gambling — média. | Nenhum item retido. |
| [SSOAR](https://www.ssoar.info/) | Página de erro `Oh noes!`. | Fallback; comportamento social — baixa-média. | Estado inconclusivo; sem ação. |
| [World Bank WPS](https://www.worldbank.org/en/research/brief/policy-research-working-papers) | Direta e extensa. | Decisão/qualidade de dados — baixa. | Nenhum ativo retido. |

### Seção 6 — humanidades, linguagem, informação, mídia e filosofia

| Plataforma | Acesso observado | Busca e relevância | Evidência versus inferência |
|---|---|---|---|
| [ART-Dok](https://archiv.ub.uni-heidelberg.de/artdok/) | Página `Oh noes!`. | Fallback; visual culture — baixa. | Nenhum item. |
| [BodoArXiv](https://bodoarxiv.wordpress.com/) | Direta; WordPress. | Navegação + fallback — baixa. | Nenhum item. |
| [CrossAsia Repository](https://crossasia-repository.ub.uni-heidelberg.de/) | Limitada pelo cliente. | Regional language/OCR potencial — baixa. | Potencial não demonstrado. |
| [E-LIS](http://eprints.rclis.org/) | Redirecionou para HTTPS e retornou 502. | Retrieval/metadata — baixa. | Sem item. |
| [hprints](https://hal-hprints.archives-ouvertes.fr/) | Página HAL `Oh noes!`. | Fallback — baixa. | Sem item. |
| [Humanities Commons CORE](https://hcommons.org/core/) | Exigiu JS e verificação de robô. | Fallback — baixa. | Proteção não contornada. |
| [LingBuzz](https://ling.auf.net/lingbuzz) | Limitada pelo cliente. | Pragmatics/ToM — média. | Nenhuma evidência acionável nesta busca. |
| [LISSA](https://lissarchive.org/) | Direta. | Information science — baixa. | Sem item. |
| [MediArXiv](https://mediarxiv.com/) | Timeout do cliente. | UI/mídia — baixa-média. | Cobertura inconclusiva. |
| [MetaArXiv](https://osf.io/preprints/metaarxiv/) | Shell OSF vazio. | Métodos/reprodutibilidade — média. | Resultados OSF gerais foram descartados por não provarem pertencer ao MetaArXiv. |
| [MindRxiv](https://mindrxiv.org/) | Limitada pelo cliente. | Cognição/risco/confiança — média-alta. | Zero top-k não prova ausência. |
| [Open Anthropology Research Repository](https://www.openanthroresearch.org/) | Limitada pelo cliente. | Cultura/comportamento — baixa. | Sem conclusão. |
| [PhilArchive](https://philarchive.org/) | Direta; busca e exportação. | Treze blocos focados, muitas duplicatas; informação imperfeita/ToM — média-alta. | Dois itens retidos; challengers, não substitutos. |
| [PhilSci-Archive](https://philsci-archive.pitt.edu/) | Homepage `Request Rejected`; itens individuais indexados. | Nove blocos; explicabilidade/CV — média. | Retido princípio de fidelidade explicativa, sem modelo/peso. |
| [PropylaeumDok](https://archiv.ub.uni-heidelberg.de/propylaeumdok/) | Página `Oh noes!`. | Fallback — baixa. | Sem item. |
| [Rutgers Optimality Archive](https://roa.rutgers.edu/) | Direta; busca especializada. | Linguagem/constraints — média. | Pode informar explicações, não estratégia. |
| [Thesis Commons](https://thesiscommons.org/) | Redirecionou para [OSF](https://osf.io/preprints/thesiscommons/); shell vazio. | Poker AI/CV — média; nenhum bloco. | Zero top-k não prova ausência. |

### Seção 7 — plataformas nacionais e regionais

| Plataforma | Acesso observado | Busca e relevância | Evidência versus inferência |
|---|---|---|---|
| [AfricArXiv](https://africarxiv.org/) | Direta; link para repositório e open data. | OOD/regional/multilingual — média; nenhum candidato. | Diversidade é relevante, mas nenhum dataset visual de poker foi localizado. |
| [ChinaXiv](http://chinaxiv.org/) | Redirecionou para [HTTPS/home](https://chinaxiv.org/home.htm); busca EN/CN. | Dez blocos; CV, pipelines e calibração — média-alta. | Itens eram de astronomia/metrologia; nenhum peso/dataset de poker. Licenças variam. |
| [IndiaRxiv](https://ops.iihr.res.in/index.php/IndiaRxiv) | Direta; OJS. | ML/regional — média; nenhum bloco estreito. | Sem ativo promovível. |
| [LatArXiv](https://preprints.latarxiv.org/) | `One moment, please`; páginas indexadas acessíveis. | Categoria [Engineering and Technology](https://preprints.latarxiv.org/index.php/latarxiv/en/preprints/category/engineering-technology) declarou 35 itens; quatro blocos. | Nenhum item sobre poker/OCR de cartas; keyword ML não basta. |
| [Preprints.ru](https://preprints.ru/) | 502. | ML/multilingual — baixa-média. | Cobertura inconclusiva. |
| [RINarXiv](https://rinarxiv.lipi.go.id/lipi) | Limitada pelo cliente. | Regional/CV — média. | Pode estar legado/migrado; sem conclusão. |
| [SciELO Preprints](https://preprints.scielo.org/) | Redirecionou para [OJS](https://preprints.scielo.org/index.php/scielo); direta. | Onze blocos; human factors/IA/risco — média. | Um protocolo de reversibilidade apareceu, ainda sem validação; não virou regra do produto. |
| [Sciencepaper Online](http://www.paper.edu.cn/) | Redirecionou para [HTTPS](https://www.paper.edu.cn/); direta. | Treze blocos; CV/RL/preprocessing — média-alta. | POMDP de filtros apenas challenger; ISP hierárquico rejeitado por desvio de domínio. |

### Seção 8 — financiadores, sociedades e editoras

| Plataforma | Acesso observado | Busca e relevância | Evidência versus inferência |
|---|---|---|---|
| [AAS Open Research](https://aasopenresearch.org/) | Redirecionou para [Open Research Africa](https://openresearchafrica.org/); shell vazio. | Validação regional — baixa-média. | Tratar como migração/alias, não fonte atual separada. |
| [AMRC Open Research](https://amrcopenresearch.org/) | Redirecionou para [Health Open Research](https://healthopenresearch.org/); shell vazio. | Validação/human factors — baixa-média. | Tratar como migração/alias. |
| [Emerald Open Research](https://emeraldopenresearch.com/) | Redirecionou para CAPTCHA anti-crawl. | Fallback — baixa-média. | Proteção não contornada; sem conclusão sobre o acervo. |
| [Gates Open Research](https://gatesopenresearch.org/) | Direta; browse; 562 artigos declarados. | Quinze blocos de ML; validação/calibração/QA — alta. | Dois padrões metodológicos retidos; modelos clínicos não são transferidos. |
| [Health Open Research](https://healthopenresearch.org/) | Shell vazio, inclusive `/browse`. | ML/human factors — média; nenhum bloco. | Zero top-k não é ausência. |
| [HRB Open Research](https://hrbopenresearch.org/) | Direta; 678 artigos declarados. | Um bloco; co-design/usabilidade/Stop-Amend-Go — média-alta. | Protocolo humano aplicável; thresholds clínicos não. |
| [MNI Open Research](https://mniopenresearch.org/) | Direta. | Dois blocos; benchmark/robustez — média. | Cultura de benchmark, não transferência de neuroimagem. |
| [NIHR Open Research](https://openresearch.nihr.ac.uk/) | Direta. | Treze blocos; synthetic QA/missingness — média-alta. | Data note inspira falhas sintéticas; dataset clínico não treina poker. |
| [Open Research Africa](https://openresearchafrica.org/) | Shell vazio. | Validação regional — média; nenhum bloco. | Nenhum ativo localizado. |
| [Open Research Europe](https://open-research-europe.ec.europa.eu/) | Homepage shell; [busca](https://open-research-europe.ec.europa.eu/search) declarou 1.442 artigos. | Open peer review/reprodutibilidade — média. | Fonte metodológica; nenhum modelo de poker/CV promovível. |
| [Routledge Open Research](https://routledgeopenresearch.org/) | Shell vazio. | Human factors/open methods — baixa-média; nenhum bloco. | Nenhum ativo localizado. |
| [Wellcome Open Research](https://wellcomeopenresearch.org/) | Homepage shell; [busca](https://wellcomeopenresearch.org/search) declarou 3.883 artigos. | Datasets/validation/open review — média. | Fonte metodológica; não substitui PHH ou benchmark visual específico. |

## Registro das consultas estreitas

| Lote | Sites | Temas | Blocos brutos |
|---|---|---|---:|
| S5_T1 | AgEcon, APSA, Bepress, CEPR | poker, gambling, game theory, incerteza, risco, ML | 18 |
| S5_T2 | CrimRxiv, EconStor, ERIC, RePEc | deception, strategic decision, behavioral game theory, human-AI, XAI, poker | 18 |
| S5_T3 | RePEc, NBER, EconStor | player models, opponent beliefs, Bayesian learning, recommendations | 18 |
| S5_T4 | NBER | game theory, poker, gambling, risk, decisão | 16 |
| S6_T1 | PhilArchive, PhilSci, MindRxiv, MetaArXiv | imperfect information, bounded rationality, calibração, CV, human-AI | 18 |
| S6_T2 | PhilArchive, MindRxiv, Thesis Commons, LingBuzz | second-order ToM, strategic game, poker AI, uncertainty | 13 |
| S7_T1 | ChinaXiv, SciELO, AfricArXiv, Sciencepaper | CV, OCR, RL, game theory, calibração | 16 |
| S7_T2 | ChinaXiv, SciELO, AfricArXiv | detection, recognition, confidence, risk, cognition | 18 |
| S7_T3 | IndiaRxiv, AfricArXiv, LatArXiv, Preprints.ru | machine learning | 4 |
| S8_T1 | Gates, HRB, ORE, Wellcome | calibration, uncertainty, CV, human-AI, decision support | 1 |
| S8_T2 | Gates, ORE, Wellcome, Open Research Africa | ML, calibration, external validation, prediction | 17 |
| S8_T3 | MNI, NIHR, Routledge, Health | machine learning | 15 |

## Decisões recomendadas

### Adotar agora no desenho e nos gates

- Saída do estimador: probabilidade, incerteza e versão do modelo; preferência/custo somente no decisor.
- Log de decisão: estado, recomendação, confiança, explicação, ação final, override, latência e desfecho.
- Flags obrigatórias: ação forçada, timeout, sit-out, exposição ao copilot, street e contexto de sessão.
- Avaliação de visão/OCR: split agrupado por cliente/site/tema/resolução, métricas por campo, FAR/abstenção e bootstrap por sessão.
- Estudo humano: SUS, entendimento, carga, confiança, aprendizagem, retenção e critérios próprios Go/Amend/Stop.

### Apenas challenger controlado

- opponent model com memória recência×contexto e mistura de níveis de raciocínio;
- baseline finito-state interpretável por street;
- pequena política offline de filtros de pré-processamento, comparada um fator por vez por CER/FAR OOD.

### Rejeitar ou manter em quarentena

- qualquer ação humana como rótulo puro de preferência;
- thresholds de saúde transplantados para poker;
- RL de ISP em screenshot sRGB;
- preprint, PDF indexado ou working paper tratado como peso, dataset autorizado ou ganho reproduzido;
- promoção de modelo sem código, licença, revisão de dados, split agrupado, calibração e benchmark reproduzido.

## O que esta auditoria não prova

- Não prova que uma plataforma sem bloco retornado não contém material relevante.
- Não prova que um artigo indexado tem código, dados ou licença reutilizável.
- Não reproduziu nenhum treinamento ou número de qualidade remoto.
- Não comparou os challengers sugeridos contra o baseline do Poker Arena.
- Não converteu abstracts, preprints ou métricas de outro domínio em alegações de eficácia no poker.

Assim, a conclusão fail-closed é: **as fontes das seções 5–8 melhoram principalmente o protocolo de decisão, fatores humanos e validação; nenhum ativo remoto deve ser promovido ao runtime sem experimento local versionado e gates existentes.**

# Varredura das plataformas — seções 9 a 12

**Snapshot:** 2026-07-17, `America/Sao_Paulo`  
**Escopo:** 47/47 plataformas do arquivo `plataformas_concorrentes_equivalentes_arxiv (3).md`  
**Evidência estruturada:** [`platform_sweep_sections_9_12.json`](platform_sweep_sections_9_12.json)

## Resultado executivo

Todas as 47 URLs foram sondadas por acesso público e somente leitura. A varredura encontrou quatro mudanças/limitações arquiteturais relevantes:

1. **Papers with Code não é mais um serviço independente no endpoint testado:** tanto a homepage quanto a antiga rota `/api/v1/papers` redirecionam para Hugging Face Papers. Uma nova integração não deve depender da API histórica do PWC.
2. **CORE, DBLP, OpenAlex, Crossref, Semantic Scholar bulk e HF Papers são as rotas programáticas mais úteis** para esta solução. Cada uma cobre uma etapa diferente; nenhuma deve ser tomada como fonte única.
3. **BASE ficou inacessível ao cliente de auditoria:** homepage e busca exibiram `UniBi Security Check`; a API retornou `Access denied` para IP/user-agent. Isso é “não medido”, não zero.
4. **Os resultados brutos têm falsos positivos severos.** Em “playing card recognition”, OpenAlex trouxe um survey de event-based vision, Crossref trouxe face recognition e HF trouxe card-based games. Logo, volume/posição não é evidência de aderência; reranking e revisão de protocolo são obrigatórios.

As evidências técnicas mais úteis recuperadas foram [DeepStack](https://doi.org/10.1126/science.aam6960), [AlphaHoldem](https://dblp.org/rec/conf/aaai/ZhaoYLLX22), [DecisionHoldem](https://huggingface.co/papers/2201.11580), [Model-Based Opponent Modeling](https://huggingface.co/papers/2108.01843), [On Calibration of Modern Neural Networks](https://huggingface.co/papers/1706.04599), um trabalho CNN específico de [detecção/classificação de cartas](https://www.semanticscholar.org/paper/05270aad7e4c67772961a0db34125b2f90482562) e um baseline clássico [SIFT/counting](https://core.ac.uk/download/270215513.pdf). Esses registros justificam **leitura e replicação**, não adoção automática.

## Método e interpretação

- Foi feito `GET` público sem login, paywall, credenciais, evasão de robots ou contorno de controles.
- Redirecionamentos normais foram seguidos. `403`, `405`, `202` e security checks descrevem este cliente e instante; não provam que uma pessoa não consiga navegar.
- As sete consultas comuns foram: `poker artificial intelligence`, `imperfect information games`, `self play reinforcement learning games`, `opponent modeling games`, `playing card recognition computer vision`, `optical character recognition deep learning` e `probability calibration neural networks`.
- Contagens são o valor reportado pelo índice naquele instante. Semânticas e universos são diferentes; **não se comparam counts entre provedores**.
- No HF Papers, `120` é quantidade devolvida, pois a resposta não expõe total. No Semantic Scholar bulk, a ordenação não é por relevância. No Europe PMC, foi usada frase exata em título/resumo.
- O JSON registra cada URL exata de consulta, contagem, ID/DOI retornado e aviso de precisão.

## 9. Repositórios institucionais e autoarquivamento

| Plataforma | Acesso observado | Capacidade/API observada | Relevância inferida para Poker Arena |
|---|---|---|---|
| Academia.edu | `403` | Rede acadêmica; nenhuma API pública estável verificada | Baixa-média; somente descoberta manual, sem ingestão automática |
| DASH/Harvard | Homepage `405`; [REST](https://dash.harvard.edu/server/api) `200`; [OAI-PMH](https://dash.harvard.edu/server/oai/request?verb=Identify) `200` | DSpace 8.0, teses/artigos, REST HAL e OAI | Média; fonte de teses/relatórios com licença e versão verificadas |
| DSpace@MIT | Homepage `405`; [REST](https://dspace.mit.edu/server/api) `200`; [OAI-PMH](https://dspace.mit.edu/server/oai/request?verb=Identify) `200` | DSpace 8.2, teses, artigos, software | Média-alta; boa fonte institucional para IA/CV/jogos |
| LSE Research Online | `200` | EPrints; [OAI-PMH](https://researchonline.lse.ac.uk/cgi/oai2?verb=Identify) `200` | Média; teoria dos jogos/economia comportamental |
| Open Science Framework | `200` | Projetos, arquivos, datasets, pré-registros, preprints; [JSON:API v2](https://api.osf.io/v2/) `200` | Média-alta; dados/protocolos/resultados negativos, sempre com provenance gate |
| ResearchGate | `403` | Rede acadêmica; nenhuma API pública estável verificada | Baixa-média; pista manual para versão canônica, não corpus |

## 10. Serviços encerrados, migrados ou legados

| Plataforma | Acesso/status observado | Capacidade/API observada | Relevância inferida |
|---|---|---|---|
| Arabixiv | `200`, redireciona ao [Zenodo](https://zenodo.org/communities/arabixiv/about) | Comunidade Zenodo; [API](https://zenodo.org/api/communities/arabixiv) `200` | Baixa para poker; média para eventual OCR árabe |
| CogPrints | `200`, redireciona ao arquivo web de Southampton | Arquivo estático; OAI legado testado retornou `404` | Baixa; contexto histórico de cognição |
| ESSOAr | Destino `403`, redirecionado a `essopenarchive.org` | Preprints Earth/space; API não verificada | Muito baixa; domínio desalinhado |
| Frenxiv | `200`; busca/submissão visíveis; página contém sinais datados de 2020 | Preprints multidisciplinares, conta OSF; API específica não confirmada | Baixa; confirmar operação antes de integrar |
| INA-Rxiv | `200`; [provider OSF](https://api.osf.io/v2/preprint_providers/inarxiv/) `200` informa encerramento | Leitura de registros preservados | Baixa |
| LawArXiv | `200`; [provider OSF](https://api.osf.io/v2/preprint_providers/lawarxiv/) informa fim de submissões | Leitura de preprints jurídicos | Muito baixa |
| MarXiv | `200`; [provider OSF](https://api.osf.io/v2/preprint_providers/marxiv/) informa submissões fechadas | Leitura de preprints marinhos | Muito baixa |
| mp_arc | Timeout após 25 s | Arquivo de física matemática; API não verificada | Muito baixa; não priorizar |
| Nature Precedings | `200`; coleção declara cobertura [2007–2012](https://www.nature.com/npre/) | Busca/browse, DOI e PDFs preservados | Muito baixa; arquivo histórico de life science |
| NutriXiv | `200`; [provider OSF](https://api.osf.io/v2/preprint_providers/nutrixiv/) informa fim de novas submissões | Leitura de preprints de nutrição | Muito baixa |
| PeerJ Preprints | `403` ao cliente; PDFs históricos ainda indexados | Arquivo legado; API não verificada | Baixa; resolver metadados via Crossref/CORE |

## 11. Buscadores, agregadores e índices

| Plataforma | Acesso observado | Capacidade/API observada | Relevância inferida |
|---|---|---|---|
| alphaXiv | `200`, redireciona a `www.alphaxiv.org` | Descoberta, resumos e discussão de arXiv; sem API pública estável verificada | Média; triagem, nunca fonte primária |
| ar5iv | `200` | HTML5 por ID arXiv, por exemplo `/html/{id}` | Alta como ferramenta de leitura/extração; não é índice |
| BASE | `200` com Security Check; API JSON diz `Access denied` | Agregador OA; API/OAI controlados por acesso/IP | Média-alta se houver autorização oficial; nesta execução, não medido |
| CORE | `200`; [API v3](https://api.core.ac.uk/v3/search/works?q=poker&limit=2) `200` | Metadados, texto completo, downloads e busca | Alta para literatura cinzenta/full text, com dedupe/licença |
| Crossref | `200`; [REST/Swagger](https://api.crossref.org/swagger-ui/index.html) `200` | DOI, metadados, referências, filtros e cursores | Alta para resolução de IDs/versões; baixa como ranker semântico |
| DBLP | `200`; [search API](https://dblp.org/search/publ/api?q=poker&format=json&h=2) `200` | Bibliografia CS, IDs estáveis, DOI/arXiv | Alta; melhor precisão para IA/CV |
| Dimensions | `202`, redireciona à autenticação | Papers/grants/patents/datasets; [DSL](https://docs.dimensions.ai/dsl/) sob acesso | Média; landscape, sem integração nesta auditoria |
| EconPapers | `200` | RePEc, working papers e artigos; sem JSON geral verificado | Média para jogos/economia |
| Europe PMC | `200`; [REST](https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=imperfect%20information&format=json&pageSize=2) `200` | Biomedicina, preprints, full text, citações | Baixa para poker; média para metodologia/calibração |
| Google Scholar | `200` | Busca ampla e citation chaining; sem API pública oficial | Alta manual, inadequada para pipeline automatizado |
| Hugging Face Papers | `200`; redireciona à data atual; [search endpoint](https://huggingface.co/api/papers/search?q=poker) `200` | Daily/trending, busca, upvotes, IDs arXiv | Alta para novidade, com forte reranking |
| IDEAS/RePEc | `200` | RePEc, autores, séries, citações/rankings | Média para teoria de jogos/economia |
| INSPIRE HEP | `200`; [REST](https://inspirehep.net/api/literature?q=poker&size=1) `200` | Física HEP, citações/dados | Muito baixa |
| Internet Archive Scholar | `200` | Busca/preservação; API atual não verificada nesta auditoria (documentação Fatcat histórica sofreu timeout) | Média para recuperar trabalhos órfãos; validar versão/licença |
| Lens | `200` | Patentes e literatura; [API](https://docs.api.lens.org/) sob conta/solicitação | Média para patents de OCR/visão |
| NASA ADS | `202`, shell JS | Astronomia/física; [API](https://ui.adsabs.harvard.edu/help/api/) exige token | Muito baixa |
| OpenAIRE Explore | `200` | Outputs, datasets, software, projetos; [Graph API V3](https://graph.openaire.eu/docs/apis/graph-api/overview/) | Média-alta para datasets/software EU |
| OpenAlex | `200`; [REST](https://api.openalex.org/works?search=poker&per-page=1) `200` | Grafo, citations, topics, keywords e snapshot | Alta para discovery/dedupe; busca ampla exige filtro |
| OpenCitations | `200` | Grafo de citações; [REST/SPARQL](https://opencitations.net/index/api/v2) | Média-alta depois de obter DOI; não é busca temática |
| Papers with Code | `200`, redireciona a [HF Papers](https://huggingface.co/papers/trending) | API histórica também redireciona; sem serviço independente observado | Alta como legado; não criar dependência viva |
| PhilPapers | `403` | Filosofia; API não verificada | Muito baixa |
| PubMed | Homepage `403`; [E-utilities](https://eutils.ncbi.nlm.nih.gov/entrez/eutils/) `200` | Índice biomédico/MeSH | Baixa para poker; média para calibração em alto risco |
| Scilit | `200` | Literatura/preprints/métricas; API anônima não verificada | Média-baixa; segunda opinião de metadados |
| SciRate | `403` | Ratings/comentários sobre arXiv; API pública estável não verificada | Baixa-média; sinal social, não qualidade |
| Semantic Scholar | `200`; relevance API rate-limited; [bulk](https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=poker%20artificial%20intelligence&fields=title,year,url,citationCount,externalIds) `200` | Grafo, IDs, citations, datasets e busca bulk | Alta; cache/rate limit/reranking obrigatórios |

## 12. Diretórios de repositórios

| Plataforma | Acesso observado | Capacidade/API observada | Relevância inferida |
|---|---|---|---|
| ASAPbio directory | `200` | Lista de servidores e políticas; API não verificada | Média para ampliar inventário, não para conteúdo |
| DOAPR | `200`; rota presumida `/server/api` retornou `404` | Diretório COAR, browse/search; nenhuma API inferida | Média para descobrir fontes |
| OpenDOAR | `200`, redireciona a `opendoar.ac.uk`; endpoint de retrieve retornou `api-key absent` | Diretório curado; API exige chave | Média-alta para localizar OAI/DSpace/EPrints |
| ROAR | HTTP→HTTPS `200`; [OAI-PMH](https://roar.eprints.org/cgi/oai2?verb=Identify) `200` | Registry EPrints, registros/gráficos | Média; reprobe de cada registro necessário |
| SPI-Hub | `200` | Browse de servidores e políticas; API não verificada | Média para governança/status, não corpus |

## Contagens reproduzíveis

As consultas exatas e URLs completas estão no JSON. `HF=120` significa apenas `returned_count`; `—` significa não medido, nunca zero.

| Tema | OpenAlex | Crossref | Semantic Scholar bulk | DBLP | CORE | HF Papers | Europe PMC frase exata |
|---|---:|---:|---:|---:|---:|---:|---:|
| Poker + IA | 5.166 | 1.335.608 | 215 | 7 | 217 | 120 retornados | 0 |
| Informação imperfeita | 60.826 | 2.866.464 | 1.784 | 261 | 2.144 | 120 retornados | 8 |
| Self-play + RL | 61.234 | 4.065.627 | 423 | 6 | 293 | 120 retornados | 0 |
| Opponent modeling | 67.018 | 1.269.603 | 2.137 | 15 | 197 | 120 retornados | 0 |
| Playing-card vision | 48.934 | 3.278.314 | 23 | 0 | 23 | 120 retornados | 0 |
| OCR | 39.507 | 4.757.774 | 1.387 | 14 | 425 | 120 retornados | 0 |
| Calibração | 124.113 | 2.172.916 | 769 | 2 | 319 | 120 retornados | 0 |

Interpretação rigorosa:

- Crossref `query.bibliographic` pontua tokens em metadados bibliográficos e devolve universos enormes; serve para resolução/recall, não para estimar literatura realmente aderente.
- OpenAlex pesquisou texto/metadados com ranking de relevância, mas os falsos positivos observados mostram que filtros de título, conceito e revisão humana continuam necessários.
- Semantic Scholar bulk produz contagem e lote por matching de título/abstract, mas não é ordenado por relevância. O endpoint de relevance devolveu `429` em 6/7 tentativas; isso foi preservado como evidência.
- DBLP foi muito mais seletivo: 7 resultados para poker+IA e 15 para opponent modeling, mas zero para a frase específica de card recognition.
- CORE localizou literatura cinzenta e texto completo, incluindo duplicata do mesmo trabalho SIFT; deduplicação não é opcional.
- Europe PMC confirma desalinhamento de domínio para frases exatas; os zeros não significam ausência de métodos genéricos de OCR/calibração na biomedicina.

### Plataformas sem contagem válida

- **BASE:** busca web serviu Security Check; API informou `Access denied`. Não houve contorno.
- **Papers with Code:** antiga API devolveu HTML do HF Papers após redirect; buscas foram feitas no HF Papers.
- **arXiv Atom:** sete consultas respeitando intervalo superior a 3 s resultaram em quatro `429` e três timeouts; nenhuma contagem foi inventada.
- **Google Scholar, Dimensions, Lens, Academia.edu, ResearchGate:** não houve scraping/login/API privada.

## Evidências primárias com maior potencial

| Evidência | ID estável | O que de fato sustenta | O que não sustenta |
|---|---|---|---|
| DeepStack | DOI [`10.1126/science.aam6960`](https://doi.org/10.1126/science.aam6960), OpenAlex `W2574978968` | Continual re-solving/value functions em heads-up no-limit | Transferência automática a 6-max, UI real ou opponent adaptation |
| AlphaHoldem | DOI [`10.1609/aaai.v36i4.20394`](https://doi.org/10.1609/aaai.v36i4.20394), DBLP `conf/aaai/ZhaoYLLX22` | Referência de RL end-to-end em HUNL | Superioridade no protocolo atual sem reprodução |
| DecisionHoldem | arXiv [`2201.11580`](https://huggingface.co/papers/2201.11580) | Safe depth-limited solving com diversidade de oponentes | Robustez a jogadores 6-max adaptativos sem teste |
| Model-Based Opponent Modeling | arXiv [`2108.01843`](https://huggingface.co/papers/2108.01843) | Separar modelo do oponente e política | Exploitation seguro sem medir exploitability/shift |
| Consistent Opponent Modeling | arXiv [`2508.17671`](https://dblp.org/rec/journals/corr/abs-2508-17671) | Candidato recente específico de imperfect-information games | Aplicação a oponentes não estacionários; o título declara static opponents |
| On Calibration of Modern Neural Networks | arXiv [`1706.04599`](https://huggingface.co/papers/1706.04599) | Temperature scaling como baseline pós-hoc | Calibração OOD, por classe e temporal sem novos testes |
| Playing-card CNN 2024 | DOI [`10.1109/ICEMPS60684.2024.10559365`](https://doi.org/10.1109/ICEMPS60684.2024.10559365) | Um baseline específico de detecção/classificação de cartas | Robustez em screenshots; só 1 citação foi reportada no snapshot |
| Playing-card SIFT 2017 | CORE [`75580422`](https://core.ac.uk/download/270215513.pdf) | Baseline clássico SIFT/counting | Competitividade atual; apareceu duplicado no CORE |

## Ações recomendadas

1. **P0 — pipeline em camadas:** DBLP/HF/OpenAlex para candidatos; Crossref para DOI/versão; Semantic Scholar/OpenCitations para citation chasing; CORE/OSF/DSpace para full text/dados.
2. **P0 — rastreabilidade:** persistir query, data, provedor, contagem bruta, IDs, licença, checksum e decisão de inclusão. Não comparar counts entre índices.
3. **P0 — reranking do projeto:** pontuar escopo NLHE, 2–9 jogadores, observabilidade disponível, código/pesos, licença, protocolo, split por fonte/grupo e existência de baseline reproduzível.
4. **P1 — matriz de replicação de estratégia:** DeepStack, AlphaHoldem, DecisionHoldem e Model-Based Opponent Modeling, cada um em protocolo isolado e sem extrapolar HUNL para 6-max.
5. **P1 — visão:** manter CNN 2024 e SIFT 2017 somente como baselines. Promoção exige screenshots reais, grupos independentes, mAP50-95/per-class, OCR CER, NLL/Brier/ECE e teste OOD.
6. **P1 — calibração:** temperature scaling em validation set independente, comparado com NLL, Brier, ECE adaptativa, reliability diagrams e cortes por site/stake/tema de UI.
7. **P2 — fontes controladas:** solicitar BASE/OpenDOAR por via oficial somente se a literatura cinzenta justificar. Não contornar security checks nem automatizar Academia/ResearchGate/Scholar.
8. **P2 — migração PWC:** remover Papers with Code como dependência ativa; resolver artefatos por arXiv/DOI, repositório de código canônico e HF model/dataset cards.

## Limitações

- Este é um snapshot mutável de 2026-07-17.
- Nenhuma credencial privada foi usada ou registrada.
- Bloqueios do cliente automático não equivalem a indisponibilidade humana.
- O trabalho auditou descoberta/metadados; não baixou, executou ou promoveu modelos/datasets.
- Os primeiros resultados foram preservados para mostrar a precisão real do índice, inclusive falsos positivos. A seleção científica final exige leitura completa, licença e reprodução.

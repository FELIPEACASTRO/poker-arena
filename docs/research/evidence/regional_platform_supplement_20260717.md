# Suplemento regional — Ásia, Canadá, Rússia e Índia

**Snapshot:** 17 de julho de 2026.  
**Receipt estruturado:** [regional_platform_supplement_20260717.json](regional_platform_supplement_20260717.json).

Este suplemento amplia, sem substituir, a auditoria das 156 plataformas do anexo. Foram usadas
consultas públicas em inglês, japonês, chinês e russo sobre poker, jogos de informação imperfeita,
NFSP/CFR/RL, modelagem de oponente, visão/OCR, calibração, datasets, código e pesos. Bloqueio,
erro ou top-k vazio é **inconclusivo**, não ausência. Nenhum login, CAPTCHA ou restrição foi
contornado.

## Achados que mudam o roadmap

| Região | Evidência primária | O que entra no projeto | Limite |
|---|---|---|---|
| Japão | [NFSP sem dados de exploração na memória supervisionada](https://www.jstage.jst.go.jp/article/pjsai/JSAI2018/0/JSAI2018_1N301/_article/-char/en) | registrar origem behavior-policy/exploração por transição e testar a exclusão no NFSP formal | Leduc, estudo curto de 2018; não copiar `epsilon=0.1` para NLHE |
| Canadá | [AIVAT, AAAI 2018](https://ojs.aaai.org/index.php/AAAI/article/view/11481) | challenger de redução de variância depois que chance history, política conhecida e value estimate forem verificáveis | não é implementável honestamente sobre o estado atual incompleto |
| Canadá | [CFR+ do CPRG](https://poker.cs.ualberta.ca/cfr_plus.html) | referência independente BSD para HULHE isolado | não valida no-limit multiplayer nem o motor local |
| Rússia | [tese HSE sobre LLMs e poker](https://www.hse.ru/en/edu/vkr/1047837931) | hipótese a refutar/reproduzir | graduação; sem código/dados/protocolo/IC imutáveis no receipt |
| Rússia | [segunda tese HSE com DDQN/DeepSeek](https://www.hse.ru/en/edu/vkr/1047501606) e [repositório](https://github.com/romanhse/PyPokerEngine_diploma) | catálogo de testes negativos para crédito temporal, avaliação congelada e pareamento | checkpoint e logs existem, mas o protocolo/código não sustentam promoção |
| Índia | [slides IIT Kanpur de opponent modelling](https://cse.iitk.ac.in/users/cs365/2013/submissions/~ayujain/cs365/project/slides.pdf) | baseline histórico de reponderação Bayes/frequência | sem implementação completa, calibração ou holdout |
| Índia | [ISBA do IIT Bombay](https://rnd.iitb.ac.in/node/2258) | decomposição Monte Carlo + rede Bayes + regras como challenger conceitual | patente de Rummy; sem peso, dataset ou benchmark aberto de poker |

O registro oficial canadense do [PHH v3](https://zenodo.org/records/17136841) também corrige uma
ambiguidade material: as 21.605.687 mãos humanas NLHE são logs anonimizados de **1 a 23 de julho
de 2009**. É a maior coleção histórica encontrada, mas não representa comportamento contemporâneo.
Qualquer opponent model treinado nela exige holdout moderno, autorizado, externo e temporal.

## Cobertura sem ativo promovível

- ChinaXiv e Sciencepaper Online: itens de CV/RL/calibração fora do domínio de screenshots/poker;
- KoreaScience: nenhum resultado de alto sinal retido na consulta delimitada;
- IndiaRxiv: nenhum bloco estreito promovível;
- CyberLeninka: material genérico de RL/visão/game AI, sem artefato de poker reproduzível;
- Preprints.ru: `502`, portanto cobertura inconclusiva;
- MNI Open Research/NRC Canada: métodos de validação e calibração em outros domínios, sem modelo
  transferível.

## Auditoria estática do ativo russo aberto

O repositório ligado pela segunda tese HSE foi clonado somente para leitura e fixado no commit
`52fa10e7965e4351eb98a6532f67c38e4e50873e` (19 de maio de 2025). O checkpoint
`dueling_ddqn_model_7.pt` tem SHA-256
`687b16de0b41c967a9dec52c8ac37556955c9f4e48819e1fdee93979539fd2fa`. Esses identificadores
provam qual snapshot foi inspecionado; não provam qualidade ou licença dos pesos.

Falhas que impedem reutilização:

- o notebook `CFR.ipynb` está vazio;
- não há seed do baralho, Python, NumPy ou PyTorch, rotação de assentos nem duplicate deals;
- o replay DDQN guarda somente a última ação da mão e marca toda transição como terminal;
- buffer e otimizador reiniciam a cada partida, e o target network não é sincronizado depois de
  carregar o checkpoint;
- `MSELoss` já reduz o batch antes da multiplicação pelos pesos, anulando a correção por amostra
  do prioritized replay;
- o agente continua explorando, treinando e salvando durante a suposta avaliação;
- o script estatístico filtra linhas por comprimento/saldo, não fixa o bootstrap e calcula como
  “p-value” a massa de um bootstrap centrado no efeito observado;
- o DeepSeek remoto usa alias mutável, temperatura `0.7`, chamadas sem timeout e retries/logs sem
  receipt imutável de modelo/resposta.

Logo, o resultado é uma implementação acadêmica auditável e útil como anti-padrão de QA, mas não
um baseline comparável ao protocolo local. O arquivo MIT é herdado do PyPokerEngine original e
não resolve por si só a linhagem/licença do checkpoint ou dos logs.

## Incidente de integridade

Consultas `site:.ac.in` devolveram páginas de cassino/app-store em subcaminhos acadêmicos indianos,
com texto promocional e alegações de IA sem fonte. Esses resultados foram classificados como
provável SEO poisoning/comprometimento, não como produção acadêmica. Nenhum link, claim ou arquivo
desses resultados entrou no corpus. A regra decorrente é explícita: domínio institucional sozinho
não prova proveniência; título, autoria, venue, conteúdo e artefato precisam ser coerentes.

## Decisão

Não foi encontrado peso ou dataset regional promovível. Os ganhos reais são: higiene de replay no
NFSP, futuro benchmark AIVAT, holdout temporal moderno para PHH, testes negativos derivados da
auditoria HSE e uma barreira contra fontes academic-looking contaminadas. Isso melhora rigor e
eficiência experimental sem fabricar ganho.

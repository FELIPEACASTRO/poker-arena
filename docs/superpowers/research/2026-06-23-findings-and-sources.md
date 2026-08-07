# Poker Arena — Dossiê de Pesquisa, Achados e Fontes Verificadas

> **SNAPSHOT HISTÓRICO DE PESQUISA (2026-06-23).** “Verificado” significa verificado
> naquele levantamento, não exaustivo nem atual em 2026-07-17. Contagens de buscas no HF/
> Kaggle, disponibilidade de hardware/serviços, licenças, preços e conclusões sobre ausência
> de modelos podem mudar. Este arquivo também mistura evidência externa com planos que não
> foram implementados. Não o use como prova do runtime; consulte o inventário atual, os
> model cards e o relatório de estado da arte mais recente.

**Data:** 2026-06-23
**Método:** análise de 2 documentos externos (`plano_jogo_poker_bots_double_check.md`
e `pesquisa_completa_poker_ai_bots_2026.md`) + **verificação na fonte** das URLs
de maior risco/valor + **garimpo autenticado** em HuggingFace e Kaggle.
**Regra:** nada de achismo — cada item marca `[✓ verificado na fonte]` ou `[conforme doc]`.

---

## 1. Veredito de integridade das fontes

No recorte histórico, as 13 referências examinadas resolveram para trabalhos existentes.
Isso não certifica todas as alegações desses trabalhos, nem todo o dossiê, e a atualidade
de cada metadado precisa ser revalidada. Duas ressalvas de qualidade e um erro interno
foram registrados abaixo.

### 1.1 Papers verificados na fonte

| Paper | arXiv | Verdito |
|---|---|---|
| PokerBench | 2501.08328 | ✅ real (jan/2025) |
| NFSP (Heinrich & Silver) | 1603.01121 | ✅ real (2016) — "NFSP approached a Nash equilibrium" em Leduc |
| GTO Wizard Benchmark | 2603.23660 | ✅ real (mar/2026) |
| ToolPoker | 2602.00528 | ✅ real (jan/2026) |
| Real-Time Parallel CFR | 2605.19928 | ✅ real (mai/2026) — 3.3× em 1 GPU |
| Embedding CFR | 2511.12083 | ✅ real (nov/2025) |
| SpinGPT | 2509.22387 | ✅ real (set/2025) — 78% match de solver em Spin&Go 3-handed |
| Readable Minds | 2604.04157 | ✅ real (abr/2026) |
| PokerSkill | 2605.30094 | ✅ real (mai/2026) |
| SPIRAL | 2506.24119 | ✅ real (jun/2025) |
| MARSHAL | 2510.15414 | ⚠️ real, **mas é raciocínio matemático, não poker** (só existe o modelo MARSHAL-Kuhn) |
| Robust Deep MCCFR | 2509.00923 | ⚠️ existe, **RETIRADO (withdrawn) pelo autor** por erros numéricos — não citar |
| Reevaluating Policy Gradient (IIG) | 2502.08938 | ✅ real — PPO deve ser controle; o paper não estabelece superioridade universal nem transferência a NLHE |

### 1.2 Ferramentas e dados verificados

| Recurso | Verdito |
|---|---|
| **RLCard** | ✅ NFSP **sim**, Deep CFR **NÃO** (só CFR tabular); NLHE abstraído; MIT; último release mar/2022 |
| **OpenSpiel** | ✅ NFSP **+** Deep CFR **+** CFR/MCCFR **+** exploitability/best-response — tudo numa lib |
| **PokerKit** | ✅ Python puro, MIT, 99% cobertura, multi-variante, "para poker AI/tooling" |
| **PokerBench** (dataset) | ✅ 574.200 registros, labels de solver p/ NLHE 6-max, **Apache-2.0** |

---

## 2. O único erro factual — e era nosso

> Nosso design dizia *"RLCard (NFSP, Deep CFR)"*. **Falso:** RLCard **não tem Deep
> CFR**. Correção aplicada: **OpenSpiel** (tem os dois + exploitability). `[✓]`

---

## 3. Garimpo HuggingFace + Kaggle (recursos NOVOS, não estavam nos docs)

Busca declarada naquele snapshot por "poker": **HF = 150 models + 80 datasets + 80 spaces**;
**Kaggle = ~60 datasets + models + kernels**.

### 3.1 Kaggle (oficiais e recentes)
- 🆕 `kaggle/poker-heads-up` (abr/2026) + `poker-heads-up-gameplay` (jun/2026, ~45 GB)
  — **LLMs de ponta jogando heads-up entre si** (Claude Opus 4.6, GPT-5, Gemini 3,
  Grok 4, DeepSeek, o3). Benchmark atual e citável. `[✓ inspecionei os arquivos]`
- 🆕 `benjaminniesmertelny/texas-holdem-monte-carlo-data` — **tabelas de equity
  pré-computadas por street** (`preflop/flop/turn/river_equity.csv`, ~1.4 MB).
  **Uso:** validar + cachear o bot Monte Carlo. `[✓ inspecionei os arquivos]`
- `mandines-real-poker-hands` (jun/2026), `pgt-high-roller`, `wsop-final-table`,
  `triton-poker-game-data` — históricos de torneio reais.

### 3.2 HuggingFace
- `KotDAzur/poker-nlh` — **45,4M linhas de históricos NLHE reais (2009)**, ~1.9 GB,
  **sem licença declarada** → tratar como parser/estatística, **não** label ótimo. `[✓]`
- `violetxi/clbench-*poker*` — suíte de pesquisa de world-model/exploitability.
- `the-acorn-ai/kuhn-poker-*` (trajetórias Kuhn), `mradermacher/poker-reasoning-14b`,
  vários `iamPi/leduc_poker-*` (LLMs em Leduc).
- Na amostra reportada, os modelos eram LLM/visão/robótica; não foi localizado checkpoint
  NFSP/Deep CFR diretamente promovível. Isso não prova ausência fora do recorte. `[✓]`

### 3.3 Negativos úteis (verificados)
- Não foi localizada, naquele recorte, Space com a experiência completa; originalidade
  universal não foi demonstrada.
- Não foi localizado modelo de poker no recorte consultado de Kaggle Models; os notebooks
  de RL/CFR amostrados não trouxeram evidência suficiente para promoção.

---

## 4. Achados → impacto MICRO e MACRO

| # | Achado | 🔬 Micro (implementação) | 🌍 Macro (estratégia) |
|---|---|---|---|
| 1 | RLCard ≠ Deep CFR → **OpenSpiel** | NFSP+DeepCFR+exploitability numa lib | corrige erro + dá a prova científica |
| 2 | **PPO como controle em IIG** (2502.08938) | treinar via `stable-baselines3` | comparar antes de challengers; autores alertam para cinco jogos/tuning e não universalidade |
| 3 | **6-max não é soma-zero** | medir cross-play + bb/100, não exploitability | re-escopa a tese; legitima o Modo Laboratório |
| 4 | **Equity tables (Kaggle)** | validar/cachear o bot Monte Carlo | bot Intermediário mais forte, de graça |
| 5 | **PokerBench (Apache-2.0)** | baseline supervisionado + action-agreement | eixo de avaliação extra e limpo |
| 6 | **PokerKit como oráculo** | cruzar 1M de mãos vs nosso motor | de-risca o engine sem reescrever |
| 7 | **HF Spaces/ZeroGPU** | publicar a demo como Space | host grátis, público, diferenciado |
| 8 | **HF Jobs + Kaggle GPU** | dois caminhos de treino na nuvem | redundância de prazo, custo zero |
| 9 | **LLM só de explicação** | GGUF leve verbaliza a decisão do engine | wow-factor; LLM não decide (provado) |
| 10 | **Dificuldade × Personalidade + mistura** | `α·forte+β·estilo+γ·erro` | um motor → 5 níveis, sem treinar 5 modelos |
| 11 | **Observação filtrada por assento** | `Observation` sem cartas de terceiros + teste | segurança por construção |
| 12 | **PHH + event sourcing** | logar mãos em formato aberto | reprodutibilidade + dataset próprio |
| 13 | **Datasets LLM-vs-LLM (Kaggle)** | análise de contexto | ângulo bônus "como a IA de 2026 joga" |
| 14 | **Licenças permissivas** | ficar em MIT/Apache; evitar AGPL/NC | sem contaminação jurídica |
| 15 | **Motor já pronto (38 testes)** | — | estamos à frente do greenfield dos docs |

---

## 5. Contradição entre os dois documentos (resolvida)

- `double_check.md` recomenda **"sem ML, React local-first, produto comercial"** e
  **não menciona feira de ciências** → seguir isso **reprovaria** o requisito da feira.
- `pesquisa_completa.md` **abraça ML/CFR/self-play** e é tecnicamente correto.
- **Resolução:** para a feira (que exige ML de ponta), o `pesquisa_completa` **governa**
  a arquitetura; o `double_check` vira fonte só de **produto/UX** (telas, personalidades,
  acessibilidade).

---

## 6. Índice de fontes-chave (com licença)

| Recurso | URL | Licença |
|---|---|---|
| OpenSpiel | https://github.com/google-deepmind/open_spiel | Apache-2.0 |
| RLCard | https://github.com/datamllab/rlcard | MIT |
| PokerKit | https://github.com/uoftcprg/pokerkit | MIT |
| treys | https://github.com/ihendley/treys | MIT |
| PokerBench (dataset) | https://huggingface.co/datasets/RZ412/PokerBench | Apache-2.0 |
| PHH (formato) | https://github.com/uoftcprg/phh-std | aberto |
| stable-baselines3 (PPO) | https://stable-baselines3.readthedocs.io/ | MIT |
| Reevaluating PG (PPO em IIG) | https://arxiv.org/abs/2502.08938 | — |
| Kaggle equity tables | benjaminniesmertelny/texas-holdem-monte-carlo-data | verificar |
| Kaggle LLM-vs-LLM | kaggle/poker-heads-up | verificar |

> ⚠️ **Evitar** por licença restritiva: DecisionHoldem, TexasSolver C++, postflop-solver
> (AGPL); PokerSkill e Poker-SFT-Mix (CC BY-NC).

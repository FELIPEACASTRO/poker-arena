# Poker Arena — Design / Especificação

> **DOCUMENTO HISTÓRICO (2026-06-23), NÃO NORMATIVO.** Este texto registra objetivos e
> hipóteses anteriores à implementação atual. Itens como mesa fixa de 6 lugares, NFSP ×
> Deep CFR no produto, treino em Kaggle/HF, IA super-humana, exploitability do NLHE e
> contagens de testes não descrevem o estado comprovado do pacote. Para o estado atual,
> use o `README.md`, `ml/README.md`, o OpenAPI gerado e os model cards. Planos não marcados
> como concluídos aqui continuam sendo backlog, não funcionalidades.

**Data:** 2026-06-23
**Autor:** Felipe (+ Claude)
**Contexto:** Apresentação em feira de ciências cujo desafio é **usar tecnologia
de ponta com Machine Learning e IA**.

---

## 1. Visão geral

App web onde o usuário monta uma mesa de Texas Hold'em No-Limit (6 lugares),
escolhe o "nível de inteligência" de cada bot, senta na 6ª cadeira e joga contra
eles. O bot mais avançado é uma **rede neural treinada por self-play
(Reinforcement Learning)** — IA de verdade. Os bots mais simples são *baselines*
destinados a testar, de forma mensurável, se a IA supera cada baseline no protocolo fixado.

**Hipótese científica histórica (1):** *Um agente que aprende sozinho, jogando milhões de mãos
contra si mesmo via deep reinforcement learning, supera estratégias programadas
à mão.* — deveria ser testada por win-rate, curvas de treino e, somente em jogos
menores compatíveis, exploitability.

**Tese científica (2) — o diferencial "Modo Laboratório":** *Duas escolas de IA
podem ser comparadas ao vivo no mesmo jogo:* uma que **aprende pela experiência**
(NFSP / Reinforcement Learning) e outra que **raciocina pela teoria dos jogos**
(Deep CFR / rumo ao ótimo de Nash). O usuário escolhe, antes da partida, qual
cérebro ocupa cada cadeira — inclusive colocando NFSP × Deep CFR na mesma mesa —
e os dados (win-rate, exploitability, estilo de decisão) respondem qual joga
melhor e como "pensam" diferente.

---

## 2. Visão de Negócio (Business Architecture)

- **Proposta de valor:** transformar o projeto num **laboratório vivo de IA** —
  não só demonstrar que IA moderna supera estratégias programadas, mas permitir
  que o avaliador **escolha e compare paradigmas de IA** (aprender × raciocinar)
  jogando contra eles, usando poker como vitrine que qualquer pessoa entende em
  segundos.
- **Stakeholders:**
  - *Autor (Felipe)* — constrói e apresenta.
  - *Banca da feira* — avalia rigor científico e inovação.
  - *Público / jogadores* — interagem jogando contra a IA.
- **Capacidades de negócio (o que a solução precisa entregar):**
  1. Jogar Texas Hold'em corretamente (regras à prova de erro).
  2. Oferecer múltiplos níveis de inteligência **selecionáveis por cadeira antes
     da partida** (Modo Laboratório).
  3. Treinar duas IAs: **NFSP** (self-play) e **Deep CFR** (teoria dos jogos).
  4. Medir quantitativamente a IA contra cada baseline, aceitando vitória, empate ou derrota.
  5. **Comparar NFSP × Deep CFR ao vivo** (duelo na mesma mesa + placar).
  6. Explicar visualmente as decisões dos bots.
  7. Permitir partida ao vivo (humano vs bots).
- **Métricas de sucesso (com a separação de rigor correta — achado verificado):**
  - **Jogos pequenos (Kuhn / Leduc / heads-up):** exploitability / NashConv cai ao
    longo do treino → **prova matemática** de convergência ao ótimo (best-response).
  - **Mesa de 6 (sem garantia de equilíbrio):** avaliar por **cross-play** (matriz
    de duelos) + **bb/100 com intervalo de confiança** + **AIVAT** (redução de
    variância) — **não** por exploitability (6-max não é soma-zero de 2 jogadores).
  - A IA vence cada baseline com margem estatística clara (em N mãos duplicadas).
  - **O duelo NFSP × Deep CFR é demonstrável ao vivo** (= a própria matriz de cross-play).
  - Um juiz entende a diferença entre níveis em < 1 minuto; a demo roda sem travar.
- **Restrições históricas:** compute externo de baixo custo, sem dinheiro real e prazo
  da feira (~2+ meses). Contas e planos pessoais foram removidos deste documento.

---

## 3. Escopo

- **Variante:** Texas Hold'em No-Limit
- **Mesa:** 6 jogadores (1 humano + até 5 bots)
- **Escada de inteligência:** ver seção 5
- **Frontend:** app web em React + TypeScript
- **Backend:** Python + FastAPI, WebSocket
- **ML estrela:** NFSP (self-play). **Capítulo de rigor (se houver tempo):**
  Deep CFR em jogos pequenos.

### Fora de escopo (YAGNI)
- IA superhumana no 6-max No-Limit completo (pesquisa de ponta — Pluribus usou
  supercomputador). A IA jogável será a melhor possível com GPU grátis.
- Dinheiro real / qualquer integração com plataformas online de aposta.
- Multiplayer humano em rede.

---

## 4. Visão de Solução (Solution Architecture)

### Componentes
**Backend (Python/FastAPI)**
- `engine/` — motor de poker: deck, dealing, rodadas, pote/side pots, ordem de
  jogada, determinação de vencedor.
- `evaluation/` — wrapper sobre biblioteca testada de avaliação de mãos.
- `bots/` — interface `Bot` comum + implementações: Random, Heuristic,
  MonteCarlo, e **MLBot** parametrizável pelo cérebro carregado (**checkpoint
  NFSP / Deep CFR / PPO**). Recebe apenas uma **observação filtrada por assento**
  (`Observation`) — **nunca** as cartas de outros jogadores, garantido por teste.
  Cada bot expõe seu "raciocínio" para o painel. A interface comum é o que permite
  o Modo Laboratório: qualquer cérebro pluga em qualquer cadeira.
- `api/` — FastAPI: setup (REST) + eventos do jogo (WebSocket).
- `engine/` (sessão) — `Hand` (uma mão: blinds, apostas validadas com regras de
  No-Limit, side pots, showdown) + `Table` (várias mãos: rotação de botão,
  eliminação de quem zera, fim de jogo). É a base que mede "IA vence em N mãos".

**Frontend (React + TS)**
- Tela de setup — **Modo Laboratório**: menu por cadeira escolhendo o cérebro
  (`Random / Heurística / Monte Carlo / NFSP / Deep CFR`).
- Mesa de poker (6 lugares, cartas, pote, fichas).
- Controles de aposta do humano.
- Painel de raciocínio do bot da vez.
- **Tela de comparação** — placar NFSP × Deep CFR (win-rate, exploitability,
  estilo de decisão) ao longo de muitas mãos.

**Pipeline de ML (offline, na nuvem)**
- Treino NFSP/Deep CFR em GPU grátis (Kaggle / HF Jobs).
- Avaliação (win-rate vs baselines, exploitability) e curvas.
- Modelo final publicado no **HF Hub**, baixado pelo backend p/ inferência.

### Fluxo de dados
1. **Jogo ao vivo:** setup → eventos via WebSocket → decisão do bot (inferência
   local da rede) → render na mesa.
2. **Treino:** ambiente de poker (**OpenSpiel**: curriculum Kuhn → Leduc → Hold'em
   abstraído) → self-play (NFSP / Deep CFR / **PPO**) em GPU na nuvem (Kaggle / HF
   Jobs) → modelo no HF Hub → backend baixa e serve.

### Decisões de arquitetura (ADRs resumidos)
| Decisão | Por quê |
|---|---|
| **React** no front | UI rica/animada, padrão de mercado, impressiona na feira |
| **FastAPI + WebSocket** | Tempo real + ecossistema Python (mesmo do ML) |
| **OpenSpiel + PyTorch** | NFSP **e** Deep CFR **e** exploitability numa lib só (Apache-2.0). ⚠️ Correção verificada: **RLCard NÃO tem Deep CFR** (só NFSP/CFR) — por isso OpenSpiel |
| **PPO self-play** (stable-baselines3) | Controle obrigatório: o paper 2502.08938 não encontrou vantagem de um representante FP/DO/CFR sobre policy gradients nos cinco jogos testados, mas os autores rejeitam generalização universal; não prova superioridade em NLHE |
| **`treys`** (mãos) + **PokerKit** (oráculo) | treys já no código; PokerKit (MIT, 99% cov) cruza 1M de mãos p/ validar o motor |
| **Treino na nuvem** (Kaggle + HF Jobs) | Alternativas históricas sem GPU local; disponibilidade, cota e hardware exigem verificação a cada execução |
| **HF Hub** p/ modelo + **HF Spaces/ZeroGPU** p/ demo | Hospedagem versionada do modelo + demo pública grátis |
| **venv Python 3.11** p/ ML | PyTorch/OpenSpiel ainda sem wheel p/ o 3.14 local |

---

## 5. A escada de inteligência (núcleo científico)

| Nível | Cérebro | Papel |
|---|---|---|
| 🟢 Iniciante | Aleatório com viés | baseline (chão) |
| 🟡 Amador | Heurística por força da mão | baseline |
| 🟠 Intermediário | Monte Carlo (equity) + pot odds | baseline forte (matemático) |
| 🔴 **IA — NFSP** | **Rede neural treinada por self-play** (aprende pela experiência) | ⭐ estrela — ML de ponta |
| 🟣 **IA — Deep CFR** | **Rede que raciocina pela teoria dos jogos** (rumo ao ótimo de Nash) | ⭐ 2ª estrela — rigor/GTO |

**Modo Laboratório:** os dois cérebros de IA (e os baselines) são **selecionáveis
por cadeira antes da partida**. Dá pra jogar contra um, contra os dois, ou pôr
**NFSP × Deep CFR** frente a frente.

**Cérebro de controle:** além de NFSP/Deep CFR, avaliar **PPO self-play**
(`stable-baselines3`). O paper 2502.08938 justifica incluí-lo no protocolo comparativo;
não transfere ranking, parâmetros nem garantia para NLHE 6-max.

**Dois eixos (Dificuldade × Personalidade):** o *nível* (qualidade da decisão) é
ortogonal à *personalidade* (TAG/LAG/Tight-Passive/…). Um motor só gera muitos
bots por **mistura**: `política = α·forte + β·estilo + γ·erro` (Σ=1) — sem treinar
5 modelos.

**Capítulo de rigor:** Deep CFR/NFSP em **Kuhn/Leduc**, medindo *exploitability*
para provar convergência ao ótimo. ⚠️ No **6-max não há garantia de equilíbrio** —
ali a força se mede por **cross-play**, não exploitability. Entrega via escada de
risco: NFSP primeiro (reduz o risco de entrega), Deep CFR/PPO depois.

---

## 6. Onde mora a "precisão"

1. **Corretude das regras:** aferida por TDD, testes diferenciais e biblioteca-oráculo;
   cobertura não equivale a prova de ausência de defeitos.
2. **Qualidade da IA:** vem de treino (self-play), arquitetura da rede e compute.
   Forte e demonstrável; não "imbatível teórico" sem compute de pesquisa.
3. **Rigor estatístico:** comparações IA vs baselines com nº de mãos suficiente
   p/ significância.

---

## 7. Stack técnica

- **Backend:** Python 3.11 (venv p/ ML), FastAPI, WebSockets, NumPy.
- **Avaliação de mãos:** `treys` (já no código); **PokerKit** como oráculo de validação.
- **ML:** PyTorch + **OpenSpiel** (NFSP + Deep CFR + exploitability). Cérebro
  "que aprende" alternativo: **PPO self-play** (`stable-baselines3`).
- **Dados auxiliares:** tabelas de **equity** pré-computadas (Kaggle) p/ cachear o
  bot Monte Carlo; **PokerBench** (Apache-2.0) p/ baseline supervisionado/benchmark.
- **Formato/repro:** **PHH** (histórico aberto) + event sourcing + replay determinístico.
- **Treino/host (plano histórico):** provedores externos como Colab, HF Jobs e Kaggle,
  com hardware e cotas verificados no momento da execução. Identificadores de conta e
  status de assinatura foram removidos. Modelo no HF Hub e demo em HF Spaces eram
  opções de publicação, não garantias operacionais.
- **Frontend:** React + Vite + TypeScript.
- **Estrutura:** monorepo `backend/` + `frontend/` + `ml/`.

---

## 8. Recursos-chave para a feira

**Modo Laboratório (o grande diferencial):** antes da partida, o avaliador
escolhe o cérebro de cada cadeira e pode pôr **NFSP × Deep CFR** frente a frente.
Transforma o projeto de "uma IA" em **uma bancada que compara dois paradigmas de
IA ao vivo** e deixa os dados decidirem qual joga melhor. Raro num projeto de
feira — eleva o nível para "cara de pesquisa".

**Painel de raciocínio:** ao jogar, cada bot mostra chance estimada de ganhar,
pot odds e o porquê da decisão — torna a IA *visível*, não caixa-preta. No duelo,
mostra os dois paradigmas decidindo *diferente* na mesma situação.

**Camada de explicação em linguagem natural (opcional):** um **LLM pequeno** (GGUF
leve, ex. PokerBench-SFT) traduz a decisão *já tomada pelo engine* em português
("aumentei: 72% de equity e o pote dava odds"). ⚠️ O LLM **explica, nunca decide**
— benchmarks verificados (ToolPoker, GTO-Wizard) mostram LLMs abaixo do solver.
Padrão *tool-use*: engine decide → LLM verbaliza.

**Evidências científicas a exibir:** curva de treino (recompensa), win-rate da IA
vs cada baseline, **placar NFSP × Deep CFR**, e exploitability caindo (jogos
pequenos).

---

## 9. Estratégia de testes (reduz o risco de erro)

- TDD no motor: desempates, side pots, all-ins simultâneos, ordem de aposta.
- Seeds fixas (determinismo).
- Testes de sanidade dos bots (Monte Carlo converge p/ equity conhecida).
- Avaliação estatística IA vs baselines.

---

## 10. Gestão de risco

Cada fase entrega algo apresentável. Ordem de risco controlado:
1. Motor + baselines (Random/Heuristic/MonteCarlo) → já é demo jogável.
2. NFSP (a estrela) → IA de verdade.
3. Deep CFR (rigor) → só se sobrar tempo.
Nunca chegar na feira de mãos vazias.

---

## 11. Infraestrutura e descobertas (garimpo HF + Kaggle, verificado)

- **Provedores externos:** o levantamento histórico considerou Colab, Kaggle e
  Hugging Face para treino e publicação. Identificadores, planos pessoais e estado de
  autenticação foram removidos; disponibilidade, hardware e cotas não são garantidos.
- **Busca histórica:** naquele recorte não foi localizado um Space com a experiência
  completa nem checkpoint NFSP/Deep CFR diretamente promovível. Isso não prova
  inexistência atual e requer nova busca antes de orientar decisões.
- **Licenças (requisito técnico):** nossa pilha é permissiva
  (OpenSpiel/RLCard/PokerKit/treys/PokerBench = MIT/Apache). **Evitar** AGPL
  (DecisionHoldem, TexasSolver, postflop-solver) e **CC-BY-NC** (PokerSkill, alguns
  datasets) se houver publicação/demo.
- **Registro histórico:** o motor então informava 38 testes e 98% de cobertura; os
  números atuais devem vir exclusivamente do gate de QA reproduzido no checkout.
- Chaves mantidas FORA do repositório; `.gitignore` reforça o bloqueio de segredos.

# Poker Arena — Design / Especificação

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
que provam, de forma mensurável, a superioridade da IA.

**Tese científica (1):** *Um agente que aprende sozinho, jogando milhões de mãos
contra si mesmo via deep reinforcement learning, supera estratégias programadas
à mão.* — provada por win-rate, curvas de treino e (em jogos menores)
exploitability.

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
  4. Provar quantitativamente a superioridade da IA sobre os baselines.
  5. **Comparar NFSP × Deep CFR ao vivo** (duelo na mesma mesa + placar).
  6. Explicar visualmente as decisões dos bots.
  7. Permitir partida ao vivo (humano vs bots).
- **Métricas de sucesso:**
  - A IA vence cada baseline com margem estatística clara (em N mãos).
  - Exploitability cai ao longo do treino nos jogos pequenos (prova de
    convergência ao ótimo).
  - **O duelo NFSP × Deep CFR é demonstrável ao vivo**, com placar de win-rate e
    comparação de exploitability entre os dois paradigmas.
  - Um juiz entende a diferença entre níveis em < 1 minuto.
  - A demo roda do início ao fim sem travar.
- **Restrições:** GPU somente gratuita (Kaggle / HF PRO), sem dinheiro real,
  prazo da feira (~2+ meses).

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
  MonteCarlo, e **MLBot** parametrizável pelo cérebro carregado
  (**checkpoint NFSP** ou **checkpoint Deep CFR**). Cada bot expõe seu
  "raciocínio" para o painel. A interface comum é o que permite o Modo
  Laboratório: qualquer cérebro pluga em qualquer cadeira.
- `api/` — FastAPI: setup (REST) + eventos do jogo (WebSocket).
- `state/` — máquina de estado da partida.

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
2. **Treino:** ambiente de poker (RLCard) → self-play em GPU na nuvem → modelo no
   HF Hub → backend baixa e serve.

### Decisões de arquitetura (ADRs resumidos)
| Decisão | Por quê |
|---|---|
| **React** no front | UI rica/animada, padrão de mercado, impressiona na feira |
| **FastAPI + WebSocket** | Tempo real + ecossistema Python (mesmo do ML) |
| **RLCard + PyTorch** | SOTA pronto p/ poker (NFSP, Deep CFR), foca esforço na ciência |
| **Biblioteca de mãos** (`treys`/`pokerkit`) | Corretude perfeita das regras sem reinventar |
| **Treino na nuvem** (Kaggle/HF) | Sem GPU local; HF PRO acelera |
| **HF Hub** p/ modelo | Hospedagem versionada do modelo treinado |
| **venv Python 3.11** p/ ML | PyTorch/RLCard ainda sem wheel p/ o 3.14 local |

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

**Capítulo de rigor:** Deep CFR em Leduc/Limit, medindo *exploitability*
(distância do equilíbrio de Nash) para provar convergência ao ótimo. Entrega via
escada de risco: NFSP primeiro (garante o projeto), Deep CFR depois.

---

## 6. Onde mora a "precisão"

1. **Corretude das regras:** 100% via TDD + biblioteca testada.
2. **Qualidade da IA:** vem de treino (self-play), arquitetura da rede e compute.
   Forte e demonstrável; não "imbatível teórico" sem compute de pesquisa.
3. **Rigor estatístico:** comparações IA vs baselines com nº de mãos suficiente
   p/ significância.

---

## 7. Stack técnica

- **Backend:** Python 3.11 (venv p/ ML), FastAPI, WebSockets, NumPy.
- **Avaliação de mãos:** `treys` ou `pokerkit`.
- **ML:** PyTorch + **RLCard** (NFSP, Deep CFR). Alternativa: OpenSpiel.
- **Treino/host:** Kaggle (GPU grátis) e/ou HF Jobs; modelo no **HF Hub** (conta
  PRO: `felipesp1983`).
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

**Evidências científicas a exibir:** curva de treino (recompensa), win-rate da IA
vs cada baseline, **placar NFSP × Deep CFR**, e exploitability caindo (jogos
pequenos).

---

## 9. Estratégia de testes (garante a precisão)

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

## 11. Infraestrutura já provisionada

- **Kaggle CLI** autenticada (`felipe1983`).
- **HuggingFace** autenticado (`felipesp1983`, **PRO confirmado**).
- Chaves mantidas FORA do repositório (em `POKER\`, pasta-pai); `.gitignore`
  reforça o bloqueio de segredos.

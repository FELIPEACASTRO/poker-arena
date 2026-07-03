# 🃏 Poker Arena

Jogo próprio de **Texas Hold'em No-Limit** (mesa de até **9 jogadores**) onde um
humano enfrenta bots de **inteligência selecionável** — do aleatório à IA treinada
por self-play. Projeto de **feira de ciências** com foco em IA / Machine Learning
*e* em engenharia de software de qualidade.

> **Modo Laboratório** — o grande diferencial: você monta uma mesa só de bots,
> escolhe o "cérebro" de cada cadeira e **compara os paradigmas de IA ao vivo**,
> com as cartas abertas. Cada jogada mostra, em **caixa de vidro**, *como aquele
> cérebro pensou* — a chance real, as opções boas e por quê.

---

## 🧠 Os 5 perfis de IA

Fonte única no backend (`available_levels()`); o Expert só aparece se o modelo
treinado (`.onnx`) existir.

| Nível | Nome | Como pensa (real, sem mock) |
|---|---|---|
| `random` | 🟢 **Iniciante** | joga no chute — linha de base |
| `heuristic` | 🟡 **Amador** | força da mão por regras (par, cartas altas, naipe) + pot odds |
| `montecarlo` | 🟠 **Intermediário** | simula centenas de finais de mão → **equity** vs pot odds |
| `adaptive` | 🧠 **Adaptativo** | força da mão **+ leitura do humano** (explora quem desiste/paga demais) |
| `expert` | 🔴 **Expert** | **rede neural** treinada (solver + self-play), servida via ONNX |

Cada bot expõe o **mesmo número que decide a jogada** (glass-box) — nada inventado.

---

## ✨ Destaques da experiência (frontend)

- **Dashboard "Lab científico"** — mesa de cassino (feltro verde + posições reais)
  cercada por painéis analíticos.
- **"Como o competidor está pensando"** (Modo Laboratório) — a cada jogada: como o
  paradigma raciocina, a **chance real** de ganhar, e **as opções (pagar/aumentar/
  desistir) avaliadas boa/arriscada/ruim, com o porquê**.
- **Sua jogada** (Modo Jogar) — equity multiway, outs/projetos, pot odds, EV, a nut,
  textura do board, e o **conselho das 5 IAs** (o que cada cérebro faria na sua vez).
- **Placar, Estilo de cada IA (VPIP/agressão) e Corrida das fichas** — estatísticas
  ao vivo, cada competidor com **cor própria** consistente em toda a tela.
- **Posições de poker** (SB, BB, UTG, UTG+1, MP1, MP2, DJ, HJ, BTN) nos assentos +
  **guia de regras por posição** (clique na sigla).
- **Gerenciar mesa** — sente/retire jogadores ao vivo, no nível que quiser.
- **Auditoria** — toda partida é gravada; replay mão a mão com o raciocínio de cada IA.
- **Guia dos Cérebros** — explicação didática (estilo *Use a Cabeça*) de cada nível.

---

## ✅ Fidelidade às regras oficiais

Motor auditado contra a documentação oficial (PokerNews / PokerStars / TDA-WSOP) e
**em conformidade**: blinds e rotação do botão, heads-up, ordem de ação (UTG pré-flop
/ SB pós-flop), **aumento mínimo e full-raise**, **all-in incompleto não reabre a
aposta** (TDA 47 / WSOP 96), **side pots**, burn cards, showdown (melhor de 5 em 7),
ranking de mãos, opção do big blind e ficha-ímpar à esquerda do botão. As cartas são
embaralhadas com **aleatoriedade criptográfica** (`SystemRandom`).

---

## ▶️ Como rodar (Windows)

**Jeito fácil:** duplo-clique no ícone **POKER** na Área de Trabalho (ou em
[`POKER.bat`](POKER.bat) na raiz) → menu:

```
[1] Iniciar   (backend + frontend + navegador)
[2] Parar     (encerra os servidores)
[3] Abrir no navegador
[4] Validar   (testes + build + lint)
```

**Manual:**
```bash
# backend  -> http://127.0.0.1:8000/docs
cd backend && uv run uvicorn poker_arena.api.app:app --port 8000
# frontend -> http://localhost:5173
cd frontend && npm install && npm run dev
```

---

## 📘 Documentação da API — pasta [`api-docs/`](api-docs/)

- **Swagger ao vivo:** http://127.0.0.1:8000/docs (com o backend rodando).
- **Swagger offline:** `api-docs/swagger.html` (abre por duplo-clique).
- **Insomnia:** importe `api-docs/insomnia.json` (todos os serviços em pastas).
- **OpenAPI:** `api-docs/openapi.json`. Regenera com `uv run python ../api-docs/generate.py`.

### Endpoints
| Método | Rota | O que faz |
|---|---|---|
| `POST` | `/tables` | cria a mesa (cérebros, blinds, formato, modo) → devolve o `table_id` |
| `GET` | `/tables/{id}` | estado atual da mesa |
| `POST` | `/tables/{id}/actions` | sua jogada (`fold/check/call/raise/all_in`) |
| `POST` | `/tables/{id}/step` | avança 1 jogada de bot (Modo Laboratório) |
| `POST` | `/tables/{id}/next-hand` | próxima mão |
| `POST` | `/tables/{id}/players` | senta um novo bot |
| `DELETE` | `/tables/{id}/players/{seat}` | remove um jogador |
| `GET` | `/levels` · `/games` · `/games/{id}` · `/health` | catálogo, auditoria, saúde |
| `WS` | `/tables/{id}/ws` | estado em tempo real (push a cada ação) |

Erros do domínio viram HTTP: inexistente → **404**; ação ilegal/inválida → **400**.

---

## 🗂️ Estrutura (monorepo)

```
backend/          API + motor + bots (Python, Clean Architecture)
  poker_arena/
    engine/       domínio: regras do poker (Hand, Table, cartas, avaliador, posições)
    bots/         domínio: cérebros (Strategy) + observação filtrada por assento
    application/  use cases: GameSession (Facade), BotFactory, análise, raciocínio, stats
    api/          interface: FastAPI (REST + WebSocket), schemas, ACL/mappers, DI
  tests/          unidade + integração (pytest)
frontend/         mesa + dashboard em React + TypeScript (Vite)
api-docs/         Swagger (openapi.json + swagger.html) + projeto Insomnia
assets/           ícone do app + scripts (stop.ps1, validar.ps1)
ml/               notebooks de treino/prova (OpenSpiel) — rodam no Colab
```

---

## 🏛️ Arquitetura — Clean Architecture

Dependências apontam **para dentro**. O domínio não conhece ninguém; a web conhece
tudo. Trocar FastAPI por outra coisa não toca no motor.

```
  api/  (FastAPI, Pydantic, DI)              ← detalhes externos
   ↓ depende de
  application/  (GameSession, Factory, Repo) ← casos de uso
   ↓ depende de
  engine/ + bots/  (regras puras do poker)   ← domínio (núcleo)
```

### Design Patterns aplicados
| Padrão | Onde | Por quê |
|---|---|---|
| **Strategy** | `bots/` (interface `Bot`) | cada cérebro é uma estratégia intercambiável |
| **Factory** | `application/bot_factory.py` | cria o bot a partir do nível (OCP) |
| **Repository** | `application/session_repository.py` | guarda sessões atrás de uma interface (DIP) |
| **Facade** | `application/game_session.py` | esconde a orquestração motor+bots |
| **Anti-Corruption Layer** | `api/mappers.py` | traduz domínio ↔ web sem vazamento |
| **DTO** | `api/schemas.py` + `application/views.py` | contratos de dados explícitos |
| **Adapter** | `bots/observation.py` | adapta `Bot` ao loop do motor |
| **CQRS-lite** | `GameSession` (comandos vs `view()`) e API (POST vs GET) | separa escrita de leitura |

### SOLID
**S**RP (um motivo de mudança por módulo) · **O**CP (novo bot sem editar o resto) ·
**L**SP (qualquer `Bot`/`Repository` é substituível) · **I**SP (interfaces mínimas) ·
**D**IP (a API depende da abstração, não da implementação).

---

## ⏱️ Análise assintótica (Big O)

`P` = jogadores (≤9), `N` = amostras de Monte Carlo.

| Operação | Complexidade |
|---|---|
| Avaliar mão (`treys`) | **O(1)** (perfect-hash) |
| `legal_actions` / `round_complete` | **O(1)** / **O(P)** |
| `build_side_pots` | **O(P²)** (P≤9 → trivial) |
| `MonteCarloBot.estimate_equity` | **O(N·P)** — mais N = estimativa melhor |
| `Repository.get/add` | **O(1)** |

---

## 🔬 Qualidade e validação

Rode a opção **[4] Validar** no launcher, ou:
```bash
cd backend && uv run pytest -q           # 133 testes (motor, bots, aplicação, API)
cd frontend && npm test && npm run build && npm run lint   # 12 testes + build + lint
```

- **Testes:** unidade + **integração** (API via `TestClient`) no backend; componentes
  (`@testing-library`) no frontend.
- **Regras do poker** cobertas por testes (side pots, all-in incompleto, full-hand).
- **Sem mock/stub na solução** — todo painel usa dado real do motor.

---

## 🤖 Machine Learning (`ml/`)
Notebooks que rodam no **Colab** (treino na nuvem; o backend só serve o checkpoint
ONNX do Expert). CFR converge ao Nash (Kuhn/Leduc); NFSP/self-play para a política
neural. Detalhes: `ml/README.md`.

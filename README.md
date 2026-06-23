# 🃏 Poker Arena

Jogo próprio de **Texas Hold'em No-Limit** onde um humano enfrenta bots de
**inteligência selecionável** — de aleatório a IA treinada por self-play. Projeto
de **feira de ciências** com foco em IA / Machine Learning *e* em engenharia de
software de qualidade.

> **Modo Laboratório:** o grande diferencial — você escolhe o "cérebro" de cada
> cadeira (Random → Heurística → Monte Carlo → NFSP → Deep CFR) e compara
> paradigmas de IA **ao vivo, na mesma mesa**.

---

## Estrutura (monorepo)

```
backend/          API + motor + bots (Python, Clean Architecture)
  poker_arena/
    engine/       domínio: regras do poker (Hand, Table, cartas, avaliador)
    bots/         domínio: cérebros (Strategy) + observação filtrada por assento
    application/  use cases: GameSession (Facade), BotFactory, Repository, DTOs
    api/          interface: FastAPI (REST + WebSocket), schemas, ACL/mappers, DI
  scripts/        demo_play.py — joga uma partida via API (logs "Use a Cabeça")
  tests/          unidade + integração (pytest)
frontend/         mesa em React + TypeScript (Vite) — consome a API
ml/               notebooks de treino/prova (OpenSpiel) — rodam no Colab
docs/             especificação, plano, dossiê de pesquisa verificada
```

---

## Arquitetura — Clean Architecture

Dependências apontam **para dentro**. O domínio não conhece ninguém; a web conhece
tudo. Trocar FastAPI por outra coisa não toca no motor.

```
            ┌───────────────────────────────────────────┐
            │  api/  (FastAPI, Pydantic, DI)             │  ← detalhes externos
            │   depende de ↓                             │
            │  application/  (GameSession, Factory, Repo)│  ← casos de uso
            │   depende de ↓                             │
            │  engine/ + bots/  (regras puras do poker)  │  ← domínio (núcleo)
            └───────────────────────────────────────────┘
```

- **Abstração / acoplamento / coesão:** cada arquivo tem **uma** responsabilidade
  e se comunica por interfaces estreitas; o domínio é puro (sem FastAPI/Pydantic).
- **Extensibilidade:** novo bot = registrar na `BotFactory`; novo repositório =
  implementar `SessionRepository`. Nada mais muda.

### Design Patterns aplicados

| Padrão | Onde | Por quê |
|---|---|---|
| **Strategy** | `bots/` (interface `Bot`) | cada cérebro é uma estratégia intercambiável |
| **Factory** | `application/bot_factory.py` | cria o bot a partir do nível (OCP) |
| **Repository** | `application/session_repository.py` | guarda sessões atrás de uma interface (DIP) |
| **Facade** | `application/game_session.py` | esconde a orquestração motor+bots |
| **Anti-Corruption Layer (ACL)** | `api/mappers.py` | traduz domínio ↔ web sem vazamento |
| **DTO** | `api/schemas.py` (web) + `application/views.py` (app) | contratos de dados explícitos |
| **Singleton (via DI)** | `api/dependencies.py` (`lru_cache`) | uma instância do repo, testável |
| **Adapter** | `bots/observation.py` (`as_strategy`) | adapta `Bot` ao loop do motor |
| **CQRS-lite** | `GameSession` (comandos vs `view()`) e API (POST vs GET) | separa escrita de leitura |

### Microservices patterns — aplicados com critério (não cargo-cult)
- ✅ **ACL** — fronteira domínio↔web (aplicado).
- ⚖️ **CQRS** — aplicado em versão *leve* (comando/consulta). **Event Sourcing**
  com event store seria **over-engineering** para um jogo single-player local.
- ❌ **SAGA / API Gateway / Service Discovery** — **não aplicáveis**: é um processo
  único, sem transações distribuídas nem múltiplos serviços. Aplicá-los aqui seria
  complexidade sem benefício.

### SOLID
- **S**RP — um motivo de mudança por módulo (cartas ≠ apostas ≠ avaliação).
- **O**CP — `BotFactory`/`Bot` permitem novos bots sem editar o existente.
- **L**SP — qualquer `Bot` ou `SessionRepository` é substituível.
- **I**SP — interfaces mínimas (`Bot.act`; `Repository.add/get/remove`).
- **D**IP — a API depende da **abstração** `SessionRepository`, não da implementação.

---

## Análise assintótica (Big O)

`P` = jogadores (≤6), `N` = amostras de Monte Carlo, `S` = streets (≤4).

| Operação | Complexidade | Observação |
|---|---|---|
| Avaliar mão (`treys`) | **O(1)** | perfect-hash; 7 cartas é custo fixo |
| `legal_actions` / `amount_to_call` | **O(1)** | poucas checagens |
| `round_complete` | **O(P)** | varre jogadores ativos |
| `build_side_pots` | **O(P²)** | camadas × contribuintes; P≤6 → trivial |
| `resolve` (showdown) | **O(P)** | P avaliações O(1) |
| `RandomBot` / `HeuristicBot.act` | **O(1)** | decisão direta |
| `MonteCarloBot.estimate_equity` | **O(N·P)** | **alavanca de força:** mais N = estimativa melhor |
| `GameSession._drive` (até a vez do humano) | **O(P·S · custo_bot)** | dirige uma mão |
| `Repository.get/add` | **O(1)** | dict em memória |

---

## Como rodar o backend

```bash
cd backend
uv venv --python 3.11 && uv pip install -e ".[dev]"
uv run uvicorn poker_arena.api.app:app --reload      # http://127.0.0.1:8000/docs
```

### Endpoints
| Método | Rota | O que faz |
|---|---|---|
| `GET` | `/health` | saúde |
| `POST` | `/tables` | cria mesa (escolhe os cérebros por cadeira) |
| `GET` | `/tables/{id}` | estado atual (query) |
| `POST` | `/tables/{id}/actions` | humano joga (`fold/check/call/raise/all_in`) |
| `POST` | `/tables/{id}/next-hand` | próxima mão |
| `WS` | `/tables/{id}/ws` | estado em tempo real (push a cada ação) |

Erros do domínio viram HTTP: inexistente → **404**; ação ilegal/inválida → **400**.

### Atalho (Windows) — subir tudo de uma vez
Duplo-clique em **`subir.bat`** na raiz (ou rode `subir.bat` no terminal): sobe o
**backend** e o **frontend** em janelas separadas e abre o navegador sozinho.

### Demo ao vivo (sem frontend)
```bash
cd backend && uv run python scripts/demo_play.py   # sobe o servidor e joga
```

### Frontend (a mesa visual)
```bash
cd frontend && npm install && npm run dev          # http://localhost:5173
```

---

## Qualidade

```bash
cd backend
uv run pytest --cov=poker_arena   # testes + cobertura
uv run ruff check . && uv run mypy
```

- **Testes:** unidade (motor, bots, aplicação) + **integração** (API via `TestClient`).
- **Cobertura:** **99%** (`73 testes`).
- **Lint/Tipos:** `ruff` + `mypy` (strict-ish) — zero issues.
- **TDD:** todo o motor e a aplicação nasceram de teste que falha primeiro.
- Logs de notebooks/jobs seguem o estilo *Use a Cabeça* (ver `ml/LOGGING_STYLE.md`).

---

## Machine Learning (`ml/`)
Notebooks que rodam no **Colab** (treino na nuvem; o backend só serve o checkpoint):
- `01_*` — **CFR** converge ao Nash (Kuhn + Leduc), com exploitability.
- `02_nfsp_leduc_single_cell.ipynb` — **NFSP**, a IA que *aprende* por rede neural.

Detalhes e fontes verificadas: `docs/superpowers/research/`.

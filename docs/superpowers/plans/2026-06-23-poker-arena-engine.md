# Poker Arena — Plano de Implementação: Fase 1 (Motor de Poker)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir um motor de Texas Hold'em No-Limit (6-max) correto e 100%
testado, que será a fundação de toda a Poker Arena.

**Architecture:** Backend Python puro, sem framework nesta fase. Lógica de jogo
própria (estado, apostas, pote, side pots) + biblioteca testada (`treys`) só para
avaliar/ranquear mãos. Desenvolvimento via TDD — cada regra nasce de um teste que
falha primeiro.

**Tech Stack:** Python 3.11 (via `uv`), `treys` (avaliação de mãos), `pytest`.

---

## Roadmap macro (visão da jornada inteira)

Cada fase é um plano próprio e entrega algo apresentável:

| Fase | Subsistema | Entrega | Plano |
|---|---|---|---|
| **1** | **Motor de poker** | Jogo de Hold'em correto, testado (CLI/headless) | **este documento** |
| 2 | Bots baseline | Random, Heuristic, MonteCarlo jogando no motor | a definir |
| 3 | Backend API | FastAPI + WebSocket servindo partidas ao vivo | a definir |
| 4 | Frontend React | Mesa de poker jogável e bonita | a definir |
| 5 | ML — NFSP (estrela) | IA treinada por self-play na nuvem, hospedada no HF | a definir |
| 6 | ML — Deep CFR (rigor) | Convergência/exploitability em jogos pequenos | a definir |
| 7 | Apresentação | Gráficos, pôster, demo final | a definir |

Spec de referência: `docs/superpowers/specs/2026-06-23-poker-arena-design.md`

---

## Estrutura de arquivos desta fase

```
backend/
  pyproject.toml
  poker_arena/
    __init__.py
    engine/
      __init__.py
      cards.py        # Rank, Suit, Card, Deck (shuffle com seed)
      evaluator.py    # wrapper sobre treys (ranquear/comparar mãos)
      actions.py      # tipos de ação (FOLD/CHECK/CALL/RAISE/ALL_IN)
      player.py       # estado do jogador (stack, hole cards, status)
      game.py         # estado da mão, rodadas de aposta, pote, side pots
  tests/
    engine/
      test_cards.py
      test_evaluator.py
      test_player.py
      test_betting.py
      test_side_pots.py
      test_full_hand.py
```

**Responsabilidade de cada arquivo:** uma só. `cards` não conhece apostas;
`game` orquestra; `evaluator` só ranqueia. Isso mantém cada unidade testável
isoladamente.

---

## Chunk 1: Fundação e cartas

### Task 1: Scaffold do projeto + ambiente

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/poker_arena/__init__.py`
- Create: `backend/poker_arena/engine/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/engine/__init__.py`

- [ ] **Step 1: Criar `backend/pyproject.toml`**

```toml
[project]
name = "poker-arena"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["treys>=0.1.8"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Criar o ambiente com `uv` (Python 3.11) e instalar**

Run:
```bash
cd backend
uv venv --python 3.11
uv pip install -e ".[dev]"
```
Expected: venv criado em `.venv`, `treys` e `pytest` instalados.
> Se `uv` não existir: `pip install uv` (ou usar `python3.11 -m venv .venv`).
> Não usar o Python 3.14 do sistema — `treys`/libs futuras de ML não têm wheel.

- [ ] **Step 3: Criar os `__init__.py` vazios** (os 4 listados acima).

- [ ] **Step 4: Sanity check do pytest**

Run: `uv run pytest -q`
Expected: "no tests ran" (sem erro de coleta).

- [ ] **Step 5: Commit**

```bash
git add backend/
git commit -m "chore: scaffold do backend (engine) + ambiente uv/3.11"
```

---

### Task 2: Cartas e baralho (`cards.py`)

**Files:**
- Create: `backend/poker_arena/engine/cards.py`
- Test: `backend/tests/engine/test_cards.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/engine/test_cards.py
from poker_arena.engine.cards import Card, Deck, Rank, Suit

def test_card_string_is_treys_compatible():
    assert str(Card(Rank.ACE, Suit.SPADES)) == "As"
    assert str(Card(Rank.TEN, Suit.HEARTS)) == "Th"
    assert str(Card(Rank.TWO, Suit.CLUBS)) == "2c"

def test_deck_has_52_unique_cards():
    deck = Deck()
    assert len(deck.cards) == 52
    assert len(set(str(c) for c in deck.cards)) == 52

def test_shuffle_is_deterministic_with_seed():
    a, b = Deck(seed=42), Deck(seed=42)
    a.shuffle(); b.shuffle()
    assert [str(c) for c in a.cards] == [str(c) for c in b.cards]

def test_deal_removes_cards_from_top():
    deck = Deck(seed=1); deck.shuffle()
    top2 = deck.cards[:2]
    dealt = deck.deal(2)
    assert dealt == top2
    assert len(deck.cards) == 50
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_cards.py -v`
Expected: FAIL (ImportError — módulo não existe).

- [ ] **Step 3: Implementar o mínimo**

```python
# poker_arena/engine/cards.py
from __future__ import annotations
import random
from dataclasses import dataclass
from enum import IntEnum, Enum

class Rank(IntEnum):
    TWO = 2; THREE = 3; FOUR = 4; FIVE = 5; SIX = 6; SEVEN = 7
    EIGHT = 8; NINE = 9; TEN = 10; JACK = 11; QUEEN = 12; KING = 13; ACE = 14

class Suit(Enum):
    SPADES = "s"; HEARTS = "h"; DIAMONDS = "d"; CLUBS = "c"

_RANK_CHAR = {10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}

@dataclass(frozen=True)
class Card:
    rank: Rank
    suit: Suit
    def __str__(self) -> str:
        r = _RANK_CHAR.get(int(self.rank), str(int(self.rank)))
        return f"{r}{self.suit.value}"

class Deck:
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)
        self.cards: list[Card] = [Card(r, s) for s in Suit for r in Rank]
    def shuffle(self) -> None:
        self._rng.shuffle(self.cards)
    def deal(self, n: int) -> list[Card]:
        dealt, self.cards = self.cards[:n], self.cards[n:]
        return dealt
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_cards.py -v`
Expected: PASS (4 testes).

- [ ] **Step 5: Commit**

```bash
git add backend/poker_arena/engine/cards.py backend/tests/engine/test_cards.py
git commit -m "feat(engine): cartas e baralho com shuffle deterministico"
```

---

### Task 3: Avaliador de mãos (`evaluator.py`)

Usa `treys` para ranquear. Em treys, **menor rank = mão melhor** (1 = royal
flush). Encapsulamos para o resto do código nunca falar com treys diretamente.

**Files:**
- Create: `backend/poker_arena/engine/evaluator.py`
- Test: `backend/tests/engine/test_evaluator.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/engine/test_evaluator.py
from poker_arena.engine.cards import Card, Rank, Suit
from poker_arena.engine.evaluator import evaluate, compare

def _c(s):  # helper: "As" -> Card
    from poker_arena.engine.evaluator import card_from_str
    return card_from_str(s)

def test_royal_flush_beats_pair():
    board = [_c("Ah"), _c("Kh"), _c("Qh"), _c("2c"), _c("3d")]
    royal = [_c("Jh"), _c("Th")]      # flush real
    pair  = [_c("Ad"), _c("Ac")]      # trinca de ases
    assert compare(royal, pair, board) > 0  # royal vence

def test_higher_pair_beats_lower_pair():
    board = [_c("2h"), _c("7d"), _c("9s"), _c("Jc"), _c("4h")]
    kings = [_c("Kh"), _c("Kd")]
    queens = [_c("Qh"), _c("Qd")]
    assert compare(kings, queens, board) > 0

def test_identical_hands_tie():
    board = [_c("2h"), _c("7d"), _c("9s"), _c("Jc"), _c("4h")]
    a = [_c("Ah"), _c("Kd")]
    b = [_c("As"), _c("Kc")]
    assert compare(a, b, board) == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_evaluator.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implementar o mínimo**

```python
# poker_arena/engine/evaluator.py
from __future__ import annotations
from treys import Card as TCard, Evaluator as TEvaluator
from .cards import Card

_EVAL = TEvaluator()

def card_from_str(s: str) -> Card:
    from .cards import Rank, Suit
    _R = {"T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
    rank = Rank(_R.get(s[0], int(s[0]) if s[0].isdigit() else 0) or int(s[0]))
    return Card(rank, Suit(s[1]))

def _t(card: Card) -> int:
    return TCard.new(str(card))

def evaluate(hole: list[Card], board: list[Card]) -> int:
    """Score treys: MENOR = melhor. Requer 5 cartas comunitarias."""
    return _EVAL.evaluate([_t(c) for c in board], [_t(c) for c in hole])

def compare(hole_a: list[Card], hole_b: list[Card], board: list[Card]) -> int:
    """+1 se A vence, -1 se B vence, 0 empate."""
    sa, sb = evaluate(hole_a, board), evaluate(hole_b, board)
    return (sb > sa) - (sa > sb)  # menor score vence
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_evaluator.py -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add backend/poker_arena/engine/evaluator.py backend/tests/engine/test_evaluator.py
git commit -m "feat(engine): avaliador de maos via treys (wrapper)"
```

---

## Chunk 2: Jogadores, ações e apostas

### Task 4: Jogador e ações (`player.py`, `actions.py`)

**Files:**
- Create: `backend/poker_arena/engine/actions.py`
- Create: `backend/poker_arena/engine/player.py`
- Test: `backend/tests/engine/test_player.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/engine/test_player.py
from poker_arena.engine.player import Player, PlayerStatus
from poker_arena.engine.actions import Action, ActionType

def test_player_starts_active_with_stack():
    p = Player(name="Bot1", stack=1000)
    assert p.stack == 1000
    assert p.status == PlayerStatus.ACTIVE
    assert p.current_bet == 0

def test_bet_reduces_stack_and_tracks_current_bet():
    p = Player(name="Bot1", stack=1000)
    p.bet(150)
    assert p.stack == 850
    assert p.current_bet == 150

def test_betting_entire_stack_marks_all_in():
    p = Player(name="Bot1", stack=200)
    p.bet(200)
    assert p.stack == 0
    assert p.status == PlayerStatus.ALL_IN

def test_action_raise_requires_amount():
    a = Action(ActionType.RAISE, amount=300)
    assert a.type == ActionType.RAISE and a.amount == 300
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/engine/test_player.py -v` → FAIL.

- [ ] **Step 3: Implementar o mínimo**

```python
# poker_arena/engine/actions.py
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class ActionType(Enum):
    FOLD = "fold"; CHECK = "check"; CALL = "call"
    RAISE = "raise"; ALL_IN = "all_in"

@dataclass(frozen=True)
class Action:
    type: ActionType
    amount: int = 0  # total apostado nesta rodada (para RAISE/ALL_IN)
```

```python
# poker_arena/engine/player.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from .cards import Card

class PlayerStatus(Enum):
    ACTIVE = "active"; FOLDED = "folded"; ALL_IN = "all_in"

@dataclass
class Player:
    name: str
    stack: int
    hole: list[Card] = field(default_factory=list)
    status: PlayerStatus = PlayerStatus.ACTIVE
    current_bet: int = 0
    total_committed: int = 0  # total na mao inteira (p/ side pots)

    def bet(self, amount: int) -> int:
        amount = min(amount, self.stack)
        self.stack -= amount
        self.current_bet += amount
        self.total_committed += amount
        if self.stack == 0:
            self.status = PlayerStatus.ALL_IN
        return amount

    def fold(self) -> None:
        self.status = PlayerStatus.FOLDED

    def reset_for_new_round(self) -> None:
        self.current_bet = 0
```

- [ ] **Step 4: Rodar e ver passar** — `uv run pytest tests/engine/test_player.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/poker_arena/engine/actions.py backend/poker_arena/engine/player.py backend/tests/engine/test_player.py
git commit -m "feat(engine): jogador (stack/all-in) e tipos de acao"
```

---

### Task 5: Estado da mão + distribuição (`game.py` — parte 1)

Cria a mão: botão, blinds, distribui hole cards. Sem rodada de aposta ainda.

**Files:**
- Create: `backend/poker_arena/engine/game.py`
- Test: `backend/tests/engine/test_betting.py` (começa aqui)

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/engine/test_betting.py
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player

def _players():
    return [Player(f"P{i}", 1000) for i in range(6)]

def test_blinds_are_posted():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    # SB = seat 1, BB = seat 2 (heads-up tem regra propria; aqui 6-max)
    assert h.players[1].current_bet == 10
    assert h.players[2].current_bet == 20
    assert h.pot == 30

def test_each_player_gets_two_hole_cards():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    assert all(len(p.hole) == 2 for p in h.players)

def test_first_to_act_preflop_is_left_of_big_blind():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    assert h.to_act == 3  # UTG, esquerda do BB
```

- [ ] **Step 2: Rodar e ver falhar** — FAIL (ImportError).

- [ ] **Step 3: Implementar o mínimo** (estrutura + `start()`)

```python
# poker_arena/engine/game.py
from __future__ import annotations
from .cards import Card, Deck
from .player import Player, PlayerStatus

class Hand:
    def __init__(self, players: list[Player], button: int,
                 small_blind: int, big_blind: int, seed: int | None = None):
        self.players = players
        self.button = button
        self.sb, self.bb = small_blind, big_blind
        self.deck = Deck(seed)
        self.board: list[Card] = []
        self.pot = 0
        self.to_act = 0
        self.current_bet = 0

    def _next_seat(self, seat: int) -> int:
        return (seat + 1) % len(self.players)

    def start(self) -> None:
        self.deck.shuffle()
        sb_seat = self._next_seat(self.button)
        bb_seat = self._next_seat(sb_seat)
        self._post(sb_seat, self.sb)
        self._post(bb_seat, self.bb)
        self.current_bet = self.bb
        for _ in range(2):
            for p in self.players:
                p.hole.extend(self.deck.deal(1))
        self.to_act = self._next_seat(bb_seat)

    def _post(self, seat: int, amount: int) -> None:
        self.pot += self.players[seat].bet(amount)
```

- [ ] **Step 4: Rodar e ver passar** — PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add backend/poker_arena/engine/game.py backend/tests/engine/test_betting.py
git commit -m "feat(engine): inicio da mao (botao, blinds, hole cards)"
```

---

### Task 6: Rodada de aposta (`game.py` — parte 2)

Aplicar ações, avançar a vez, detectar fim de rodada.

**Files:**
- Modify: `backend/poker_arena/engine/game.py`
- Test: `backend/tests/engine/test_betting.py` (acrescentar)

- [ ] **Step 1: Escrever os testes que falham**

```python
# acrescentar em tests/engine/test_betting.py
from poker_arena.engine.actions import Action, ActionType

def test_fold_marks_player_and_advances():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    actor = h.to_act
    h.apply(Action(ActionType.FOLD))
    assert h.players[actor].status.name == "FOLDED"

def test_call_matches_current_bet():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    seat = h.to_act
    h.apply(Action(ActionType.CALL))
    assert h.players[seat].current_bet == 20  # igualou o BB

def test_round_completes_when_all_matched():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    # todos pagam ate fechar a rodada preflop
    for _ in range(6):
        if not h.round_complete():
            h.apply(Action(ActionType.CALL))
    assert h.round_complete()
```

- [ ] **Step 2: Rodar e ver falhar** — FAIL (métodos `apply`/`round_complete`).

- [ ] **Step 3: Implementar `apply()` e `round_complete()`**

```python
# acrescentar a classe Hand em game.py
    def _active_seats(self) -> list[int]:
        return [i for i, p in enumerate(self.players)
                if p.status == PlayerStatus.ACTIVE]

    def apply(self, action: Action) -> None:
        seat = self.to_act
        p = self.players[seat]
        if action.type == ActionType.FOLD:
            p.fold()
        elif action.type == ActionType.CHECK:
            pass
        elif action.type == ActionType.CALL:
            self.pot += p.bet(self.current_bet - p.current_bet)
        elif action.type in (ActionType.RAISE, ActionType.ALL_IN):
            self.pot += p.bet(action.amount - p.current_bet)
            self.current_bet = max(self.current_bet, p.current_bet)
        p.acted = True
        self._advance()

    def _advance(self) -> None:
        nxt = self._next_seat(self.to_act)
        while self.players[nxt].status != PlayerStatus.ACTIVE:
            nxt = self._next_seat(nxt)
        self.to_act = nxt

    def round_complete(self) -> bool:
        active = [p for p in self.players if p.status == PlayerStatus.ACTIVE]
        if len(active) <= 1:
            return True
        return all(getattr(p, "acted", False) and p.current_bet == self.current_bet
                   for p in active)
```
> Adicionar `acted: bool = False` ao `Player` e resetá-lo em
> `reset_for_new_round`.

- [ ] **Step 4: Rodar e ver passar** — PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(engine): rodada de aposta (apply/advance/round_complete)"
```

---

## Chunk 3: Progressão, showdown e side pots

### Task 7: Progressão do board (flop/turn/river)

**Files:**
- Modify: `backend/poker_arena/engine/game.py`
- Test: `backend/tests/engine/test_betting.py`

- [ ] **Step 1: Teste que falha** — `advance_street()` lida flop(3)/turn(1)/river(1),
  reseta `current_bet` e `current_bet` dos players, e `to_act` vira o primeiro
  ativo à esquerda do botão.

```python
def test_advance_to_flop_deals_three_cards():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    for _ in range(6):
        if not h.round_complete(): h.apply(Action(ActionType.CALL))
    h.advance_street()
    assert len(h.board) == 3
    assert h.current_bet == 0
    assert all(p.current_bet == 0 for p in h.players)
```

- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar `advance_street()`** (burn opcional; lida 3/1/1 conforme
  `len(self.board)`; chama `reset_for_new_round` em todos; define `to_act`).
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5: Commit** — `feat(engine): progressao do board (flop/turn/river)`.

---

### Task 8: Showdown e vencedor (pote único)

**Files:**
- Modify: `backend/poker_arena/engine/game.py`
- Test: `backend/tests/engine/test_full_hand.py`

- [ ] **Step 1: Teste que falha** — com board completo, `showdown()` devolve o(s)
  vencedor(es) e credita o pote; fold de todos menos um dá vitória sem showdown.

```python
def test_last_player_standing_wins_pot():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    # todos foldam menos um
    for _ in range(5): h.apply(Action(ActionType.FOLD))
    winners = h.resolve()
    assert len(winners) == 1
    assert winners[0].stack > 1000 - 20  # recebeu o pote
```

- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar `showdown()` + `resolve()`** usando `evaluator.compare`
  para achar o(s) melhor(es) e dividir o pote.
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5: Commit** — `feat(engine): showdown e atribuicao de vencedor`.

---

### Task 9: Side pots (cenários de all-in)

O caso mais traiçoeiro do poker. Testes dedicados.

**Files:**
- Modify: `backend/poker_arena/engine/game.py`
- Test: `backend/tests/engine/test_side_pots.py`

- [ ] **Step 1: Teste que falha** — 3 jogadores, stacks 100/200/300, todos all-in;
  o de 100 só pode ganhar até 300 (100×3); o resto forma side pot entre os de
  200 e 300. Verificar distribuição exata por `total_committed`.

```python
def test_three_way_all_in_builds_side_pots():
    players = [Player("A", 100), Player("B", 200), Player("C", 300)]
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=7)
    h.start()
    # forcar all-ins (detalhe na implementacao)
    # ... A all-in 100, B all-in 200, C all-in 300 ...
    pots = h.build_side_pots()
    assert pots[0].amount == 300  # main pot: 100 de cada
    assert pots[1].amount == 200  # side 1: 100 de B e C
    assert pots[2].amount == 100  # side 2: so C
```

- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar `build_side_pots()`** a partir de `total_committed` de
  cada jogador (algoritmo de camadas por nível de contribuição) e ajustar
  `resolve()` para premiar cada pote ao melhor elegível.
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5: Commit** — `feat(engine): side pots para multiplos all-ins`.

---

### Task 10: Teste de integração — uma mão completa

**Files:**
- Test: `backend/tests/engine/test_full_hand.py`

- [ ] **Step 1: Teste que falha** — joga uma mão determinística (seed fixa) do
  preflop ao river com uma sequência de ações roteirizada; valida que a soma dos
  stacks finais = soma inicial (conservação de fichas) e que há exatamente 1 pote
  resolvido.

```python
def test_chips_are_conserved_over_a_full_hand():
    players = [Player(f"P{i}", 1000) for i in range(6)]
    start_total = sum(p.stack for p in players)
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=99)
    h.play_scripted([...])   # sequencia de Action determinística
    assert sum(p.stack for p in h.players) == start_total
```

- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar `play_scripted()`** (helper que percorre streets
  aplicando ações até resolver) — só o necessário p/ o teste passar.
- [ ] **Step 4: Ver passar** + rodar a suíte inteira: `uv run pytest -q` (tudo verde).
- [ ] **Step 5: Commit** — `test(engine): integracao de mao completa + conservacao de fichas`.

---

## Critério de pronto da Fase 1

- [ ] `uv run pytest -q` — toda a suíte verde.
- [ ] Cobertura do pacote `engine` ≥ 90% (`uv run pytest --cov=poker_arena/engine`).
- [ ] Conservação de fichas garantida por teste.
- [ ] Side pots cobertos por teste dedicado.
- [ ] Tudo commitado.

**Próximo plano:** Fase 2 — Bots baseline (Random, Heuristic, MonteCarlo) jogando
sobre este motor.

---

## Pós-auditoria (2026-06-23) — itens implementados além do plano original

Uma auditoria isenta apontou gaps; todos os críticos/médios foram corrigidos
nesta mesma fase (38 testes, ruff + mypy limpos):

| Item | O que foi feito |
|---|---|
| 1. Validação de ação | `legal_actions()` + `IllegalActionError`: rejeita CHECK ilegal e RAISE negativo |
| 2. Raise sem teste | `test_raises.py` cobre raise, re-raise, reabertura, ilegais |
| 3. Regras No-Limit | min-bet (≥ BB) e min-raise (≥ último incremento); all-in sempre legal |
| 4. **Sessão/múltiplas mãos** | nova `table.py` (`Table`): várias mãos, rotação de botão, fim de jogo |
| 5. Casos não testados | split/empate, ficha ímpar, run-out de board, heads-up |
| 6. `play_out` robusto | levanta erro se a rodada não converge (em vez de mascarar) |
| 7. Análise estática | ruff + mypy no loop, zero issues |

### Dívida técnica conhecida (simplificações documentadas, aceitáveis p/ a feira)
- **Direitos de reabertura:** um all-in "curto" (abaixo do min-raise) sobe a
  aposta a pagar, mas não trava o direito do raiser anterior de re-aumentar
  (regra fina de NL). Raríssimo importar numa demo.
- **Sem burn cards** e a distribuição não começa na small blind — cosmético
  (baralho embaralhado mantém a justiça).
- **`self.pot`** é só exibição; a resolução usa `total_committed` (fonte única).
- **`evaluator.compare`** ficou usado só em teste — manter para os bots da Fase 2.

---

## Pós-pesquisa (2026-06-23) — achados aplicados ao roadmap

Verificação na fonte + garimpo HF/Kaggle. Detalhe completo em
`docs/superpowers/research/2026-06-23-findings-and-sources.md`.

### Roadmap de ML revisado
| Fase | Antes | Depois (corrigido) |
|---|---|---|
| ML estrela | "NFSP via RLCard" | **NFSP via OpenSpiel** (RLCard não tem Deep CFR) |
| ML rigor | "Deep CFR" | **Deep CFR via OpenSpiel** + **exploitability** em Kuhn/Leduc |
| ML alternativa | — | **PPO self-play** (`stable-baselines3`) — mais simples, paper 2502.08938 |
| Avaliação 6-max | "exploitability" | **cross-play + bb/100 + IC + AIVAT** (6-max não tem garantia de equilíbrio) |

### Itens novos no backlog (com fase sugerida)
| Item | Fase | Esforço |
|---|---|---|
| `bots/` — contrato `Observation` filtrado por assento + `Bot` protocol | **2** (parcial já nesta branch) | baixo |
| Cache de equity com tabelas do Kaggle (`*_equity.csv`) p/ o MonteCarloBot | 2 | baixo |
| PokerKit como oráculo: cruzar 1M de mãos vs nosso motor | 2/3 | médio |
| Export PHH + event sourcing + replay determinístico | 3 | médio |
| Curriculum OpenSpiel: Kuhn (Nash fechado) → Leduc (exploitability) → Hold'em | 5 | alto |
| Matriz de cross-play (NFSP × Deep CFR × PPO × baselines) | 6 | médio |
| Treino em HF Jobs (`hf jobs uv run --flavor l4x4`) e/ou Kaggle | 5/6 | médio |
| Demo pública em HF Spaces/ZeroGPU | 7 | médio |
| Camada LLM de explicação (GGUF leve, tool-use; nunca decide) | 7 | médio |
| Eixo Personalidade (TAG/LAG/…) por mistura `α·forte+β·estilo+γ·erro` | 2/4 | médio |

### Disciplina de licença (requisito técnico)
Ficar em **MIT/Apache** (OpenSpiel, RLCard, PokerKit, treys, PokerBench,
stable-baselines3). **Evitar** AGPL (DecisionHoldem, TexasSolver, postflop-solver)
e CC-BY-NC (PokerSkill, Poker-SFT-Mix) em qualquer publicação/demo.

"""Parser do PokerBench (6-max NLHE com decisões de solver) para o NOSSO formato.

Reconstrói um `Observation` do motor a partir de um registro do PokerBench e usa o
mesmo `encode()` do self-play. O espaço vetorial é compartilhado, mas vários escalares
são reconstruções aproximadas e não equivalem ao estado original do solver.

Confiável (domina a decisão): cartas, board, posição, pote, máscara legal e a
ação-alvo do solver. Best-effort (aprox., minoria das features): to_call /
current_bet / min_raise_to / stack / num_active — derivados da linha de ações.
Como o BC é só um WARM-START que o self-play depois refina, a aproximação nesses
poucos campos é uma limitação explícita; o impacto precisa ser medido, não presumido.
"""

from __future__ import annotations

import math
import re
from typing import Any

from ..bots.observation import Observation, PublicPlayer
from ..engine.actions import ActionType
from ..engine.cards import Card, Rank, Suit
from .encoder import ACTIONS, encode, legal_mask

_RANK = {
    "two": Rank.TWO,
    "three": Rank.THREE,
    "four": Rank.FOUR,
    "five": Rank.FIVE,
    "six": Rank.SIX,
    "seven": Rank.SEVEN,
    "eight": Rank.EIGHT,
    "nine": Rank.NINE,
    "ten": Rank.TEN,
    "jack": Rank.JACK,
    "queen": Rank.QUEEN,
    "king": Rank.KING,
    "ace": Rank.ACE,
}
_SUIT = {"spade": Suit.SPADES, "heart": Suit.HEARTS, "diamond": Suit.DIAMONDS, "club": Suit.CLUBS}
_RANK_SYMBOL = {
    **{str(i): Rank(i) for i in range(2, 10)},
    "T": Rank.TEN,
    "J": Rank.JACK,
    "Q": Rank.QUEEN,
    "K": Rank.KING,
    "A": Rank.ACE,
}
_SUIT_SYMBOL = {s.value: s for s in Suit}
_COMPACT_CARD = re.compile(r"(10|[2-9TJQKA])\s*([shdc])", re.IGNORECASE)
POSITIONS = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
STARTING = 100  # PokerBench: "everyone started with 100 chips"


def parse_card(text: str) -> Card:
    """'King of Diamond' -> Card(KING, DIAMONDS). Case-insensitive, singular/plural."""
    words = re.findall(r"[a-z]+", text.lower())
    rank = next(_RANK[w] for w in words if w in _RANK)
    suit = next(_SUIT[w.rstrip("s")] for w in words if w.rstrip("s") in _SUIT)
    return Card(rank, suit)


def parse_cards(text: Any) -> list[Card]:
    """Lê uma ou várias cartas: 'King of Diamond and Jack of Spade', board, etc."""
    if text is None or not str(text).strip():
        return []
    value = str(text).strip()
    matches = list(_COMPACT_CARD.finditer(value))
    remainder = _COMPACT_CARD.sub("", value)
    if matches and not re.sub(r"[\s,;/|]+", "", remainder):
        compact: list[Card] = []
        for match in matches:
            rank_s, suit_s = match.groups()
            rank_s = "T" if rank_s.upper() == "10" else rank_s.upper()
            compact.append(Card(_RANK_SYMBOL[rank_s], _SUIT_SYMBOL[suit_s.lower()]))
        return compact
    out: list[Card] = []
    for chunk in re.split(r",|\band\b", value):
        if any(w in chunk.lower() for w in _RANK):
            out.append(parse_card(chunk))
    return out


def bucket_action(text: str, pot: int, stack: int) -> int:
    """Ação do solver ('bet 18', 'raise 13', 'call'...) -> índice das nossas 5 ações."""
    t = text.strip().lower()
    if t.startswith("fold"):
        return ACTIONS.index("fold")
    if t.startswith("check") or t.startswith("call"):
        return ACTIONS.index("check_call")
    if re.search(r"\ball[\s_-]?in\b", t):
        return ACTIONS.index("all_in")
    m = re.search(r"\d+(?:\.\d+)?", t)
    amount = float(m.group()) if m else float(pot)
    if stack > 0 and amount >= stack * 0.95:
        return ACTIONS.index("all_in")
    if amount <= pot * 0.75:
        return ACTIONS.index("raise_half")
    return ACTIONS.index("raise_pot")


def legal_from_moves(moves: Any) -> set[ActionType]:
    s = str(moves).lower()
    legal: set[ActionType] = set()
    if "fold" in s:
        legal.add(ActionType.FOLD)
    if "check" in s:
        legal.add(ActionType.CHECK)
    if "call" in s:
        legal.add(ActionType.CALL)
    if "raise" in s or "bet" in s:
        legal.add(ActionType.RAISE)
    if re.search(r"(?:^|['\"\s,\[])\d+(?:[.,]\d+)?\s*(?:bb|chips?)?(?=['\"\s,\]]|$)", s):
        legal.add(ActionType.RAISE)
    if re.search(r"all[\s_-]?in", s):  # evita casar com 'call'
        legal.add(ActionType.ALL_IN)
    return legal


def _field(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if row.get(k) not in (None, ""):
            return row[k]
    return None


def _legal_for_target(legal: set[ActionType], target: int) -> frozenset[ActionType]:
    """Garante que a ação-alvo é legal na máscara (consistência treino/benchmark)."""
    accepted = {
        0: {ActionType.FOLD},
        1: {ActionType.CHECK, ActionType.CALL},
        2: {ActionType.RAISE},
        3: {ActionType.RAISE},
        4: {ActionType.ALL_IN, ActionType.RAISE},
    }[target]
    if not (legal & accepted):
        raise ValueError(
            f"correct_decision bucket {ACTIONS[target]!r} is absent from available_moves "
            f"({sorted(a.value for a in legal)!r})"
        )
    if target == 4 and ActionType.ALL_IN not in legal:
        legal = set(legal) | {ActionType.ALL_IN}
    return frozenset(legal)


def row_to_observation(row: dict[str, Any]) -> tuple[Observation, int]:
    """Registro do PokerBench -> (Observation reconstruída, índice da ação-alvo)."""
    hole = parse_cards(_field(row, "holding", "hero_holding"))
    board = (
        parse_cards(_field(row, "board_flop"))
        + parse_cards(_field(row, "board_turn"))
        + parse_cards(_field(row, "board_river"))
    )
    if len(hole) != 2:
        raise ValueError(f"holding must contain exactly 2 cards, got {len(hole)}")
    if len(board) not in (0, 3, 4, 5):
        raise ValueError(f"board must contain 0/3/4/5 cards, got {len(board)}")
    cards = hole + board
    if len(set(cards)) != len(cards):
        raise ValueError("duplicate card in holding/board")

    raw_pot = float(_field(row, "pot_size") or 0)
    if not math.isfinite(raw_pot) or raw_pot < 0:
        raise ValueError(f"invalid pot_size: {raw_pot!r}")
    pot = int(round(raw_pot))

    raw_position = _field(row, "hero_position", "hero_pos")
    if not isinstance(raw_position, str) or not raw_position.strip():
        raise ValueError("hero_position is required")
    pos = raw_position.strip().upper()
    if pos not in POSITIONS:
        raise ValueError(f"unsupported hero_position: {pos!r}")
    n = len(POSITIONS)
    hero_seat = POSITIONS.index(pos)
    btn_seat = POSITIONS.index("BTN")

    # escalares best-effort, derivados da linha de ações
    line = " ".join(
        str(_field(row, k) or "") for k in ("prev_line", "preflop_action", "postflop_action")
    ).lower()
    amounts = re.findall(r"(?:bet|raise)\s+(\d+(?:\.\d+)?)", line)
    current_bet = int(round(float(amounts[-1]))) if amounts else 0
    to_call = current_bet
    min_raise_to = min(current_bet * 2 if current_bet else 2, STARTING)
    hero_stack = max(1, STARTING - to_call)
    num_active = max(2, n - line.count("fold"))

    decision = str(_field(row, "correct_decision", "output") or "fold")
    target = bucket_action(decision, pot, hero_stack)
    legal = _legal_for_target(legal_from_moves(_field(row, "available_moves")), target)

    others = [i for i in range(n) if i != hero_seat]
    each = max(0, n * STARTING - pot - hero_stack) // max(1, len(others))
    players = tuple(
        PublicPlayer(
            seat=i,
            name=POSITIONS[i],
            stack=hero_stack if i == hero_seat else each,
            current_bet=0,
            total_committed=0,
            status="active",
            is_button=(i == btn_seat),
        )
        for i in range(n)
    )
    obs = Observation(
        seat=hero_seat,
        hole=tuple(hole),
        board=tuple(board),
        pot=pot,
        to_call=to_call,
        current_bet=current_bet,
        min_raise_to=min_raise_to,
        legal_actions=legal,
        players=players,
        num_active=num_active,
    )
    return obs, target


def featurize(row: dict[str, Any]) -> tuple[list[float], list[bool], int]:
    """Registro -> (features p/ a rede, máscara legal, ação-alvo do solver)."""
    obs, target = row_to_observation(row)
    return encode(obs), legal_mask(obs), target

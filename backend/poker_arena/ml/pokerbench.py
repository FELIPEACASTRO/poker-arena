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
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any

from ..bots.observation import Observation, PublicPlayer
from ..engine.actions import ActionType
from ..engine.cards import Card, Rank, Suit
from ..engine.game import PublicActionEvent
from .action_space_v2 import ACTIONS_V2, legal_mask_v2, to_action_v2
from .encoder import ACTIONS, encode, legal_mask
from .encoder_v2 import EncodedObservationV2, encode_v2

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
POSTFLOP_POSITION_RANK = {"SB": 0, "BB": 1, "UTG": 2, "HJ": 3, "CO": 4, "BTN": 5}
STARTING = 100  # PokerBench: "everyone started with 100 chips"
MONEY_SCALE = 10
V2_STARTING = STARTING * MONEY_SCALE
SMALL_BLIND = 5
BIG_BLIND = 10
# Temporary warm-start compatibility bound. A non-zero gap is a parser/data
# approximation, not evidence of rake or a fully reconstructed solver state.
MAX_RECONSTRUCTED_POT_GAP = 150
# Development scan: p99=0.09036; 10% rejects the distorted tail without
# consulting the sealed holdout labels or the published test for selection.
MAX_TARGET_SIZING_RELATIVE_ERROR = 0.10


@dataclass(frozen=True, slots=True)
class HistoryParseAudit:
    raw_lines: int
    expected_action_tokens: int
    emitted_action_events: int
    forced_events: int
    ignored_action_tokens: int
    unknown_actor_events: int
    dealt_cards: int
    reconstructed_pot_units: int = 0
    reported_pot_units: int = 0

    @property
    def fidelity(self) -> float:
        if self.expected_action_tokens == 0:
            return 1.0
        return self.emitted_action_events / self.expected_action_tokens


@dataclass(frozen=True, slots=True)
class PokerBenchV2Example:
    observation: Observation
    encoded: EncodedObservationV2
    target_index: int
    sizing_relative_error: float
    mapping_ambiguous: bool
    history_audit: HistoryParseAudit


@dataclass(frozen=True, slots=True)
class PokerBenchV2Input:
    observation: Observation
    encoded: EncodedObservationV2
    history_audit: HistoryParseAudit


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


def _board_cards(row: dict[str, Any]) -> list[Card]:
    """Expose only cards dealt at the labelled decision street (no future leakage)."""

    evaluation_at = str(_field(row, "evaluation_at") or "").strip().lower()
    board = parse_cards(_field(row, "board_flop"))
    if evaluation_at not in {"flop"}:
        board += parse_cards(_field(row, "board_turn"))
    if evaluation_at not in {"flop", "turn"}:
        board += parse_cards(_field(row, "board_river"))
    return board


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
    board = _board_cards(row)
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


def _v2_position_context(row: dict[str, Any]) -> tuple[int, int, int]:
    raw_position = _field(row, "hero_position", "hero_pos")
    if not isinstance(raw_position, str) or not raw_position.strip():
        raise ValueError("hero_position is required")
    position = raw_position.strip().upper()
    if position in {"OOP", "IP"}:
        return 2, 0 if position == "OOP" else 1, 1
    if position not in POSITIONS:
        raise ValueError(f"unsupported hero_position: {position!r}")
    return len(POSITIONS), POSITIONS.index(position), POSITIONS.index("BTN")


def _money_units(text: Any) -> int:
    """Convert a PokerBench decimal blind amount to exact integer tenths."""

    match = re.search(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)(?![A-Za-z0-9.])", str(text))
    if match is None:
        raise ValueError(f"PokerBench monetary amount is absent: {text!r}")
    try:
        scaled = Decimal(match.group(1)) * MONEY_SCALE
    except InvalidOperation as exc:
        raise ValueError(f"invalid PokerBench monetary amount: {text!r}") from exc
    rounded = scaled.to_integral_value()
    if not scaled.is_finite() or abs(scaled - rounded) > Decimal("0.000001") or scaled < 0:
        raise ValueError(f"PokerBench amount exceeds 0.1bb precision: {text!r}")
    return int(rounded)


def _history_action(token: str) -> tuple[str, int | None] | None:
    """Parse only complete action tokens; card tokens such as ``7c`` never match."""

    normalized = re.sub(r"\s+", "", token.strip().lower().replace("-", "_"))
    if normalized == "fold":
        return "fold", None
    if normalized == "check":
        return "check", None
    if normalized == "call":
        return "call", None
    if normalized in {"allin", "all_in"}:
        return "all_in", None
    match = re.fullmatch(r"(?:bet|raise)_?(\d+(?:\.\d+)?)(?:bb|chips?)?", normalized)
    if match is None:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:bb|chips?)?", normalized)
    if match is not None:
        return "raise", _money_units(match.group(1))
    return None


@dataclass(slots=True)
class _HistoryState:
    bets: dict[str, int]
    totals: dict[str, int]
    statuses: dict[str, str]
    current_bet: int
    last_raise_size: int
    pot: int


def _new_preflop_state() -> _HistoryState:
    bets = dict.fromkeys(POSITIONS, 0)
    totals = dict.fromkeys(POSITIONS, 0)
    statuses = dict.fromkeys(POSITIONS, "active")
    bets["SB"] = totals["SB"] = SMALL_BLIND
    bets["BB"] = totals["BB"] = BIG_BLIND
    return _HistoryState(bets, totals, statuses, BIG_BLIND, BIG_BLIND, 15)


def _apply_history_action(
    state: _HistoryState,
    *,
    actor: str,
    seat: int,
    street: str,
    action: str,
    declared_amount: int | None,
) -> PublicActionEvent:
    before = state.bets.setdefault(actor, 0)
    state.totals.setdefault(actor, 0)
    state.statuses.setdefault(actor, "active")
    to_call_before = max(0, state.current_bet - before)
    pot_before = state.pot
    amount_added = 0
    raise_to: int | None = None
    is_full_raise = False
    if action == "fold":
        state.statuses[actor] = "folded"
    elif action == "call":
        amount_added = min(to_call_before, max(0, V2_STARTING - state.totals[actor]))
    elif action in {"raise", "all_in"}:
        max_to = before + max(0, V2_STARTING - state.totals[actor])
        raise_to = max_to if action == "all_in" and declared_amount is None else declared_amount
        if raise_to is None or raise_to <= before:
            raise ValueError("PokerBench raise-to amount does not increase the wager")
        raise_to = min(raise_to, max_to)
        amount_added = raise_to - before
        raise_size = raise_to - state.current_bet
        is_full_raise = raise_size >= state.last_raise_size and raise_to > state.current_bet
        if is_full_raise:
            state.last_raise_size = raise_size
        state.current_bet = max(state.current_bet, raise_to)
    state.bets[actor] += amount_added
    state.totals[actor] += amount_added
    state.pot += amount_added
    if state.totals[actor] == V2_STARTING:
        state.statuses[actor] = "all_in"
    return PublicActionEvent(
        seat=seat,
        street=street,
        action=action,
        amount_added=amount_added,
        raise_to=raise_to,
        pot_before=pot_before,
        to_call_before=to_call_before,
        is_full_raise=is_full_raise,
        is_forced=False,
    )


def _preflop_pairs(raw: str) -> tuple[list[tuple[str, str]], int]:
    if not raw.strip():
        return [], 0
    if "/" in raw:
        tokens = [token.strip() for token in raw.split("/") if token.strip()]
        pairs: list[tuple[str, str]] = []
        ignored = 0
        index = 0
        while index < len(tokens):
            actor = re.sub(r"\s+", "", tokens[index].upper())
            if index + 1 >= len(tokens):
                ignored += 1
                break
            action_token = tokens[index + 1]
            if actor not in POSITIONS or _history_action(action_token) is None:
                ignored += 1
            else:
                pairs.append((actor, action_token))
            index += 2
        return pairs, ignored
    pattern = re.compile(
        r"\b(UTG|HJ|CO|BTN|SB|BB)\s+"
        r"(fold|check|call|all[\s_-]?in|(?:bet|raise)\s+\d+(?:\.\d+)?\s*(?:bb|chips?)?)",
        re.IGNORECASE,
    )
    pairs = [(match.group(1).upper(), match.group(2)) for match in pattern.finditer(raw)]
    action_words = len(re.findall(r"\b(?:fold|check|call|all[\s_-]?in|bet|raise)\b", raw, re.I))
    return pairs, max(0, action_words - len(pairs))


def _published_preflop_roster(
    row: dict[str, Any], raw: str, hero_position: str
) -> frozenset[str] | None:
    """Validate the CSV's participant count without inventing active players.

    PokerBench's structured pre-flop rows define ``num_players`` as the number
    of distinct positions represented by the prior line plus the hero.  The
    natural-language contract also says every unmentioned position folded.
    Older hand-authored fixtures may omit the field, in which case the legacy
    six-seat best-effort reconstruction remains available.
    """

    raw_count = _field(row, "num_players")
    if raw_count is None:
        return None
    normalized = str(raw_count).strip()
    if re.fullmatch(r"[1-6]", normalized) is None:
        raise ValueError("PokerBench num_players must be an integer in [1, 6]")
    pairs, ignored = _preflop_pairs(raw)
    if ignored:
        raise ValueError("PokerBench participant roster contains an unparsed action")
    roster = {actor for actor, _token in pairs}
    roster.add(hero_position)
    if len(roster) != int(normalized):
        raise ValueError("PokerBench num_players contradicts the represented positions")
    return frozenset(roster)


def _parse_preflop(
    raw: str, *, complete_to_flop: bool = False
) -> tuple[list[PublicActionEvent], _HistoryState, HistoryParseAudit]:
    state = _new_preflop_state()
    pairs, ignored = _preflop_pairs(raw)
    events = [
        PublicActionEvent(4, "preflop", "post_sb", SMALL_BLIND, None, 0, 0, False, True),
        PublicActionEvent(5, "preflop", "post_bb", BIG_BLIND, None, SMALL_BLIND, 0, False, True),
    ]
    for actor, token in pairs:
        parsed = _history_action(token)
        if parsed is None:
            ignored += 1
            continue
        action, amount = parsed
        events.append(
            _apply_history_action(
                state,
                actor=actor,
                seat=POSITIONS.index(actor),
                street="preflop",
                action=action,
                declared_amount=amount,
            )
        )
    if complete_to_flop:
        participants = {actor for actor, _token in pairs}
        for position in POSITIONS:
            if position not in participants:
                state.statuses[position] = "folded"
    audit = HistoryParseAudit(
        raw_lines=int(bool(raw.strip())),
        expected_action_tokens=len(pairs) + ignored,
        emitted_action_events=len(events) - 2,
        forced_events=2,
        ignored_action_tokens=ignored,
        unknown_actor_events=0,
        dealt_cards=0,
    )
    return events, state, audit


def _map_preflop_to_roles(
    events: list[PublicActionEvent], state: _HistoryState
) -> tuple[list[PublicActionEvent], dict[str, int]]:
    active = [
        name for name in POSITIONS if state.statuses[name] != "folded" and state.totals[name] > 0
    ]
    mapping: dict[str, int] = {}
    if len(active) == 2:
        ip_actor = max(active, key=POSTFLOP_POSITION_RANK.__getitem__)
        mapping[ip_actor] = 1
        mapping[next(name for name in active if name != ip_actor)] = 0
    translated = []
    for event in events:
        mapped_seat = mapping.get(POSITIONS[event.seat], -1)
        if mapped_seat == -1 and event.is_forced:
            continue
        translated.append(
            PublicActionEvent(
                seat=mapped_seat,
                street=event.street,
                action=event.action,
                amount_added=event.amount_added,
                raise_to=event.raise_to,
                pot_before=event.pot_before,
                to_call_before=event.to_call_before,
                is_full_raise=event.is_full_raise,
                is_forced=event.is_forced,
            )
        )
    return translated, mapping


def _parse_postflop(
    raw: str,
    *,
    board_size: int,
    expected_dealt_cards: tuple[str, ...],
    initial_pot: int,
    initial_totals: dict[str, int],
) -> tuple[list[PublicActionEvent], _HistoryState, HistoryParseAudit]:
    roles = ("OOP", "IP")
    state = _HistoryState(
        bets=dict.fromkeys(roles, 0),
        totals={role: initial_totals.get(role, 0) for role in roles},
        statuses=dict.fromkeys(roles, "active"),
        current_bet=0,
        last_raise_size=BIG_BLIND,
        pot=initial_pot,
    )
    tokens = [token.strip() for token in raw.split("/") if token.strip()]
    maximum_street = {3: 1, 4: 2, 5: 3}[board_size]
    streets = ("preflop", "flop", "turn", "river")
    street_index = 1
    expected = ignored = dealt = 0
    events: list[PublicActionEvent] = []
    skip_card = False
    for token in tokens:
        compact = re.sub(r"\s+", "", token.upper())
        if skip_card:
            if re.fullmatch(r"(?:10|[2-9TJQKA])[SHDC]", compact):
                parsed_cards = parse_cards(compact)
                if len(parsed_cards) != 1 or dealt >= len(expected_dealt_cards):
                    raise ValueError("PokerBench history dealt an unexpected public card")
                if str(parsed_cards[0]) != expected_dealt_cards[dealt]:
                    raise ValueError("PokerBench history card contradicts the published board")
                dealt += 1
                skip_card = False
                continue
            ignored += 1
            skip_card = False
        if compact == "DEALCARDS":
            street_index += 1
            if street_index > maximum_street:
                raise ValueError("PokerBench history crosses beyond the labelled decision street")
            state.bets = dict.fromkeys(roles, 0)
            state.current_bet = 0
            state.last_raise_size = BIG_BLIND
            skip_card = True
            continue
        direct = re.fullmatch(
            r"(OOP|IP)_(FOLD|CHECK|CALL|ALL[_-]?IN|BET(?:_\d+(?:\.\d+)?)?|RAISE(?:_\d+(?:\.\d+)?)?)",
            compact,
        )
        if direct is None:
            ignored += 1
            continue
        expected += 1
        actor, action_token = direct.groups()
        parsed = _history_action(action_token)
        if parsed is None:
            ignored += 1
            continue
        action, amount = parsed
        events.append(
            _apply_history_action(
                state,
                actor=actor,
                seat=0 if actor == "OOP" else 1,
                street=streets[street_index],
                action=action,
                declared_amount=amount,
            )
        )
    if skip_card or dealt != len(expected_dealt_cards):
        raise ValueError("PokerBench history is missing a labelled public card transition")
    audit = HistoryParseAudit(
        raw_lines=int(bool(raw.strip())),
        expected_action_tokens=expected + ignored,
        emitted_action_events=len(events),
        forced_events=0,
        ignored_action_tokens=ignored,
        unknown_actor_events=0,
        dealt_cards=dealt,
    )
    return events, state, audit


def _merge_audits(*audits: HistoryParseAudit, unknown_actor_events: int = 0) -> HistoryParseAudit:
    return HistoryParseAudit(
        raw_lines=sum(audit.raw_lines for audit in audits),
        expected_action_tokens=sum(audit.expected_action_tokens for audit in audits),
        emitted_action_events=sum(audit.emitted_action_events for audit in audits),
        forced_events=sum(audit.forced_events for audit in audits),
        ignored_action_tokens=sum(audit.ignored_action_tokens for audit in audits),
        unknown_actor_events=unknown_actor_events,
        dealt_cards=sum(audit.dealt_cards for audit in audits),
    )


def _v2_observation(row: dict[str, Any]) -> tuple[Observation, HistoryParseAudit]:
    hole = parse_cards(_field(row, "holding", "hero_holding"))
    has_published_board = any(
        _field(row, key) is not None for key in ("board_flop", "board_turn", "board_river")
    )
    evaluation_at = str(_field(row, "evaluation_at") or "").strip().lower()
    if has_published_board and evaluation_at not in {"flop", "turn", "river"}:
        raise ValueError("PokerBench post-flop row requires an explicit decision street")
    board = _board_cards(row)
    expected_board_size = {"flop": 3, "turn": 4, "river": 5}.get(evaluation_at, 0)
    if has_published_board and len(board) != expected_board_size:
        raise ValueError("PokerBench board does not match the labelled decision street")
    if (
        len(hole) != 2
        or len(board) not in (0, 3, 4, 5)
        or len(set(hole + board)) != len(hole + board)
    ):
        raise ValueError("PokerBench cards do not form a legal public observation")
    pot = _money_units(_field(row, "pot_size") or 0)
    table_size, hero_seat, button_seat = _v2_position_context(row)
    legal = legal_from_moves(_field(row, "available_moves"))
    preflop_raw = str(_field(row, "prev_line", "preflop_action") or "")
    preflop_events, preflop_state, preflop_audit = _parse_preflop(
        preflop_raw, complete_to_flop=table_size == 2
    )
    if table_size != 2:
        hero_position = POSITIONS[hero_seat]
        published_roster = _published_preflop_roster(row, preflop_raw, hero_position)
        if published_roster is not None:
            for position in POSITIONS:
                if position not in published_roster:
                    preflop_state.statuses[position] = "folded"
    names: tuple[str, ...]
    if table_size == 2:
        translated, mapping = _map_preflop_to_roles(preflop_events, preflop_state)
        unknown = sum(event.seat == -1 for event in translated)
        preflop_audit = replace(
            preflop_audit,
            forced_events=sum(event.is_forced for event in translated),
        )
        totals_by_role = {
            role: sum(preflop_state.totals[name] for name, seat in mapping.items() if seat == index)
            for index, role in enumerate(("OOP", "IP"))
        }
        postflop_events, state, postflop_audit = _parse_postflop(
            str(_field(row, "postflop_action") or ""),
            board_size=len(board),
            expected_dealt_cards=tuple(str(card) for card in board[3:]),
            initial_pot=preflop_state.pot,
            initial_totals=totals_by_role,
        )
        history = tuple(translated + postflop_events)
        audit = _merge_audits(
            preflop_audit,
            postflop_audit,
            unknown_actor_events=unknown,
        )
        names = ("OOP", "IP")
    else:
        state = preflop_state
        history = tuple(preflop_events)
        audit = preflop_audit
        names = POSITIONS
    if audit.ignored_action_tokens:
        raise ValueError("PokerBench history contains unparsed action tokens")
    audit = replace(
        audit,
        reconstructed_pot_units=state.pot,
        reported_pot_units=pot,
    )
    pot_gap = audit.reconstructed_pot_units - audit.reported_pot_units
    if not 0 <= pot_gap <= MAX_RECONSTRUCTED_POT_GAP:
        raise ValueError("PokerBench reconstructed pot is inconsistent with the published pot")
    hero_name = names[hero_seat]
    hero_bet = state.bets[hero_name]
    current_bet = state.current_bet
    to_call = max(0, current_bet - hero_bet) if ActionType.CALL in legal else 0
    derived_min_raise = current_bet + max(state.last_raise_size, BIG_BLIND)
    available_raise_targets = []
    for value in re.findall(r"\d+(?:\.\d+)?", str(_field(row, "available_moves") or "")):
        amount = _money_units(value)
        if amount > current_bet:
            available_raise_targets.append(amount)
    min_raise_to = min(available_raise_targets) if available_raise_targets else derived_min_raise
    players = tuple(
        PublicPlayer(
            seat=seat,
            name=name,
            stack=max(0, V2_STARTING - state.totals[name]),
            current_bet=state.bets[name],
            total_committed=state.totals[name],
            status=state.statuses[name],
            is_button=seat == button_seat,
        )
        for seat, name in enumerate(names)
    )
    hero = players[hero_seat]
    if available_raise_targets and max(available_raise_targets) >= hero.current_bet + hero.stack:
        legal.add(ActionType.ALL_IN)
    observation = Observation(
        seat=hero_seat,
        hole=tuple(hole),
        board=tuple(board),
        pot=pot,
        to_call=to_call,
        current_bet=current_bet,
        min_raise_to=min_raise_to,
        legal_actions=frozenset(legal),
        players=players,
        num_active=sum(player.status != "folded" for player in players),
        history=history,
    )
    return observation, audit


def _v2_target(decision: str, observation: Observation) -> tuple[int, float, bool]:
    normalized = decision.strip().lower()
    if normalized.startswith("fold"):
        return 0, 0.0, False
    if normalized.startswith("check") or normalized.startswith("call"):
        return 1, 0.0, False
    if re.search(r"all[\s_-]?in", normalized):
        if not legal_mask_v2(observation)[9]:
            raise ValueError("PokerBench all-in target is absent from the reconstructed mask")
        return 9, 0.0, False
    amount_match = re.search(r"\d+(?:\.\d+)?", normalized)
    if amount_match is None:
        raise ValueError(f"unsupported PokerBench v2 decision: {decision!r}")
    target_amount = _money_units(amount_match.group())
    hero = observation.players[observation.seat]
    if target_amount >= hero.current_bet + hero.stack and legal_mask_v2(observation)[9]:
        return 9, abs(target_amount - hero.current_bet - hero.stack) / max(target_amount, 1), False
    candidates: list[tuple[float, int]] = []
    for index, enabled in enumerate(legal_mask_v2(observation)):
        if not enabled or not 2 <= index <= 8:
            continue
        action = to_action_v2(observation, index)
        candidates.append((abs(action.amount - target_amount), index))
    if not candidates:
        raise ValueError("PokerBench raise target has no legal v2 sizing")
    candidates.sort()
    distance, target = candidates[0]
    relative_error = distance / max(target_amount, 1)
    ambiguous = relative_error > MAX_TARGET_SIZING_RELATIVE_ERROR or (
        len(candidates) > 1 and math.isclose(candidates[0][0], candidates[1][0], abs_tol=1e-9)
    )
    return target, relative_error, ambiguous


def featurize_v2_input(row: dict[str, Any]) -> PokerBenchV2Input:
    """Build public inputs without consulting the solver's decision label."""

    observation, history_audit = _v2_observation(row)
    return PokerBenchV2Input(
        observation=observation,
        encoded=encode_v2(observation),
        history_audit=history_audit,
    )


def target_v2(row: dict[str, Any], observation: Observation) -> tuple[int, float, bool]:
    """Read and map the solver label only after partition assignment."""

    decision = str(_field(row, "correct_decision", "output") or "")
    target, error, ambiguous = _v2_target(decision, observation)
    mask = legal_mask_v2(observation)
    if not mask[target]:
        raise ValueError(f"PokerBench v2 target {ACTIONS_V2[target]!r} is masked")
    return target, error, ambiguous


def featurize_v2(row: dict[str, Any]) -> PokerBenchV2Example:
    """Map one solver-labelled row while exposing sizing approximation error."""

    inputs = featurize_v2_input(row)
    target, error, ambiguous = target_v2(row, inputs.observation)
    return PokerBenchV2Example(
        observation=inputs.observation,
        encoded=inputs.encoded,
        target_index=target,
        sizing_relative_error=error,
        mapping_ambiguous=ambiguous,
        history_audit=inputs.history_audit,
    )

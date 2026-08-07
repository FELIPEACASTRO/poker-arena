"""Independent differential adapter between Poker Arena and PokerKit.

The adapter translates only public actions and seat numbering.  It deliberately
does not reuse betting, pot, or hand-ranking logic from the production engine.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from pokerkit import Automation, NoLimitTexasHoldem
from pokerkit.state import State

from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.cards import Deck
from poker_arena.engine.evaluator import card_from_str
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player

SMALL_BLIND = 10
BIG_BLIND = 20

# Burn cards are supplied explicitly so the two engines consume the exact same
# cards.  All unrelated bookkeeping remains automated by PokerKit.
_AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
)


class StepKind(StrEnum):
    CHECK_OR_CALL = "check_or_call"
    FOLD = "fold"
    RAISE_TO = "raise_to"
    ALL_IN = "all_in"


@dataclass(frozen=True)
class Step:
    kind: StepKind
    amount: int | None = None


def check_or_call() -> Step:
    return Step(StepKind.CHECK_OR_CALL)


def fold() -> Step:
    return Step(StepKind.FOLD)


def raise_to(amount: int) -> Step:
    return Step(StepKind.RAISE_TO, amount)


def all_in() -> Step:
    return Step(StepKind.ALL_IN)


@dataclass(frozen=True)
class DealPlan:
    """Cards indexed by the physical seats used by the internal engine."""

    holes: tuple[str, ...]
    board: str
    burns: tuple[str, str, str]


@dataclass(frozen=True)
class DifferentialResult:
    internal_stacks: tuple[int, ...]
    pokerkit_stacks: tuple[int, ...]
    actor_trace: tuple[int, ...]
    board: tuple[str, ...]
    pot_amounts: tuple[int, ...]


def _canonical_to_physical(player_count: int, button: int) -> tuple[int, ...]:
    """Map PokerKit's fixed button layout to arbitrary physical seats.

    For 3+ players PokerKit uses SB=0, BB=1, button=n-1.  In heads-up it
    correctly swaps blind order: BB=0 and button/SB=1.
    """

    if player_count == 2:
        return ((button + 1) % 2, button)
    return tuple((button + 1 + offset) % player_count for offset in range(player_count))


def _state(stacks: list[int], canonical_to_physical: tuple[int, ...]) -> State:
    canonical_stacks = tuple(stacks[seat] for seat in canonical_to_physical)
    return NoLimitTexasHoldem.create_state(
        _AUTOMATIONS,
        True,
        0,
        (SMALL_BLIND, BIG_BLIND),
        BIG_BLIND,
        canonical_stacks,
        len(stacks),
    )


def _split_cards(compact: str) -> list[str]:
    if len(compact) % 2:
        raise ValueError(f"invalid compact cards: {compact!r}")
    return [compact[index : index + 2] for index in range(0, len(compact), 2)]


def _install_deal(hand: Hand, plan: DealPlan) -> None:
    if len(plan.holes) != len(hand.players):
        raise ValueError("deal plan must contain one two-card hand per player")
    board = _split_cards(plan.board)
    if len(board) != 5 or any(len(_split_cards(hole)) != 2 for hole in plan.holes):
        raise ValueError("Texas Hold'em requires two hole cards and five board cards")

    for player, compact in zip(hand.players, plan.holes, strict=True):
        player.hole = [card_from_str(card) for card in _split_cards(compact)]

    future = [
        plan.burns[0],
        *board[:3],
        plan.burns[1],
        board[3],
        plan.burns[2],
        board[4],
    ]
    used = {card for compact in plan.holes for card in _split_cards(compact)}
    used.update(future)
    if len(used) != (2 * len(plan.holes)) + 8:
        raise ValueError("deal plan contains duplicate cards")

    remaining = [card for card in Deck(seed=0).cards if str(card) not in used]
    hand.deck.cards = [card_from_str(card) for card in future] + remaining


def _apply_internal(hand: Hand, step: Step) -> None:
    if step.kind is StepKind.CHECK_OR_CALL:
        action_type = (
            ActionType.CHECK if ActionType.CHECK in hand.legal_actions() else ActionType.CALL
        )
        hand.apply(Action(action_type))
    elif step.kind is StepKind.FOLD:
        hand.apply(Action(ActionType.FOLD))
    elif step.kind is StepKind.RAISE_TO:
        assert step.amount is not None
        hand.apply(Action(ActionType.RAISE, amount=step.amount))
    else:
        hand.apply(Action(ActionType.ALL_IN))


def _apply_pokerkit(state: State, step: Step) -> None:
    if step.kind is StepKind.CHECK_OR_CALL:
        state.check_or_call()
    elif step.kind is StepKind.FOLD:
        state.fold()
    elif step.kind is StepKind.RAISE_TO:
        assert step.amount is not None
        state.complete_bet_or_raise_to(step.amount)
    else:
        assert state.actor_index is not None
        actor = state.actor_index
        all_in_total = state.bets[actor] + state.stacks[actor]
        if all_in_total > max(state.bets):
            state.complete_bet_or_raise_to(all_in_total)
        else:
            state.check_or_call()


def _deal_pokerkit_holes(
    state: State,
    physical_holes: tuple[str, ...],
    canonical_to_physical: tuple[int, ...],
) -> None:
    while state.can_deal_hole():
        assert state.hole_dealee_index is not None
        physical_seat = canonical_to_physical[state.hole_dealee_index]
        state.deal_hole(physical_holes[physical_seat])


def _physical_values(
    canonical_values: list[int], canonical_to_physical: tuple[int, ...]
) -> tuple[int, ...]:
    physical = [0] * len(canonical_values)
    for canonical, seat in enumerate(canonical_to_physical):
        physical[seat] = canonical_values[canonical]
    return tuple(physical)


class DifferentialState:
    """A synchronized preflop state used to compare action legality."""

    def __init__(self, stacks: list[int], button: int, seed: int = 1):
        self.players = [Player(f"P{seat}", stack) for seat, stack in enumerate(stacks)]
        self.internal = Hand(
            self.players,
            button=button,
            small_blind=SMALL_BLIND,
            big_blind=BIG_BLIND,
            seed=seed,
        )
        self.internal.start()
        self.canonical_to_physical = _canonical_to_physical(len(stacks), button)
        self.pokerkit = _state(stacks, self.canonical_to_physical)
        holes = tuple("".join(str(card) for card in player.hole) for player in self.players)
        _deal_pokerkit_holes(self.pokerkit, holes, self.canonical_to_physical)

    @property
    def pokerkit_actor(self) -> int | None:
        if self.pokerkit.actor_index is None:
            return None
        return self.canonical_to_physical[self.pokerkit.actor_index]

    @property
    def pokerkit_bets(self) -> tuple[int, ...]:
        return _physical_values(list(self.pokerkit.bets), self.canonical_to_physical)

    @property
    def pokerkit_stacks(self) -> tuple[int, ...]:
        return _physical_values(list(self.pokerkit.stacks), self.canonical_to_physical)

    def apply(self, step: Step) -> None:
        assert self.internal.to_act == self.pokerkit_actor
        _apply_internal(self.internal, step)
        _apply_pokerkit(self.pokerkit, step)


def play_differential_hand(
    stacks: list[int],
    script: list[Step],
    *,
    button: int,
    seed: int,
    deal: DealPlan | None = None,
) -> DifferentialResult:
    """Play the same hand in both engines and return comparable evidence."""

    starting_total = sum(stacks)
    players = [Player(f"P{seat}", stack) for seat, stack in enumerate(stacks)]
    hand = Hand(
        players,
        button=button,
        small_blind=SMALL_BLIND,
        big_blind=BIG_BLIND,
        seed=seed,
    )
    hand.start()
    if deal is not None:
        _install_deal(hand, deal)

    holes = tuple("".join(str(card) for card in player.hole) for player in players)
    future_cards = deque(str(card) for card in hand.deck.cards)
    remaining_steps = deque(script)
    actor_trace: list[int] = []

    def strategy(current: Hand) -> Action:
        if not remaining_steps:
            raise AssertionError("internal engine requested an unexpected extra action")
        step = remaining_steps.popleft()
        actor_trace.append(current.to_act)
        if step.kind is StepKind.CHECK_OR_CALL:
            action_type = (
                ActionType.CHECK if ActionType.CHECK in current.legal_actions() else ActionType.CALL
            )
            return Action(action_type)
        if step.kind is StepKind.FOLD:
            return Action(ActionType.FOLD)
        if step.kind is StepKind.RAISE_TO:
            assert step.amount is not None
            return Action(ActionType.RAISE, amount=step.amount)
        return Action(ActionType.ALL_IN)

    hand.play_out(strategy)
    assert not remaining_steps, "script contains actions not consumed by the internal engine"

    canonical_to_physical = _canonical_to_physical(len(stacks), button)
    oracle = _state(stacks, canonical_to_physical)
    _deal_pokerkit_holes(oracle, holes, canonical_to_physical)
    oracle_steps = deque(script)
    trace = deque(actor_trace)
    guard = 0
    while oracle.status and guard < 500:
        guard += 1
        if oracle.can_burn_card():
            oracle.burn_card(future_cards.popleft())
        elif oracle.can_deal_board():
            cards = "".join(future_cards.popleft() for _ in range(oracle.board_dealing_count))
            oracle.deal_board(cards)
        elif oracle.actor_index is not None and oracle_steps:
            physical_actor = canonical_to_physical[oracle.actor_index]
            assert physical_actor == trace.popleft(), "betting order diverged between engines"
            _apply_pokerkit(oracle, oracle_steps.popleft())
        else:
            break

    assert guard < 500, "PokerKit replay did not converge"
    assert not oracle_steps, "PokerKit did not consume the complete action script"
    assert not trace, "PokerKit requested fewer actions than the internal engine"

    internal_stacks = tuple(player.stack for player in players)
    pokerkit_stacks = _physical_values(list(oracle.stacks), canonical_to_physical)
    assert sum(internal_stacks) == starting_total
    assert sum(pokerkit_stacks) == starting_total
    return DifferentialResult(
        internal_stacks=internal_stacks,
        pokerkit_stacks=pokerkit_stacks,
        actor_trace=tuple(actor_trace),
        board=tuple(str(card) for card in hand.board),
        pot_amounts=tuple(pot.amount for pot in hand.build_side_pots()),
    )

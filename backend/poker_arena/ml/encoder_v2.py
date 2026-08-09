"""Suit-canonical, seat-aware and history-aware Expert observation encoder."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.engine.actions import ActionType

from .action_space_v2 import legal_mask_v2

REVISION: Final = "poker-arena-encoder-v2.5-street-aware-board-2026-08-08"
CARD_FEATURES: Final = 208
GLOBAL_FEATURES: Final = 24
MAX_SEATS: Final = 9
SEAT_FEATURES: Final = 12
MAX_HISTORY: Final = 15
HISTORY_SEAT_BUCKETS: Final = MAX_SEATS + 1
HISTORY_FEATURES: Final = 26

_RANKS: Final = "23456789TJQKA"
_SUITS: Final = "shdc"
_STREETS: Final = ("preflop", "flop", "turn", "river")
_HISTORY_ACTIONS: Final = ("fold", "check", "call", "raise", "all_in", "post_blind")
_PLAYER_STATUSES: Final = {"active", "folded", "all_in"}


@dataclass(frozen=True, slots=True)
class EncodedObservationV2:
    cards: tuple[float, ...]
    global_features: tuple[float, ...]
    seats: tuple[tuple[float, ...], ...]
    history: tuple[tuple[float, ...], ...]
    history_mask: tuple[float, ...]
    legal_mask: tuple[float, ...]


def _nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative int")
    return value


def _validate_observation(obs: Observation) -> None:
    """Reject malformed runtime/training state before it can become a tensor."""

    n = len(obs.players)
    if type(obs.seat) is not int or not 0 <= obs.seat < n:
        raise ValueError("hero seat must be a valid contiguous seat")
    seats = [player.seat for player in obs.players]
    if any(type(seat) is not int for seat in seats) or sorted(seats) != list(range(n)):
        raise ValueError("public player seats must be contiguous integers")
    if sum(player.is_button is True for player in obs.players) != 1:
        raise ValueError("public players must contain exactly one button")
    if len(obs.hole) != 2 or len(obs.board) not in (0, 3, 4, 5):
        raise ValueError("observation must contain two hole cards and a legal board size")
    if len(obs.history) > MAX_HISTORY:
        raise ValueError("history exceeds the Expert v2 trained window")
    if len(set((*obs.hole, *obs.board))) != len(obs.hole) + len(obs.board):
        raise ValueError("observation contains duplicate visible cards")
    for field, value in (
        ("pot", obs.pot),
        ("to_call", obs.to_call),
        ("current_bet", obs.current_bet),
        ("min_raise_to", obs.min_raise_to),
        ("num_active", obs.num_active),
    ):
        _nonnegative_int(value, field)
    if not obs.legal_actions or any(
        not isinstance(action, ActionType) for action in obs.legal_actions
    ):
        raise ValueError("legal_actions must be a non-empty ActionType set")
    for player in obs.players:
        if type(player.is_button) is not bool:
            raise ValueError("is_button must be a bool")
        if player.status not in _PLAYER_STATUSES:
            raise ValueError("public player status is invalid")
        _nonnegative_int(player.stack, "player.stack")
        _nonnegative_int(player.current_bet, "player.current_bet")
        _nonnegative_int(player.total_committed, "player.total_committed")
        if player.current_bet > player.total_committed:
            raise ValueError("current street commitment exceeds total commitment")
    hero = obs.players[obs.seat]
    if hero.status != "active" or hero.stack <= 0:
        raise ValueError("the acting hero must be active with a positive stack")
    active = sum(player.status != "folded" for player in obs.players)
    if obs.num_active != active:
        raise ValueError("num_active contradicts public player statuses")
    for event in obs.history:
        if type(event.seat) is not int or event.seat < -1 or event.seat >= n:
            raise ValueError("history contains an invalid public seat")
        for field, value in (
            ("history.amount_added", event.amount_added),
            ("history.pot_before", event.pot_before),
            ("history.to_call_before", event.to_call_before),
        ):
            _nonnegative_int(value, field)
        if event.raise_to is not None:
            _nonnegative_int(event.raise_to, "history.raise_to")
        if type(event.is_full_raise) is not bool or type(event.is_forced) is not bool:
            raise ValueError("history flags must be bool values")


def _validate_encoded(encoded: EncodedObservationV2) -> None:
    groups = (
        encoded.cards,
        encoded.global_features,
        *(encoded.seats),
        *(encoded.history),
        encoded.history_mask,
        encoded.legal_mask,
    )
    for group in groups:
        for value in group:
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("encoder v2 emitted a non-finite or out-of-range feature")


def _street(board_size: int) -> str:
    try:
        return {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[board_size]
    except KeyError as exc:
        raise ValueError("board must contain 0, 3, 4 or 5 cards") from exc


def _suit_mapping(obs: Observation) -> dict[str, int]:
    """Map physical suits to canonical identities using only observed cards."""

    zones = (obs.hole, obs.board[:3], obs.board[3:4], obs.board[4:5])
    signatures: dict[str, tuple[int, int, int, int]] = {}
    for suit in _SUITS:
        masks = []
        for zone in zones:
            mask = 0
            for card in zone:
                text = str(card)
                if text[1] == suit:
                    mask |= 1 << _RANKS.index(text[0])
            masks.append(mask)
        signatures[suit] = tuple(masks)  # type: ignore[assignment]
    ordered = sorted(_SUITS, key=lambda suit: (signatures[suit], suit))
    return {suit: canonical for canonical, suit in enumerate(ordered)}


def _encode_cards(obs: Observation) -> tuple[float, ...]:
    mapping = _suit_mapping(obs)
    hole = [0.0] * 52
    flop = [0.0] * 52
    turn = [0.0] * 52
    river = [0.0] * 52
    for destination, cards in (
        (hole, obs.hole),
        (flop, obs.board[:3]),
        (turn, obs.board[3:4]),
        (river, obs.board[4:5]),
    ):
        for card in cards:
            text = str(card)
            index = mapping[text[1]] * 13 + _RANKS.index(text[0])
            destination[index] = 1.0
    return tuple(hole + flop + turn + river)


def _context(obs: Observation) -> tuple[PublicPlayer, float, int, list[PublicPlayer]]:
    if not 2 <= len(obs.players) <= MAX_SEATS:
        raise ValueError("encoder v2 requires 2 to 9 public players")
    seats = [player.seat for player in obs.players]
    if len(set(seats)) != len(seats):
        raise ValueError("public player seats must be unique")
    hero = next((player for player in obs.players if player.seat == obs.seat), None)
    if hero is None:
        raise ValueError("hero is absent from public players")
    total = sum(player.stack + player.total_committed for player in obs.players)
    scale = float(total) if total > 0 else 1.0
    active_opponents = [
        player for player in obs.players if player.seat != obs.seat and player.status != "folded"
    ]
    effective = min([hero.stack, *(player.stack for player in active_opponents)])
    return hero, scale, effective, active_opponents


def _encode_global(obs: Observation) -> tuple[float, ...]:
    hero, scale, effective, opponents = _context(obs)
    n = len(obs.players)
    button = next((player.seat for player in obs.players if player.is_button), obs.seat)
    street = [1.0 if name == _street(len(obs.board)) else 0.0 for name in _STREETS]
    call_cost = min(obs.to_call, hero.stack)
    pot_odds = call_cost / (obs.pot + call_cost) if call_cost > 0 else 0.0
    opponent_stacks = [player.stack for player in opponents] or [0]
    values = [
        obs.pot / scale,
        obs.to_call / scale,
        hero.stack / scale,
        hero.current_bet / scale,
        obs.current_bet / scale,
        obs.min_raise_to / scale,
        obs.num_active / n,
        n / MAX_SEATS,
        effective / scale,
        min(effective / max(obs.pot, 1) / 20.0, 1.0),
        pot_odds,
        ((obs.seat - button) % n) / n,
        *street,
        1.0 if hero.status == "active" else 0.0,
        1.0 if obs.to_call > 0 else 0.0,
        1.0 if legal_mask_v2(obs)[2] else 0.0,
        1.0 if legal_mask_v2(obs)[9] else 0.0,
        min(len(obs.history), MAX_HISTORY) / MAX_HISTORY,
        hero.total_committed / scale,
        max(opponent_stacks) / scale,
        min(opponent_stacks) / scale,
    ]
    if len(values) != GLOBAL_FEATURES:
        raise AssertionError("encoder v2 global contract drifted")
    return tuple(values)


def _encode_seats(obs: Observation) -> tuple[tuple[float, ...], ...]:
    hero, scale, _effective, _opponents = _context(obs)
    n = len(obs.players)
    by_relative = sorted(obs.players, key=lambda player: (player.seat - obs.seat) % n)
    rows: list[tuple[float, ...]] = []
    for relative, player in enumerate(by_relative):
        effective = min(hero.stack, player.stack)
        row = (
            1.0,
            1.0 if player.seat == obs.seat else 0.0,
            1.0 if player.status == "active" else 0.0,
            1.0 if player.status == "folded" else 0.0,
            1.0 if player.status == "all_in" else 0.0,
            player.stack / scale,
            player.current_bet / scale,
            player.total_committed / scale,
            effective / scale,
            1.0 if player.is_button else 0.0,
            relative / max(n - 1, 1),
            min(player.stack / max(hero.stack, 1), 4.0) / 4.0,
        )
        rows.append(row)
    rows.extend([(0.0,) * SEAT_FEATURES] * (MAX_SEATS - len(rows)))
    return tuple(rows)


def _encode_history(obs: Observation, scale: float) -> tuple[tuple[float, ...], ...]:
    n = len(obs.players)
    rows: list[tuple[float, ...]] = []
    for event in obs.history[-MAX_HISTORY:]:
        if event.seat == -1:
            relative = MAX_SEATS
        elif 0 <= event.seat < n:
            relative = (event.seat - obs.seat) % n
        else:
            raise ValueError("history contains an invalid public seat")
        seat_one_hot = [1.0 if index == relative else 0.0 for index in range(HISTORY_SEAT_BUCKETS)]
        if event.street not in _STREETS:
            raise ValueError("history contains an unknown public street")
        street_one_hot = [1.0 if event.street == name else 0.0 for name in _STREETS]
        action_name = "post_blind" if event.action in {"post_sb", "post_bb"} else event.action
        if action_name not in _HISTORY_ACTIONS:
            raise ValueError("history contains an unknown public action")
        action_one_hot = [1.0 if action_name == name else 0.0 for name in _HISTORY_ACTIONS]
        numeric = [
            event.amount_added / scale,
            (event.raise_to or 0) / scale,
            event.pot_before / scale,
            event.to_call_before / scale,
        ]
        row = tuple(
            [
                *seat_one_hot,
                *street_one_hot,
                *action_one_hot,
                *numeric,
                1.0 if event.is_full_raise else 0.0,
                1.0 if event.is_forced else 0.0,
            ]
        )
        if len(row) != HISTORY_FEATURES:
            raise AssertionError("encoder v2 history contract drifted")
        rows.append(row)
    rows.extend([(0.0,) * HISTORY_FEATURES] * (MAX_HISTORY - len(rows)))
    return tuple(rows)


def encode_v2(obs: Observation) -> EncodedObservationV2:
    """Encode one observation into the immutable multi-input ONNX v2 contract."""

    _validate_observation(obs)
    _street(len(obs.board))
    _hero, scale, _effective, _opponents = _context(obs)
    history_count = min(len(obs.history), MAX_HISTORY)
    encoded = EncodedObservationV2(
        cards=_encode_cards(obs),
        global_features=_encode_global(obs),
        seats=_encode_seats(obs),
        history=_encode_history(obs, scale),
        history_mask=tuple([1.0] * history_count + [0.0] * (MAX_HISTORY - history_count)),
        legal_mask=tuple(1.0 if enabled else 0.0 for enabled in legal_mask_v2(obs)),
    )
    _validate_encoded(encoded)
    return encoded

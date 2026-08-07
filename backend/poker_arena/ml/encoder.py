"""Codificação Observation → features + espaço de ação discreto (ACL motor↔rede).

A política neural vê um vetor de tamanho fixo e escolhe entre 5 ações abstratas,
que viram uma `Action` LEGAL do motor. Pura (sem numpy/torch) — usada tanto no
treino (Colab) quanto na inferência (MLBot no backend).
"""

from __future__ import annotations

from ..bots.heuristic_bot import postflop_strength, preflop_strength
from ..bots.observation import Observation, PublicPlayer
from ..engine.actions import Action, ActionType

# ações discretas que a rede escolhe
ACTIONS: tuple[str, ...] = ("fold", "check_call", "raise_half", "raise_pot", "all_in")
N_ACTIONS = len(ACTIONS)

_RANKS = "23456789TJQKA"
_SUITS = "shdc"
_HOLE = 52
_BOARD = 52
_SCALARS = 7  # pote, to_call, stack, current_bet, min_raise_to, num_active, força
_STREET = 4
_POSITION = 1
FEATURE_SIZE = _HOLE + _BOARD + _SCALARS + _STREET + _POSITION + N_ACTIONS  # 121


def _card_idx(card: str) -> int:
    return _SUITS.index(card[1]) * 13 + _RANKS.index(card[0])


def _own(obs: Observation) -> PublicPlayer:
    return next(p for p in obs.players if p.seat == obs.seat)


def _hand_strength(obs: Observation) -> float:
    """Força da mão em [0,1] via treys: pré-flop por regra, pós-flop por percentil.

    Dá à rede o sinal de força explícito (em vez de aprender do zero pelas cartas)
    — acelera o warm-start e o self-play. Robusto a board incompleto/malformado.
    """
    if len(obs.hole) < 2:
        return 0.0
    if len(obs.board) >= 3:
        return postflop_strength(obs.hole, obs.board)
    return preflop_strength(obs.hole)


def legal_mask(obs: Observation) -> list[bool]:
    """Quais das 5 ações discretas são legais agora."""
    legal = obs.legal_actions
    can_raise = ActionType.RAISE in legal
    return [
        ActionType.FOLD in legal,
        ActionType.CHECK in legal or ActionType.CALL in legal,
        can_raise,
        can_raise,
        ActionType.ALL_IN in legal,
    ]


def encode(obs: Observation) -> list[float]:
    """Observation → vetor de `FEATURE_SIZE` floats (escala-invariante)."""
    if len(obs.board) not in (0, 3, 4, 5):
        raise ValueError(f"board must contain 0, 3, 4 or 5 cards, got {len(obs.board)}")
    if not obs.players:
        raise ValueError("observation must contain at least one player")
    hole = [0.0] * _HOLE
    for c in obs.hole:
        hole[_card_idx(str(c))] = 1.0
    board = [0.0] * _BOARD
    for c in obs.board:
        board[_card_idx(str(c))] = 1.0

    chips = obs.pot + sum(p.stack for p in obs.players)
    total = float(chips) if chips > 0 else 1.0
    me = _own(obs)
    scalars = [
        obs.pot / total,
        obs.to_call / total,
        me.stack / total,
        obs.current_bet / total,
        obs.min_raise_to / total,
        obs.num_active / float(len(obs.players)),
        _hand_strength(obs),
    ]

    street = [0.0] * _STREET
    street[{0: 0, 3: 1, 4: 2, 5: 3}[len(obs.board)]] = 1.0

    n = len(obs.players)
    button = next((p.seat for p in obs.players if p.is_button), obs.seat)
    position = [((obs.seat - button) % n) / n]

    mask = [1.0 if m else 0.0 for m in legal_mask(obs)]
    return hole + board + scalars + street + position + mask


def to_action(obs: Observation, action_index: int) -> Action:
    """Converte uma escolha discreta, validada e legal numa ``Action`` do motor."""
    if type(action_index) is not int:  # bool também não é um índice de policy válido.
        raise TypeError("action_index must be an int")
    if not 0 <= action_index < N_ACTIONS:
        raise ValueError(f"action_index must be in [0, {N_ACTIONS}), got {action_index}")
    if not legal_mask(obs)[action_index]:
        raise ValueError(f"action_index {action_index} is illegal for the current observation")
    name = ACTIONS[action_index]
    legal = obs.legal_actions
    if name == "fold":
        return Action(ActionType.FOLD)
    if name == "check_call":
        kind = ActionType.CHECK if ActionType.CHECK in legal else ActionType.CALL
        return Action(kind)
    if name == "all_in":
        return Action(ActionType.ALL_IN)
    me = _own(obs)
    max_to = me.current_bet + me.stack
    frac = 0.5 if name == "raise_half" else 1.0
    target = obs.current_bet + int(obs.pot * frac)
    return Action(ActionType.RAISE, max(obs.min_raise_to, min(target, max_to)))

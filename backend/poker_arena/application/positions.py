"""Posições da mesa de poker (relativas ao botão) — rótulos e nomes completos.

Indexado pelo OFFSET do botão: offset 0 = botão (BTN), 1 = small blind, 2 = big
blind e assim por diante. Os rótulos seguem a convenção pedida (até 9 jogadores);
em mesas menores as posições mais cedo somem primeiro (como num cassino).
"""

from __future__ import annotations

from ..position_rules import POSITION_BY_PLAYER_COUNT, position_is_compatible, valid_positions

# rótulos por nº de jogadores na mão, indexados pelo offset do botão (0 = botão)
_POS: dict[int, list[str]] = {
    count: list(labels) for count, labels in POSITION_BY_PLAYER_COUNT.items()
}

_FULL: dict[str, str] = {
    "BTN": "Botão (Dealer)",
    "SB": "Small Blind",
    "BB": "Big Blind",
    "UTG": "Under the Gun",
    "UTG+1": "Under the Gun +1",
    "MP": "Middle Position",
    "LJ": "Lojack",
    "HJ": "Hijack",
    "CO": "Cutoff",
}


def position(seat: int, button: int, n: int) -> str:
    """Sigla da posição da cadeira `seat` numa mão com `n` jogadores e botão em `button`."""
    table = _POS.get(n)
    if not table:
        return ""
    offset = (seat - button) % n
    return table[offset] if 0 <= offset < len(table) else ""


def position_full(label: str) -> str:
    """Nome completo de uma sigla de posição (ex.: 'UTG' -> 'Under the Gun')."""
    return _FULL.get(label, label)


__all__ = ["position", "position_full", "position_is_compatible", "valid_positions"]

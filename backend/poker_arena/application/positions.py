"""Posições da mesa de poker (relativas ao botão) — rótulos e nomes completos.

Indexado pelo OFFSET do botão: offset 0 = botão (BTN), 1 = small blind, 2 = big
blind e assim por diante. Os rótulos seguem a convenção pedida (até 9 jogadores);
em mesas menores as posições mais cedo somem primeiro (como num cassino).
"""

from __future__ import annotations

# rótulos por nº de jogadores na mão, indexados pelo offset do botão (0 = botão)
_POS: dict[int, list[str]] = {
    2: ["SB", "BB"],  # heads-up: o botão é o small blind
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "UTG"],
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "LJ", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG+1", "LJ", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"],
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

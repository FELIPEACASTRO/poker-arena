"""Deriva Nº DE PARTICIPANTES e POSIÇÃO da geometria dos assentos detectados.

O detector (F1 por blob / F2 treinado) devolve as caixas dos assentos, do dealer
button e das suas cartas. Aqui é pura GEOMETRIA: ordena os assentos ao redor da mesa
(sentido horário = ordem de ação do poker), acha o botão e o herói, e calcula a
posição (SB/BB/UTG/.../BTN) reaproveitando `positions.position`. Testável sem imagem.
"""

from __future__ import annotations

import math

from ..application.positions import position as _position_label

Point = tuple[float, float]


def _angle(cx: float, cy: float, p: Point) -> float:
    """Ângulo do ponto em relação ao centro. Em coord. de tela (y pra baixo), o
    ângulo CRESCE no sentido HORÁRIO — a mesma direção da ação no poker."""
    return math.atan2(p[1] - cy, p[0] - cx)


def _nearest(target: Point, points: list[Point]) -> int:
    def d2(i: int) -> float:
        return (points[i][0] - target[0]) ** 2 + (points[i][1] - target[1]) ** 2

    return min(range(len(points)), key=d2)


def derive_position(
    seat_centers: list[Point], hero_center: Point, button_center: Point | None
) -> tuple[int, str]:
    """(nº de jogadores, sigla da posição do herói). Sigla vazia se faltar info.

    Ordena os assentos em sentido HORÁRIO a partir do centro da mesa; o botão define
    o offset 0, o próximo horário é o SB, e assim por diante (convenção oficial)."""
    n = len(seat_centers)
    if n < 2:
        return n, ""
    cx = sum(p[0] for p in seat_centers) / n
    cy = sum(p[1] for p in seat_centers) / n
    order = sorted(range(n), key=lambda i: _angle(cx, cy, seat_centers[i]))  # horário
    ordered = [seat_centers[i] for i in order]

    hero_idx = _nearest(hero_center, ordered)
    if button_center is None or len(button_center) < 2:  # sem botão (ou vazio) -> sem posição
        return n, ""
    button_idx = _nearest(button_center, ordered)
    return n, _position_label(hero_idx, button_idx, n)

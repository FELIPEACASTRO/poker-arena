"""Geometria dos assentos: nº de participantes + posição a partir dos centros.

Pura geometria (sem imagem): dado onde estão os assentos, o herói e o dealer button,
o herói recebe a posição oficial (SB/BB/UTG/.../BTN) na ordem de ação (horário). Isso
é o que transforma 'jogadores detectados' em 'regra de posição' pro copiloto.
"""

import math

import pytest

from poker_arena.application.positions import position as pos_formula
from poker_arena.vision.seats import derive_position


def _ring(n: int, cx: float = 400, cy: float = 300, rx: float = 360, ry: float = 260):
    """n assentos ao redor da mesa; assento 0 = herói embaixo (90°), horário."""
    return [
        (cx + rx * math.cos(math.radians(90 + i * 360 / n)),
         cy + ry * math.sin(math.radians(90 + i * 360 / n)))
        for i in range(n)
    ]


def test_conta_participantes():
    for n in range(2, 10):
        seats = _ring(n)
        got_n, _ = derive_position(seats, seats[0], seats[0])
        assert got_n == n


def test_botao_no_heroi_vira_btn_ou_sb_heads_up():
    for n in range(2, 10):
        seats = _ring(n)
        _, pos = derive_position(seats, seats[0], seats[0])  # botão = herói
        assert pos == ("SB" if n == 2 else "BTN")


def test_posicao_bate_com_formula_oficial_para_todo_assento_do_botao():
    # herói é o assento 0; variando o assento do botão, a posição geométrica tem de
    # coincidir com a fórmula oficial positions.position(hero=0, button, n)
    for n in range(2, 10):
        seats = _ring(n)
        for b in range(n):
            _, pos = derive_position(seats, seats[0], seats[b])
            assert pos == pos_formula(0, b, n), f"n={n} botão={b}"


def test_sb_fica_um_passo_horario_apos_o_botao():
    # o jogador imediatamente à esquerda (horário) do botão é o small blind
    seats = _ring(6)
    # botão no assento 1 (um passo horário a partir do herói) -> herói fica ANTES dele
    _, pos = derive_position(seats, seats[0], seats[1])
    assert pos == pos_formula(0, 1, 6)  # herói vs botão em 1


def test_abstem_com_menos_de_dois_assentos():
    n, pos = derive_position([(1.0, 2.0)], (1.0, 2.0), (1.0, 2.0))
    assert n == 1 and pos == ""


def test_sem_botao_devolve_contagem_sem_posicao():
    seats = _ring(5)
    n, pos = derive_position(seats, seats[0], None)
    assert n == 5 and pos == ""


@pytest.mark.parametrize("n", [2, 3, 6, 9])
def test_ordena_por_angulo_independente_da_ordem_de_entrada(n):
    seats = _ring(n)
    shuffled = list(reversed(seats))  # ordem de entrada trocada não muda o resultado
    a = derive_position(seats, seats[0], seats[0])
    b = derive_position(shuffled, seats[0], seats[0])
    assert a == b

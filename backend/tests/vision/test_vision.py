"""Visão F1: gerador sintético + reconhecedor (template) + sanity-check.

Testa a CADEIA e mede a ACURÁCIA de verdade — inclusive que o baseline acerta alto
no estilo calibrado (canônico) e que o sanity-check protege o Copiloto de lixo.
A generalização a QUALQUER tela é o modelo treinado (F2, notebook) — aqui provamos
o pipeline e a régua.
"""

import numpy as np
import pytest

from poker_arena.vision import check_state, recognize_table, render_table
from poker_arena.vision.recognize import RecognizedState, _read_card
from poker_arena.vision.synth import CANONICAL, RANKS, SUITS, render_card


def test_generator_returns_image_and_truth():
    img, truth = render_table(seed=1, style=CANONICAL, n_board=3)
    assert img.size == (900, 600)
    assert len(truth["hole"]) == 2 and len(truth["board"]) == 3
    assert truth["pot"] > 0
    # sem cartas repetidas no gabarito
    cards = truth["hole"] + truth["board"]
    assert len(set(cards)) == len(cards)


def test_recognizer_reads_isolated_cards_perfectly():
    ok = 0
    for r in RANKS:
        for s in SUITS:
            card = render_card(r, s, CANONICAL, 64)
            got, _ = _read_card(np.asarray(card.convert("RGB")), (0, 0, 64, 90))
            ok += got == r + s
    assert ok >= 50  # 52 cartas isoladas no estilo canônico (baseline ~100%)


def test_recognizer_high_accuracy_on_canonical_style():
    cok = ctot = 0
    for seed in range(40):
        img, truth = render_table(seed=3000 + seed, style=CANONICAL)
        st = recognize_table(img)
        tc = truth["hole"] + truth["board"]
        got = st.hole + st.board
        ctot += len(tc)
        cok += sum(1 for c in tc if c in got)
    acc = cok / ctot
    assert acc >= 0.90, f"acurácia canônica caiu para {acc:.0%} (esperado >=90%)"


def test_recognizer_is_resolution_agnostic():
    # cada aluno tem um monitor/tela diferente -> a MESMA mesa em resoluções variadas
    for size in [(900, 600), (1280, 853), (1600, 1067)]:
        cok = ctot = 0
        for seed in range(15):
            img, truth = render_table(seed=seed, style=CANONICAL)
            st = recognize_table(img.resize(size))
            tc = truth["hole"] + truth["board"]
            got = st.hole + st.board
            ctot += len(tc)
            cok += sum(1 for c in tc if c in got)
        assert cok / ctot >= 0.85, f"{size}: {cok/ctot:.0%} (esperado >=85%)"


def test_pipeline_produces_valid_state():
    img, truth = render_table(seed=42, style=CANONICAL, n_board=5)
    st = recognize_table(img)
    assert isinstance(st, RecognizedState)
    assert 0.0 <= st.confidence <= 1.0
    # no estilo canônico, deve bater o hole e o board
    assert set(st.hole) == set(truth["hole"])
    assert st.board == truth["board"]


# ---------- leitura de JOGADORES + POSIÇÃO (assentos + dealer button) ----------
def test_detecta_numero_de_participantes_no_estilo_canonico():
    cok = tot = 0
    for seed in range(40):
        img, truth = render_table(seed=seed, style=CANONICAL, with_seats=True, noise=0.1)
        st = recognize_table(img)
        tot += 1
        cok += st.n_players == truth["n_players"]
    assert cok / tot >= 0.90, f"contagem de jogadores caiu para {cok/tot:.0%}"


def test_deriva_posicao_do_heroi_no_estilo_canonico():
    cok = tot = 0
    for seed in range(40):
        img, truth = render_table(seed=seed, style=CANONICAL, with_seats=True, noise=0.1)
        st = recognize_table(img)
        tot += 1
        cok += st.position == truth["position"]
    assert cok / tot >= 0.90, f"posição do herói caiu para {cok/tot:.0%}"


def test_assentos_nao_derrubam_a_leitura_das_cartas():
    # a mesa completa (com jogadores) não pode piorar a leitura das cartas
    cok = ctot = 0
    for seed in range(30):
        img, truth = render_table(seed=seed, style=CANONICAL, with_seats=True, noise=0.1)
        st = recognize_table(img)
        tc = truth["hole"] + truth["board"]
        got = st.hole + st.board
        ctot += len(tc)
        cok += sum(1 for c in tc if c in got)
    assert cok / ctot >= 0.95


def test_abstem_de_jogadores_quando_a_cor_do_feltro_colide():
    # feltro azul colide com o avatar azul -> ABSTÉM (0 jogadores), não conta errado
    from poker_arena.vision.synth import STYLES

    blue = next(s for s in STYLES if s.name == "blue-4color")
    abstidos = 0
    for seed in range(20):
        img, _ = render_table(seed=seed, style=blue, with_seats=True, noise=0.1)
        st = recognize_table(img)
        abstidos += st.n_players == 0
    assert abstidos >= 15  # abstém na grande maioria (F2 treinado é que generaliza)


def test_sanity_avisa_quando_nao_detecta_jogadores():
    st = RecognizedState(hole=["As", "Kd"], board=[], pot=100, n_cards=2,
                         confidence=0.9, n_players=0)
    r = check_state(st)
    assert r.ok and any("jogadores" in w for w in r.warnings)


# ---------- sanity-check (a rede de segurança) ----------
def test_sanity_accepts_a_plausible_state():
    st = RecognizedState(hole=["As", "Kd"], board=["Qs", "Jh", "2c"], pot=100,
                         n_cards=5, confidence=0.9)
    assert check_state(st).ok


@pytest.mark.parametrize(
    "st",
    [
        RecognizedState(hole=["As", "As"], board=[], pot=10, confidence=0.9),  # repetida
        RecognizedState(hole=["As"], board=["Kd", "Qh", "2c"], pot=10, confidence=0.9),  # 1 hole
        RecognizedState(hole=["As", "Kd"], board=["Qs", "Jh"], pot=10, confidence=0.9),  # board 2
        RecognizedState(hole=["Zz", "Kd"], board=[], pot=10, confidence=0.9),  # inexistente
    ],
)
def test_sanity_rejects_impossible_states(st):
    r = check_state(st)
    assert not r.ok and r.problems  # abstém com motivo


def test_sanity_warns_on_low_confidence():
    st = RecognizedState(hole=["As", "Kd"], board=[], pot=None, n_cards=2, confidence=0.1)
    r = check_state(st)
    assert r.ok  # estrutura válida
    assert r.warnings  # mas avisa (confiança baixa / pote não lido)

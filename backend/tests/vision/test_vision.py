"""Visão F1: gerador sintético + reconhecedor (template) + sanity-check.

Testa a CADEIA e mede a ACURÁCIA de verdade — inclusive que o baseline acerta alto
no estilo calibrado (canônico) e que o sanity-check protege o Copiloto de lixo.
A eventual generalização fora do estilo sintético precisa ser medida em holdout real
agrupado; estes testes de F1 verificam somente o contrato determinístico local — aqui provamos
o pipeline e a régua.
"""

import numpy as np
import pytest
from PIL import Image

from poker_arena.vision import check_state, recognize_table, render_table
from poker_arena.vision.recognize import (
    RecognizedState,
    _cards_force_abstention,
    _read_card,
)
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


def test_read_card_recomputes_dimensions_after_tight_recrop():
    """A loose detector box must not leave stale dimensions after the felt is cropped."""
    card = np.asarray(render_card("A", "h", CANONICAL, 64).convert("RGB"))
    loose = np.zeros((110, 84, 3), dtype=np.uint8)
    loose[:] = (22, 92, 55)
    ch, cw = card.shape[:2]
    loose[10 : 10 + ch, 10 : 10 + cw] = card
    got, _ = _read_card(loose, (0, 0, 84, 110))
    assert got == "Ah"


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
        assert cok / ctot >= 0.85, f"{size}: {cok / ctot:.0%} (esperado >=85%)"


def test_pote_com_board_nao_e_silenciosamente_errado():
    # regressão do bug: o topo claro das cartas do board caía na faixa do pote e fundia
    # aos dígitos -> pote errado em ~52% das mãos. Apagando as cartas antes de ler, o
    # pote no estilo canônico com board volta a bater na grande maioria.
    ok = tot = 0
    for seed in range(60):
        img, truth = render_table(seed=seed, style=CANONICAL, n_board=5)
        st = recognize_table(img)
        tot += 1
        ok += st.pot == truth["pot"]
    assert ok / tot >= 0.80, f"pote com board caiu para {ok / tot:.0%} (era ~48% com o bug)"


def test_pipeline_produces_valid_state():
    img, truth = render_table(seed=42, style=CANONICAL, n_board=5)
    st = recognize_table(img)
    assert isinstance(st, RecognizedState)
    assert 0.0 <= st.confidence <= 1.0
    # no estilo canônico, deve bater o hole e o board
    assert set(st.hole) == set(truth["hole"])
    assert st.board == truth["board"]


def test_strict_card_gate_skips_ocr_that_cannot_rescue_state(monkeypatch):
    import poker_arena.vision.recognize as recognition

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("OCR must not run after the card gate has already failed")

    monkeypatch.setattr(recognition, "_read_numbers", must_not_run)
    state = recognition.recognize_table(
        Image.new("RGB", (320, 200), "green"),
        ocr_numbers=True,
        fail_fast_abstain_below=0.85,
    )

    assert state.pot is None
    assert state.pot_source == "skipped-card-gate"
    assert check_state(state, abstain_below=0.85).ok is False


def test_card_gate_preserves_ocr_for_strong_structurally_valid_cards():
    assert not _cards_force_abstention(["As", "Kd"], ["2h", "6c", "Tc"], [0.99] * 5, 0.85)


@pytest.mark.parametrize("threshold", [True, -0.1, 1.1, float("nan")])
def test_card_gate_rejects_invalid_threshold(threshold):
    with pytest.raises(ValueError, match="fail_fast_abstain_below"):
        _cards_force_abstention(["As", "Kd"], [], [0.99, 0.99], threshold)


# ---------- leitura de JOGADORES + POSIÇÃO (assentos + dealer button) ----------
def test_detecta_numero_de_participantes_no_estilo_canonico():
    cok = tot = 0
    for seed in range(40):
        img, truth = render_table(seed=seed, style=CANONICAL, with_seats=True, noise=0.1)
        st = recognize_table(img)
        tot += 1
        cok += st.n_players == truth["n_players"]
    assert cok / tot >= 0.90, f"contagem de jogadores caiu para {cok / tot:.0%}"


def test_deriva_posicao_do_heroi_no_estilo_canonico():
    cok = tot = 0
    for seed in range(40):
        img, truth = render_table(seed=seed, style=CANONICAL, with_seats=True, noise=0.1)
        st = recognize_table(img)
        tot += 1
        cok += st.position == truth["position"]
    assert cok / tot >= 0.90, f"posição do herói caiu para {cok / tot:.0%}"


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


def test_feltro_azul_detecta_jogadores_sem_confundir_com_o_feltro():
    # regressão do bug: o seat_mask casava o feltro azul-esverdeado (blue-4color) e
    # zerava a leitura. Com b>g+25 o avatar domina o azul MAIS que o feltro -> detecta.
    from poker_arena.vision.synth import STYLES

    blue = next(s for s in STYLES if s.name == "blue-4color")
    ok = 0
    for seed in range(20):
        img, truth = render_table(seed=seed, style=blue, with_seats=True, noise=0.1)
        st = recognize_table(img)
        ok += st.n_players == truth["n_players"]
    assert ok >= 16  # conta certo na grande maioria (não abstém mais)


def test_sanity_avisa_quando_nao_detecta_jogadores():
    st = RecognizedState(
        hole=["As", "Kd"], board=[], pot=100, n_cards=2, confidence=0.9, n_players=0
    )
    r = check_state(st)
    assert r.ok and any("jogadores" in w for w in r.warnings)


# ---------- sanity-check (a rede de segurança) ----------
def test_sanity_accepts_a_plausible_state():
    st = RecognizedState(
        hole=["As", "Kd"], board=["Qs", "Jh", "2c"], pot=100, n_cards=5, confidence=0.9
    )
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


def test_sanity_rejects_ten_handed_state_outside_project_contract():
    st = RecognizedState(
        hole=["As", "Kd"],
        board=[],
        pot=10,
        n_cards=2,
        confidence=0.9,
        n_players=10,
    )

    result = check_state(st)
    assert result.ok is False
    assert any("2 a 9" in problem for problem in result.problems)


def test_sanity_fails_closed_on_low_confidence_or_missing_pot():
    st = RecognizedState(hole=["As", "Kd"], board=[], pot=None, n_cards=2, confidence=0.1)
    r = check_state(st)
    assert not r.ok
    assert any("confian" in p.lower() for p in r.problems)
    assert any("pote" in p.lower() for p in r.problems)


def test_recognized_state_without_evidence_defaults_to_zero_confidence():
    assert RecognizedState().confidence == 0.0


def test_sanity_uses_weakest_critical_card_confidence():
    st = RecognizedState(
        hole=["As", "Kd"],
        board=[],
        pot=10,
        n_cards=2,
        confidence=0.95,
        card_confidences=[0.99, 0.20],
        pot_confidence=0.99,
    )
    r = check_state(st)
    assert not r.ok
    assert any("confian" in p.lower() for p in r.problems)


def test_modo_strict_abstem_de_leitura_incerta():
    # modo "100% ou abstém": leitura VÁLIDA mas de baixa confiança -> abstém (não decide)
    fraca = RecognizedState(hole=["As", "Kd"], board=[], pot=10, n_cards=2, confidence=0.5)
    r = check_state(fraca, abstain_below=0.85)
    assert not r.ok and any("limiar seguro" in p for p in r.problems)
    # a mesma leitura, com confiança alta -> decide normalmente
    forte = RecognizedState(hole=["As", "Kd"], board=[], pot=10, n_cards=2, confidence=0.95)
    assert check_state(forte, abstain_below=0.85).ok
    # o modo padrao tambem falha fechado abaixo do piso critico
    assert not check_state(fraca).ok

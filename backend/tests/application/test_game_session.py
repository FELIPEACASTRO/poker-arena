import pytest

from poker_arena.application import (
    BotSpec,
    InvalidActionError,
    SessionConfig,
    build_session,
)
from poker_arena.engine.game import IllegalActionError


def _session(seed=7, n_bots=5, level="heuristic", stack=500, rebuy=True):
    cfg = SessionConfig(
        bots=[BotSpec(f"B{i}", level) for i in range(n_bots)],
        starting_stack=stack,
        rebuy=rebuy,
    )
    return build_session(cfg, seed=seed)


def test_initial_view_has_six_seats_and_valid_phase():
    v = _session().view()
    assert v.phase in ("human_turn", "hand_over", "game_over")
    assert v.table_id
    assert len(v.seats) == 6
    assert v.hand_number >= 1


def test_human_cards_visible_bots_hidden_during_play():
    v = _session().view()
    human = next(s for s in v.seats if s.kind == "human")
    assert human.cards is not None and len(human.cards) == 2
    if v.phase == "human_turn":
        bots = [s for s in v.seats if s.kind.startswith("bot")]
        assert all(b.cards is None for b in bots)  # escondidas durante o jogo


def test_legal_actions_present_on_human_turn():
    v = _session().view()
    if v.phase == "human_turn":
        assert v.legal is not None
        assert "fold" in v.legal.actions
        assert v.legal.to_call >= 0
        assert v.legal.max_raise_to >= v.legal.min_raise_to or "raise" not in v.legal.actions


def test_chip_conservation_in_tournament_mode():
    # modo torneio (sem recompra): fichas se conservam ao longo da sessão
    s = _session(stack=500, rebuy=False)
    total = 6 * 500
    for _ in range(80):
        assert s.total_chips() == total
        v = s.view()
        if v.phase == "human_turn":
            s.apply_human_action("fold")
        elif v.phase == "hand_over":
            s.next_hand()
        else:  # game_over
            break
    assert s.total_chips() == total


def test_cash_game_keeps_table_full_after_busts():
    # stacks minusculos -> jogadores quebram rapido; com recompra a mesa segue com 6
    s = _session(seed=3, stack=40, rebuy=True)
    for _ in range(25):
        v = s.view()
        assert len(v.seats) == 6  # nunca encolhe
        assert v.phase != "game_over"  # cash game não acaba por eliminação
        if v.phase == "human_turn":
            s.apply_human_action("fold")
        else:  # hand_over
            s.next_hand()


def test_illegal_action_is_rejected_by_engine():
    s = _session()
    v = s.view()
    if v.phase == "human_turn" and v.legal is not None and "check" not in v.legal.actions:
        with pytest.raises(IllegalActionError):
            s.apply_human_action("check")  # há aposta a pagar -> check é ilegal


def test_acting_when_not_human_turn_raises():
    s = _session()
    if s.view().phase == "human_turn":
        s.apply_human_action("fold")  # humano sai da mão -> não é mais a vez dele
    with pytest.raises(InvalidActionError):
        s.apply_human_action("fold")


def test_unknown_action_type_raises():
    s = _session()
    if s.view().phase == "human_turn":
        with pytest.raises(InvalidActionError):
            s.apply_human_action("teleport")


# ---------- modo assistir (todos bots) ----------
def _watch(seed=7, n=6, level="heuristic", stack=500):
    cfg = SessionConfig(
        bots=[BotSpec(f"B{i}", level) for i in range(n)],
        starting_stack=stack,
        mode="watch",
    )
    return build_session(cfg, seed=seed)


def test_watch_mode_has_no_human():
    v = _watch().view()
    assert v.phase in ("bot_turn", "hand_over")
    assert all(s.kind != "human" for s in v.seats)
    assert len(v.seats) == 6


def test_watch_mode_reveals_all_cards():
    v = _watch().view()
    assert all(s.cards is not None and len(s.cards) == 2 for s in v.seats)


def test_watch_mode_plays_a_full_hand_via_step():
    s = _watch(stack=500)
    total = 6 * 500
    for _ in range(300):
        assert s.total_chips() == total
        if s.view().phase == "bot_turn":
            s.step()
        else:  # hand_over
            break
    assert s.view().phase == "hand_over"


def test_step_outside_bot_turn_raises():
    s = _session()  # modo jogar nunca fica em bot_turn (bots jogam sozinhos)
    with pytest.raises(InvalidActionError):
        s.step()

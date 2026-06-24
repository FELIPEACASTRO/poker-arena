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


def test_hand_limit_ends_game_with_chip_leader_as_champion():
    # cash game COM limite de mãos: termina após N mãos; campeão = quem tem mais fichas
    cfg = SessionConfig(
        mode="watch",
        bots=[BotSpec(f"B{i}", "heuristic") for i in range(6)],
        starting_stack=500,
        rebuy=True,
        hand_limit=5,
    )
    s = build_session(cfg, seed=7)
    for _ in range(500):
        v = s.view()
        if v.phase == "game_over":
            break
        if v.phase == "bot_turn":
            s.step()
        elif v.phase == "hand_over":
            s.next_hand()
    v = s.view()
    assert v.phase == "game_over"  # parou no limite (não ficou em loop)
    assert v.hand_number >= 5
    top = max(st.stack for st in v.seats)
    assert set(v.winners or []) == {st.seat for st in v.seats if st.stack == top}


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


# ---------- painéis do modo laboratório (estatísticas ao vivo) ----------
def test_watch_mode_accumulates_live_stats():
    s = _watch(stack=500)
    for _ in range(400):
        v = s.view()
        if v.phase == "game_over":
            break
        if v.phase == "bot_turn":
            s.step()
        elif v.phase == "hand_over":
            s.next_hand()
    ws = s.view().watch_stats
    assert ws is not None
    assert ws.hands >= 1
    assert len(ws.bots) == 6
    for b in ws.bots:  # contadores coerentes; VPIP/agressão normalizados
        assert b.hands_dealt >= 1
        assert 0.0 <= b.vpip <= 1.0
        assert 0.0 <= b.aggression <= 1.0
    assert ws.bots == sorted(ws.bots, key=lambda b: b.stack, reverse=True)
    assert all(len(x.points) == ws.hands for x in ws.series)  # 1 ponto por mão


def test_play_mode_has_no_watch_stats():
    s = _session()  # modo jogar usa os painéis de análise, não os do laboratório
    assert s.view().watch_stats is None


# ---------- entrar/sair de jogadores (gestão da mesa) ----------
def test_roster_reflects_table():
    s = _watch(n=3)
    roster = s.view().roster
    assert len(roster) == 3
    assert all(not r.is_human for r in roster)


def test_add_and_remove_players():
    s = _watch(n=3, stack=500)
    s.add_bot("montecarlo", name="NovoBot")
    roster = s.view().roster
    assert len(roster) == 4
    assert any(r.name == "NovoBot" and r.level == "montecarlo" for r in roster)
    s.remove_player(0)
    assert len(s.view().roster) == 3


def test_add_bot_rejects_full_table_and_invalid_level():
    cheia = _watch(n=6)  # mesa 6-max lotada
    with pytest.raises(InvalidActionError):
        cheia.add_bot("montecarlo")
    s = _watch(n=3)
    with pytest.raises(InvalidActionError):
        s.add_bot("inexistente")


def test_remove_keeps_minimum_two_players():
    s = _watch(n=3)
    s.remove_player(0)  # 3 -> 2 ok
    with pytest.raises(InvalidActionError):
        s.remove_player(0)  # 2 -> 1 proibido


def test_cannot_remove_the_human():
    s = _session()  # modo jogar: humano na cadeira 0
    assert s.view().roster[0].is_human
    with pytest.raises(InvalidActionError):
        s.remove_player(0)


def test_added_bot_gets_unique_name():
    s = _watch(n=3)  # B0, B1, B2
    s.add_bot("random", name="B0")  # colide -> deve virar único
    names = [r.name for r in s.view().roster]
    assert len(names) == len(set(names))


# ---------- bot adaptativo (aprende o humano) ----------
def test_adaptive_session_learns_from_the_human():
    cfg = SessionConfig(
        bots=[BotSpec(f"B{i}", "adaptive") for i in range(3)],
        starting_stack=300, mode="play",
    )
    s = build_session(cfg, seed=5)
    assert s.view().opponent_read is not None  # auto-learning ativo desde o inicio
    for _ in range(80):
        v = s.view()
        if v.phase == "human_turn" and v.legal is not None:
            legal = v.legal.actions
            if "fold" in legal and v.legal.to_call > 0:
                s.apply_human_action("fold")  # sempre desiste diante de aposta
            else:
                s.apply_human_action("check" if "check" in legal else "call")
        elif v.phase == "hand_over":
            s.next_hand()
        else:
            break
    read = s.view().opponent_read
    assert read is not None and read.samples > 0  # observou as jogadas do humano

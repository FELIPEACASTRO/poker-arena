import threading
import time
from contextlib import suppress

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


def test_uncontested_winner_cards_remain_hidden_after_fold():
    s = _session(n_bots=1)
    assert s.view().phase == "human_turn"
    s.apply_human_action("fold")
    v = s.view()

    assert v.phase == "hand_over"
    bot = next(seat for seat in v.seats if seat.kind.startswith("bot"))
    assert bot.cards is None


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
            samples_before = v.opponent_read.samples
            actions_before = list(v.last_actions)
            s.apply_human_action("check")  # há aposta a pagar -> check é ilegal
        after = s.view()
        assert after.opponent_read.samples == samples_before
        assert after.last_actions == actions_before


def test_concurrent_commands_are_serialized_per_session(monkeypatch):
    s = _session()
    assert s.view().phase == "human_turn"
    original_apply = s._hand.apply
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def slow_apply(action):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return original_apply(action)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(s._hand, "apply", slow_apply)
    start = threading.Barrier(3)

    def act_once():
        start.wait()
        with suppress(InvalidActionError, IllegalActionError):
            s.apply_human_action("fold")

    threads = [threading.Thread(target=act_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert max_active == 1


def test_version_changes_only_after_successful_commands_and_not_reads():
    s = _session(n_bots=1)
    assert s.version == 0
    s.view()
    assert s.version == 0

    with pytest.raises(IllegalActionError):
        s.apply_human_action("check")
    assert s.version == 0

    s.apply_human_action("fold")
    assert s.version == 1
    s.view()
    assert s.version == 1


def test_snapshot_returns_one_atomic_versioned_read_without_mutating_state():
    s = _session(n_bots=1)
    snapshot = s.snapshot()
    assert snapshot.view == s.view()
    assert snapshot.version == 0
    assert snapshot.replayed is False
    assert s.version == 0

    s.apply_human_action("fold")
    after = s.snapshot()
    assert after.view == s.view()
    assert after.version == 1
    assert after.replayed is False


def test_execute_once_replays_snapshot_and_rejects_key_reuse():
    s = _session(n_bots=1)
    first = s.execute_once(
        command_id="fold-1",
        fingerprint="fold",
        expected_version=0,
        operation=lambda: s.apply_human_action("fold"),
    )
    assert first.version == 1
    assert first.replayed is False

    duplicate = s.execute_once(
        command_id="fold-1",
        fingerprint="fold",
        expected_version=0,
        operation=lambda: s.apply_human_action("fold"),
    )
    assert duplicate.replayed is True
    assert duplicate.version == first.version
    assert duplicate.view == first.view
    assert s.version == 1

    with pytest.raises(ValueError):
        s.execute_once(
            command_id="stale-command",
            fingerprint="noop",
            expected_version=0,
            operation=lambda: None,
        )

    with pytest.raises(ValueError):
        s.execute_once(
            command_id="fold-1",
            fingerprint="different-payload",
            expected_version=1,
            operation=lambda: None,
        )


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
def test_watch_stats_appear_immediately_not_after_first_hand():
    # UX: o placar aparece ASSIM QUE a mesa é montada (senão fica ~20s em branco no
    # começo, pois a 1ª mão demora por causa da pausa entre jogadas)
    s = _watch(stack=500)
    ws = s.view().watch_stats  # PRIMEIRA visão, sem nenhum step/mão terminada
    assert ws is not None
    assert ws.hands == 0  # nenhuma mão completa ainda
    assert len(ws.bots) == 6
    assert all(b.stack == 500 and b.delta == 0 and b.hands_won == 0 for b in ws.bots)


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


# ---------- raciocínio didático (como cada bot está pensando) ----------
def test_watch_mode_produces_reasoning():
    s = _watch(n=3, stack=1000)
    for _ in range(60):
        v = s.view()
        if v.phase == "bot_turn":
            s.step()
            r = s.view().reasoning
            assert r is not None
            assert r.name and r.level
            assert 0 <= r.equity_pct <= 100
            assert 0 <= r.pot_odds_pct <= 100
            assert len(r.options) >= 1
            assert any(o.chosen for o in r.options)  # a jogada escolhida marcada
            assert all(o.verdict in ("good", "ok", "bad") for o in r.options)
            assert r.why_chosen and r.how_it_thinks
            return
        if v.phase == "hand_over":
            s.next_hand()
    raise AssertionError("não houve jogada de bot")


def test_play_mode_has_no_reasoning():
    s = _session()  # raciocínio é só do modo laboratório
    assert s.view().reasoning is None


# ---------- posições da mesa (até 9 jogadores) ----------
def test_table_supports_nine_players():
    s = _watch(n=9)
    assert len(s.view().seats) == 9


def test_positions_relative_to_button():
    s = _watch(n=9)
    seats = s.view().seats
    btn = next(i for i, x in enumerate(seats) if x.is_button)
    labels = [seats[(btn + off) % 9].position for off in range(9)]
    assert labels == ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"]


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
    cheia = _watch(n=9)  # mesa 9-max lotada
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


def test_added_bot_name_is_unique_case_insensitively():
    s = _watch(n=3)
    s.add_bot("random", name="b0")
    names = [r.name for r in s.view().roster]
    assert len({name.casefold() for name in names}) == len(names)


@pytest.mark.parametrize(
    "mode,n_bots",
    [("play", 0), ("play", 9), ("watch", 1), ("watch", 10)],
)
def test_build_session_rejects_tables_outside_two_to_nine_seats(mode, n_bots):
    cfg = SessionConfig(
        mode=mode,
        bots=[BotSpec(f"B{i}", "random") for i in range(n_bots)],
    )
    with pytest.raises(ValueError, match="2.*9"):
        build_session(cfg, seed=7)


def test_build_session_rejects_duplicate_names_case_insensitively():
    cfg = SessionConfig(
        human_name="Hero",
        bots=[BotSpec("hero", "random")],
    )
    with pytest.raises(ValueError, match="nomes"):
        build_session(cfg, seed=7)


# ---------- bot adaptativo (aprende o humano) ----------
def test_adaptive_session_learns_from_the_human():
    cfg = SessionConfig(
        bots=[BotSpec(f"B{i}", "adaptive") for i in range(3)],
        starting_stack=300,
        mode="play",
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

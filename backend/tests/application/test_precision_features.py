"""Testes de precisão dos recursos GTO/HUD/comportamento (fontes verificadas).

- MDF & α: exemplo canônico do GTO Wizard — aposta 60 num pote de 100:
  α = 60/160 = 37,5% e MDF = 100/160 = 62,5%.
- HUD: definições padrão (VPIP, PFR, WTSD, W$SD) calculadas do log de ações.
- Tilt: Palomäki et al. (2014) — agressão sobe nas mãos seguintes a perda grande.
"""

from poker_arena.application.analysis import _blockers, _realization
from poker_arena.application.reasoning import _gto_numbers
from poker_arena.application.watch_stats import LIVE_TIMELINE_LIMIT, WatchStats, bucket_of
from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.bots.opponent_model import OpponentModel
from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.evaluator import card_from_str
from poker_arena.engine.player import Player, PlayerStatus


def _c(s):
    return card_from_str(s)


def _obs(pot, to_call, me_bet=0, me_stack=1000, seat=0):
    me = PublicPlayer(
        seat=seat,
        name="X",
        stack=me_stack,
        current_bet=me_bet,
        total_committed=me_bet,
        status="active",
        is_button=False,
    )
    return Observation(
        seat=seat,
        hole=(_c("Ah"), _c("Kd")),
        board=(),
        pot=pot,
        to_call=to_call,
        current_bet=me_bet + to_call,
        min_raise_to=0,
        legal_actions=frozenset(),
        players=(me,),
        num_active=2,
    )


# ---------- MDF & alpha (GTO) ----------
def test_mdf_facing_bet_matches_canonical_example():
    # aposta 60 no pote de 100 -> pote vira 160; MDF = 100/160 = 62,5%
    mdf, _ = _gto_numbers(_obs(pot=160, to_call=60), Action(ActionType.CALL))
    assert mdf == 62  # round(62.5) -> 62 (meio pra par)


def test_bluff_alpha_for_a_bet():
    # aposta de 60 num pote de 100: alpha = 60/(60+100) = 37,5%
    _, alpha = _gto_numbers(_obs(pot=100, to_call=0), Action(ActionType.RAISE, amount=60))
    assert alpha == 38  # round(37.5) -> 38


def test_no_alpha_when_action_is_not_aggressive():
    mdf, alpha = _gto_numbers(_obs(pot=100, to_call=0), Action(ActionType.CHECK))
    assert mdf is None and alpha is None


# ---------- HUD stats (watch_stats) ----------
def _seats():
    return [
        {"seat": 0, "name": "A", "level": "random", "start": 1000, "position": "BTN"},
        {"seat": 1, "name": "B", "level": "random", "start": 1000, "position": "SB"},
        {"seat": 2, "name": "C", "level": "random", "start": 1000, "position": "BB"},
    ]


def test_watch_stats_uses_player_identity_when_a_name_is_reused():
    ws = WatchStats()
    first = {
        "seat": 0,
        "player_id": "a" * 32,
        "name": "Mesmo Nome",
        "level": "random",
        "start": 1000,
        "position": "BTN",
    }
    ws.begin_hand([first])
    ws.action(first["player_id"], "raise", "preflop")
    ws.finish_hand(
        [{"seat": 0, "player_id": first["player_id"], "name": first["name"]}],
        20,
        [{**first, "end": 1020, "delta": 20}],
        showdown=False,
    )

    replacement = {**first, "player_id": "b" * 32, "start": 500}
    ws.begin_hand([replacement])

    assert ws.per[first["player_id"]]["hands_dealt"] == 1
    assert ws.per[replacement["player_id"]]["hands_dealt"] == 1
    assert ws.per[replacement["player_id"]]["hands_won"] == 0
    assert ws.per[replacement["player_id"]]["start"] == 500


def test_watch_stats_live_timeline_is_bounded_without_losing_total_hands():
    ws = WatchStats()
    player_id = "c" * 32
    participant = {
        "seat": 0,
        "player_id": player_id,
        "name": "C",
        "level": "random",
        "start": 1000,
        "position": "BTN",
    }
    total = LIVE_TIMELINE_LIMIT + 7
    for hand in range(total):
        ws.begin_hand([participant])
        ws.finish_hand(
            [],
            0,
            [{**participant, "end": 1000 + hand, "delta": hand}],
            showdown=False,
        )

    assert ws.hands == total
    assert len(ws.timeline) == LIVE_TIMELINE_LIMIT
    assert ws.timeline[0]["stacks"][player_id] == 1000 + (total - LIVE_TIMELINE_LIMIT)


def test_pfr_counts_only_preflop_raises():
    ws = WatchStats()
    ws.begin_hand(_seats())
    ws.action("A", "raise", "preflop")  # PFR + VPIP
    ws.action("B", "call", "preflop")  # só VPIP
    ws.action("C", "check", "preflop")  # nada (BB de graça)
    ws.finish_hand(
        [{"seat": 0, "name": "A"}],
        60,
        [
            {"seat": 0, "name": "A", "end": 1040, "delta": 40},
            {"seat": 1, "name": "B", "end": 980, "delta": -20},
            {"seat": 2, "name": "C", "end": 980, "delta": -20},
        ],
        showdown=False,
    )
    assert ws.per["A"]["pfr"] == 1 and ws.per["A"]["vpip"] == 1
    assert ws.per["B"]["pfr"] == 0 and ws.per["B"]["vpip"] == 1
    assert ws.per["C"]["pfr"] == 0 and ws.per["C"]["vpip"] == 0


def test_all_in_call_is_vpip_but_not_aggression_or_pfr():
    ws = WatchStats()
    ws.begin_hand(_seats())
    ws.action("A", "all_in", "preflop", aggressive=False)
    ws.finish_hand([], 60, [], showdown=False)

    assert ws.per["A"]["vpip"] == 1
    assert ws.per["A"]["pfr"] == 0
    assert ws.per["A"]["aggressive"] == 0


def test_late_joiner_uses_its_buy_in_as_profit_baseline():
    ws = WatchStats()
    ws.begin_hand(_seats()[:2])
    ws.finish_hand([], 0, [], showdown=False)

    joined = {"seat": 2, "name": "D", "level": "random", "start": 500, "position": "BB"}
    ws.begin_hand([*_seats()[:2], joined])

    assert ws.per["D"]["start"] == 500


def test_wtsd_and_wsd_from_showdown_contenders():
    ws = WatchStats()
    ws.begin_hand(_seats())
    ws.action("A", "call", "preflop")
    ws.action("B", "call", "preflop")
    ws.action("A", "check", "flop")  # viu o flop
    ws.action("B", "check", "flop")
    ws.finish_hand(
        [{"seat": 0, "name": "A"}],
        100,
        [
            {"seat": 0, "name": "A", "end": 1050, "delta": 50},
            {"seat": 1, "name": "B", "end": 950, "delta": -50},
            {"seat": 2, "name": "C", "end": 1000, "delta": 0},
        ],
        showdown=True,
        contenders=["A", "B"],
    )
    assert ws.per["A"]["saw_flop"] == 1 and ws.per["A"]["wtsd"] == 1 and ws.per["A"]["wsd"] == 1
    assert ws.per["B"]["wtsd"] == 1 and ws.per["B"]["wsd"] == 0
    assert ws.per["C"]["wtsd"] == 0  # não disputou


def test_positional_buckets():
    assert bucket_of("UTG") == "early" and bucket_of("UTG+1") == "early"
    assert bucket_of("MP") == "middle" and bucket_of("LJ") == "middle"
    assert bucket_of("CO") == "late" and bucket_of("HJ") == "late" and bucket_of("BTN") == "late"
    assert bucket_of("SB") == "blinds" and bucket_of("BB") == "blinds"
    ws = WatchStats()
    ws.begin_hand(_seats())
    ws.action("A", "raise", "preflop")
    ws.finish_hand(
        [],
        0,
        [
            {"seat": 0, "name": "A", "end": 1000, "delta": 0},
            {"seat": 1, "name": "B", "end": 1000, "delta": 0},
            {"seat": 2, "name": "C", "end": 1000, "delta": 0},
        ],
        showdown=False,
    )
    assert ws.per["A"]["pos"]["late"] == [1, 1, 1]  # BTN: 1 mão, 1 vpip, 1 pfr
    assert ws.per["B"]["pos"]["blinds"][0] == 1


# ---------- Equity Realization (posição na ordem pós-flop) ----------
def _players(n, folded=()):
    ps = [Player(f"P{i}", 1000) for i in range(n)]
    for i in folded:
        ps[i].status = PlayerStatus.FOLDED
    return ps


def test_realization_in_position_is_high():
    # 3 jogadores, botão=2 -> ordem pós-flop 0,1,2: o botão fecha a ação
    label, _ = _realization(2, 2, _players(3))
    assert label == "alta"


def test_realization_first_to_act_is_low():
    label, _ = _realization(0, 2, _players(3))
    assert label == "baixa"


def test_realization_ignores_folded_players():
    # com o seat 2 (botão) fora, o último ativo vira o 1 -> realização alta
    label, _ = _realization(1, 2, _players(3, folded=(2,)))
    assert label == "alta"


def test_realization_ignores_all_in_players_who_cannot_act():
    players = _players(4, folded=(3,))
    players[0].status = PlayerStatus.ALL_IN
    label, _ = _realization(1, 3, players)
    assert label == "baixa"


# ---------- Blockers ----------
def test_nut_flush_blocker_detected():
    hole = [_c("Ah"), _c("5s")]
    board = [_c("Kh"), _c("Qh"), _c("2h")]
    notes = _blockers(hole, board)
    assert any("nut flush" in n for n in notes)


def test_paired_board_blocker_detected():
    hole = [_c("7h"), _c("As")]
    board = [_c("7s"), _c("7d"), _c("2c")]
    notes = _blockers(hole, board)
    assert any("quadra/full" in n for n in notes)


def test_no_blockers_preflop_or_without_holdings():
    assert _blockers([_c("Ah"), _c("Kd")], []) == []
    assert _blockers([_c("2c"), _c("3d")], [_c("Kh"), _c("Qh"), _c("2h")]) == []


# ---------- Detector de tilt ----------
def _base_model():
    m = OpponentModel()
    for _ in range(8):  # base 100% passiva (8 calls, 0 raises)
        m.observe("call", to_call=10)
    return m


def test_tilt_fires_after_big_loss_and_aggression_spike():
    m = _base_model()
    assert m.tilt is False
    m.note_hand_result(-20.0)  # perdeu 20 bb -> abre a janela
    for _ in range(3):
        m.observe("raise", to_call=10)  # só agressão na janela
    assert m.tilt is True
    assert m.tilt_delta >= 0.25


def test_tilt_needs_minimum_window_sample():
    m = _base_model()
    m.note_hand_result(-20.0)
    m.observe("raise", to_call=10)  # 1 ação só: amostra insuficiente
    assert m.tilt is False


def test_tilt_window_expires():
    m = _base_model()
    m.note_hand_result(-20.0)
    for _ in range(3):
        m.observe("raise", to_call=10)
    assert m.tilt is True
    m.note_hand_result(0.0)  # mão 1 depois da perda
    m.note_hand_result(0.0)  # mão 2 -> janela fecha
    assert m.tilt is False


def test_no_tilt_without_big_loss():
    m = _base_model()
    m.note_hand_result(-5.0)  # perda pequena não abre janela
    for _ in range(3):
        m.observe("raise", to_call=10)
    assert m.tilt is False

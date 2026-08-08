import pytest

from poker_arena.application.competitive_intelligence import (
    MIN_OPPORTUNITIES,
    build_profile,
    estimate,
)
from poker_arena.application.watch_stats import WatchStats


def _seats():
    return [
        {
            "seat": 0,
            "player_id": "a" * 32,
            "name": "A",
            "level": "random",
            "start": 1000,
            "position": "BTN",
        },
        {
            "seat": 1,
            "player_id": "b" * 32,
            "name": "B",
            "level": "random",
            "start": 1000,
            "position": "SB",
        },
        {
            "seat": 2,
            "player_id": "c" * 32,
            "name": "C",
            "level": "random",
            "start": 1000,
            "position": "BB",
        },
    ]


def _results(seats):
    return [{**seat, "end": seat["start"], "delta": 0} for seat in seats]


def _signal(profile, key):
    return next(signal for signal in profile.signals if signal.key == key)


def test_estimate_abstains_without_opportunities_and_exposes_neutral_prior():
    signal = estimate(
        "test",
        0,
        0,
        label="Teste",
        family="teste",
        context="sem dados",
    )

    assert signal.observed_rate is None
    assert signal.posterior_mean == 0.5
    assert signal.interval95_low is None
    assert signal.interval95_high is None
    assert signal.evidence == "insufficient"
    assert signal.ready is False


def test_estimate_reports_counts_shrinkage_wilson_interval_and_readiness():
    signal = estimate(
        "test",
        9,
        MIN_OPPORTUNITIES,
        label="Teste",
        family="teste",
        context="amostra",
    )

    assert signal.observed_rate == 0.75
    assert signal.posterior_mean == pytest.approx(10 / 14, abs=1e-4)
    assert signal.interval95_low is not None and 0 < signal.interval95_low < 0.75
    assert signal.interval95_high is not None and 0.75 < signal.interval95_high < 1
    assert signal.evidence == "emerging"
    assert signal.ready is True


def test_contextual_profile_counts_position_roles_responses_and_order():
    seats = _seats()
    ws = WatchStats()
    ws.begin_hand(seats)

    ws.action(seats[0]["player_id"], "raise", "preflop", aggressive=True, to_call=20)
    ws.action(seats[1]["player_id"], "call", "preflop", aggressive=False, to_call=30)
    ws.action(seats[2]["player_id"], "raise", "preflop", aggressive=True, to_call=20)
    ws.street_started("flop", [seat["player_id"] for seat in seats])
    ws.action(
        seats[0]["player_id"],
        "fold",
        "flop",
        aggressive=False,
        to_call=40,
        in_position=False,
    )
    ws.action(
        seats[1]["player_id"],
        "raise",
        "flop",
        aggressive=True,
        to_call=0,
        in_position=True,
    )
    ws.finish_hand([], 0, _results(seats), showdown=False)

    opener = build_profile(ws.per[seats[0]["player_id"]])
    small_blind = build_profile(ws.per[seats[1]["player_id"]])
    big_blind = build_profile(ws.per[seats[2]["player_id"]])

    assert (
        _signal(opener, "preflop_open_raise").opportunities,
        _signal(opener, "preflop_open_raise").successes,
    ) == (1, 1)
    assert (
        _signal(small_blind, "preflop_three_bet").opportunities,
        _signal(small_blind, "preflop_three_bet").successes,
    ) == (1, 0)
    assert (
        _signal(small_blind, "blind_defense").opportunities,
        _signal(small_blind, "blind_defense").successes,
    ) == (1, 1)
    assert (
        _signal(big_blind, "preflop_three_bet").opportunities,
        _signal(big_blind, "preflop_three_bet").successes,
    ) == (1, 1)
    assert (
        _signal(opener, "postflop_fold_to_bet").opportunities,
        _signal(opener, "postflop_fold_to_bet").successes,
    ) == (1, 1)
    assert (
        _signal(opener, "postflop_aggression_oop").opportunities,
        _signal(opener, "postflop_aggression_oop").successes,
    ) == (1, 0)
    assert (
        _signal(small_blind, "postflop_aggression_ip").opportunities,
        _signal(small_blind, "postflop_aggression_ip").successes,
    ) == (1, 1)
    assert opener.scope == "local_session_only"
    assert opener.authority == "descriptive_only_no_action_advice"


def test_context_validation_rejects_ambiguous_or_impossible_values():
    seats = _seats()[:1]
    ws = WatchStats()
    ws.begin_hand(seats)

    with pytest.raises(ValueError, match="inteiro não negativo"):
        ws.action(seats[0]["player_id"], "check", "preflop", to_call=-1)

    with pytest.raises(ValueError, match="IP/OOP"):
        ws.action(seats[0]["player_id"], "check", "flop", in_position="yes")


def test_exact_positions_steal_squeeze_four_bet_and_blind_roles_use_real_opportunities():
    labels = ["BTN", "SB", "BB", "UTG", "HJ", "CO"]
    seats = [
        {
            "seat": seat,
            "player_id": chr(97 + seat) * 32,
            "name": label,
            "level": "random",
            "start": 1000,
            "position": label,
        }
        for seat, label in enumerate(labels)
    ]
    by_position = {seat["position"]: seat for seat in seats}
    ws = WatchStats()
    ws.begin_hand(seats)

    ws.action(by_position["UTG"]["player_id"], "fold", "preflop", to_call=20)
    ws.action(by_position["HJ"]["player_id"], "fold", "preflop", to_call=20)
    ws.action(by_position["CO"]["player_id"], "raise", "preflop", to_call=20)
    ws.action(by_position["BTN"]["player_id"], "call", "preflop", to_call=40)
    ws.action(by_position["SB"]["player_id"], "raise", "preflop", to_call=30)
    ws.action(by_position["BB"]["player_id"], "fold", "preflop", to_call=100)
    ws.finish_hand([], 0, _results(seats), showdown=False)

    cutoff = build_profile(ws.per[by_position["CO"]["player_id"]])
    button = build_profile(ws.per[by_position["BTN"]["player_id"]])
    small_blind = build_profile(ws.per[by_position["SB"]["player_id"]])
    big_blind = build_profile(ws.per[by_position["BB"]["player_id"]])

    assert (
        _signal(cutoff, "late_position_steal").opportunities,
        _signal(cutoff, "late_position_steal").successes,
    ) == (1, 1)
    assert (
        _signal(cutoff, "position_exact_CO_pfr").opportunities,
        _signal(cutoff, "position_exact_CO_pfr").successes,
    ) == (1, 1)
    assert (
        _signal(button, "preflop_call_vs_raise").opportunities,
        _signal(button, "preflop_call_vs_raise").successes,
    ) == (1, 1)
    assert (
        _signal(small_blind, "preflop_squeeze").opportunities,
        _signal(small_blind, "preflop_squeeze").successes,
    ) == (1, 1)
    assert (
        _signal(big_blind, "preflop_four_bet").opportunities,
        _signal(big_blind, "preflop_four_bet").successes,
    ) == (1, 0)


def test_blind_versus_blind_and_isolation_roles_are_kept_separate():
    seats = _seats()
    ws = WatchStats()
    ws.begin_hand(seats)
    ws.action(seats[0]["player_id"], "fold", "preflop", to_call=20)
    ws.action(seats[1]["player_id"], "raise", "preflop", to_call=10)
    ws.action(seats[2]["player_id"], "call", "preflop", to_call=20)
    ws.finish_hand([], 0, _results(seats), showdown=False)

    small_blind = build_profile(ws.per[seats[1]["player_id"]])
    big_blind = build_profile(ws.per[seats[2]["player_id"]])
    assert (
        _signal(small_blind, "blind_vs_blind_sb_open").opportunities,
        _signal(small_blind, "blind_vs_blind_sb_open").successes,
    ) == (1, 1)
    assert (
        _signal(big_blind, "blind_vs_blind_bb_defense").opportunities,
        _signal(big_blind, "blind_vs_blind_bb_defense").successes,
    ) == (1, 1)
    assert (_signal(big_blind, "blind_fold_to_steal").successes) == 0

    isolation = WatchStats()
    isolation.begin_hand(seats)
    isolation.action(seats[0]["player_id"], "call", "preflop", to_call=20)
    isolation.action(seats[1]["player_id"], "raise", "preflop", to_call=10)
    isolation.action(seats[2]["player_id"], "call", "preflop", to_call=40)
    isolation.finish_hand([], 0, _results(seats), showdown=False)
    opener = build_profile(isolation.per[seats[0]["player_id"]])
    isolator = build_profile(isolation.per[seats[1]["player_id"]])
    assert _signal(opener, "preflop_limp").successes == 1
    assert _signal(isolator, "preflop_isolation_raise").successes == 1

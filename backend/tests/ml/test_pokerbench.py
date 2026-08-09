import pytest

from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.engine.actions import ActionType
from poker_arena.engine.cards import Card, Rank, Suit
from poker_arena.ml.encoder import ACTIONS, FEATURE_SIZE
from poker_arena.ml.encoder_v2 import CARD_FEATURES, MAX_HISTORY
from poker_arena.ml.pokerbench import (
    MAX_TARGET_SIZING_RELATIVE_ERROR,
    bucket_action,
    featurize,
    featurize_v2,
    featurize_v2_input,
    legal_from_moves,
    parse_card,
    parse_cards,
    row_to_observation,
    target_v2,
)

# registro pós-flop real (do dataset RZ412/PokerBench, exemplo verificado na fonte)
REAL_ROW = {
    "holding": "King of Diamond and Jack of Spade",
    "board_flop": "King Of Spade, Seven Of Heart, Two Of Diamond",
    "board_turn": "Jack Of Club",
    "board_river": "Seven Of Club",
    "pot_size": 24.0,
    "hero_position": "IP",
    "aggressor_position": "OOP",
    "available_moves": "['Bet', 'Check']",
    "preflop_action": "HJ/2.0bb/BB/call",
    "postflop_action": "OOP_CHECK/IP_BET_3/OOP_RAISE_10/IP_CALL",
    "correct_decision": "bet 18",
    "num_players": 6,
}


def test_parse_card_formats():
    assert str(parse_card("King of Diamond")) == "Kd"
    assert str(parse_card("Seven Of Heart")) == "7h"
    assert str(parse_card("Ten of Clubs")) == "Tc"  # plural tolerado
    assert str(parse_card("Ace of Spade")) == "As"


def test_parse_cards_phrase_and_board():
    assert len(parse_cards("King of Diamond and Jack of Spade")) == 2
    assert len(parse_cards("King Of Spade, Seven Of Heart, Two Of Diamond")) == 3
    assert parse_cards("") == []
    assert parse_cards(None) == []


def test_parse_cards_accepts_compact_pokerbench_notation():
    """The published PokerBench rows use compact strings, not English prose."""
    assert [str(c) for c in parse_cards("KdKc")] == ["Kd", "Kc"]
    assert [str(c) for c in parse_cards("Ks7h2d")] == ["Ks", "7h", "2d"]
    assert [str(c) for c in parse_cards("Th 9c")] == ["Th", "9c"]


def test_v2_sizing_mapping_rejects_more_than_ten_percent_distortion() -> None:
    observation = Observation(
        seat=0,
        hole=(Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)),
        board=(),
        pot=100,
        to_call=0,
        current_bet=0,
        min_raise_to=20,
        legal_actions=frozenset({ActionType.CHECK, ActionType.RAISE, ActionType.ALL_IN}),
        players=(
            PublicPlayer(0, "hero", 1_000, 0, 0, "active", True),
            PublicPlayer(1, "villain", 1_000, 0, 0, "active", False),
        ),
        num_active=2,
    )
    assert MAX_TARGET_SIZING_RELATIVE_ERROR == 0.10
    _target, accepted_error, accepted_ambiguous = target_v2(
        {"correct_decision": "raise 5.5"}, observation
    )
    _target, rejected_error, rejected_ambiguous = target_v2(
        {"correct_decision": "raise 5.6"}, observation
    )
    assert accepted_error < MAX_TARGET_SIZING_RELATIVE_ERROR
    assert accepted_ambiguous is False
    assert rejected_error > MAX_TARGET_SIZING_RELATIVE_ERROR
    assert rejected_ambiguous is True


def test_bucket_action_maps_to_our_five():
    assert bucket_action("fold", 24, 100) == ACTIONS.index("fold")
    assert bucket_action("check", 24, 100) == ACTIONS.index("check_call")
    assert bucket_action("call", 24, 100) == ACTIONS.index("check_call")
    # 18 <= 0.75*24=18 -> raise_half
    assert bucket_action("bet 18", 24, 100) == ACTIONS.index("raise_half")
    # 30 > 18 e < stack -> raise_pot
    assert bucket_action("bet 30", 24, 100) == ACTIONS.index("raise_pot")
    # aposta ~ todo o stack -> all_in
    assert bucket_action("raise 98", 24, 100) == ACTIONS.index("all_in")
    assert bucket_action("all-in", 24, 100) == ACTIONS.index("all_in")


def test_legal_from_moves():
    legal = legal_from_moves("['Fold', 'Call', 'Raise']")
    names = {a.value for a in legal}
    assert names == {"fold", "call", "raise"}


def test_legal_from_moves_recognizes_numeric_raise_choices():
    legal = legal_from_moves("['3.0bb', 'call', 'fold']")
    assert {a.value for a in legal} == {"raise", "call", "fold"}


def test_featurize_real_row():
    feats, mask, target = featurize({**REAL_ROW, "hero_position": "HJ"})
    assert len(feats) == FEATURE_SIZE
    assert len(mask) == len(ACTIONS)
    # 2 hole cards e 5 board cards codificadas (one-hot nos blocos 0:52 e 52:104)
    assert sum(feats[:52]) == 2.0
    assert sum(feats[52:104]) == 5.0
    # alvo do solver ('bet 18') é raise_half e está dentro da máscara legal
    assert target == ACTIONS.index("raise_half")
    assert mask[target] is True


def test_featurize_preflop_row_has_empty_board():
    row = {
        "hero_holding": "Ace of Spade and King of Heart",
        "pot_size": 3.0,
        "hero_pos": "BTN",
        "available_moves": "['Fold', 'Call', 'Raise']",
        "prev_line": "UTG fold, HJ fold, CO raise 2.5 chips",
        "correct_decision": "call",
    }
    feats, mask, target = featurize(row)
    assert sum(feats[52:104]) == 0.0  # sem board no pré-flop
    assert target == ACTIONS.index("check_call")
    assert mask[target] is True


def test_featurize_published_compact_row():
    row = {
        "holding": "KdKc",
        "board_flop": "Ks7h2d",
        "board_turn": "Jh",
        "board_river": "7c",
        "pot_size": 24.0,
        "hero_position": "HJ",
        "available_moves": "['3.0bb', 'check']",
        "correct_decision": "bet 3.0bb",
    }
    feats, mask, target = featurize(row)
    assert sum(feats[:52]) == 2.0
    assert sum(feats[52:104]) == 5.0
    assert target == ACTIONS.index("raise_half")
    assert mask[target] is True


def test_rejects_target_that_is_absent_from_available_moves():
    row = {
        "holding": "AsKd",
        "pot_size": 3.0,
        "hero_position": "BTN",
        "available_moves": "['Fold']",
        "correct_decision": "call",
    }
    with pytest.raises(ValueError, match="available_moves"):
        row_to_observation(row)


@pytest.mark.parametrize("holding", ["As", "AsKdQh", "AsAs"])
def test_rejects_invalid_or_duplicate_hole_cards(holding):
    row = {
        "holding": holding,
        "pot_size": 3.0,
        "available_moves": "['Check']",
        "correct_decision": "check",
    }
    with pytest.raises(ValueError):
        row_to_observation(row)


@pytest.mark.parametrize("position", [None, "", "UTG+1", "NOT_A_POSITION"])
def test_rejects_missing_or_unsupported_hero_position(position):
    row = {
        "holding": "AsKd",
        "pot_size": 3.0,
        "hero_position": position,
        "available_moves": "['Check']",
        "correct_decision": "check",
    }
    with pytest.raises(ValueError, match="hero_position"):
        row_to_observation(row)


def test_v2_featurization_uses_multiseat_history_aware_contract():
    # This hand history contains only flop actions; the v2 anti-leak contract
    # therefore evaluates it at the flop instead of exposing future cards.
    example = featurize_v2({**REAL_ROW, "evaluation_at": "Flop"})
    assert len(example.encoded.cards) == CARD_FEATURES == 208
    assert len(example.encoded.global_features) == 24
    assert len(example.encoded.seats) == 9
    assert len(example.encoded.history) == MAX_HISTORY == 15
    assert len(example.encoded.legal_mask) == 10
    assert example.encoded.legal_mask[example.target_index] == 1.0


def test_v2_input_builder_does_not_consult_the_solver_label():
    row = {
        "hero_holding": "AsKd",
        "pot_size": 1.5,
        "hero_pos": "SB",
        "num_players": 1,
        "available_moves": "['3.0bb', 'call', 'fold']",
        "prev_line": "",
        "correct_decision": "INVALID_LABEL_MUST_NOT_BE_CONSULTED",
    }

    inputs = featurize_v2_input(row)

    assert inputs.observation.pot == 15
    assert len(inputs.encoded.legal_mask) == 10


def test_v2_rejects_postflop_row_without_an_explicit_decision_street():
    with pytest.raises(ValueError, match="explicit decision street"):
        featurize_v2(REAL_ROW)


def test_v2_rejects_board_that_is_incomplete_for_the_decision_street():
    row = {
        **REAL_ROW,
        "evaluation_at": "Turn",
        "board_turn": "",
        "postflop_action": "OOP_CHECK/IP_BET_3/OOP_RAISE_10/IP_CALL",
    }
    with pytest.raises(ValueError, match="does not match"):
        featurize_v2(row)


def test_v2_reconstructs_parseable_preflop_history_instead_of_zeroing_it():
    row = {
        "holding": "AsKd",
        "pot_size": 4.5,
        "hero_position": "HJ",
        "available_moves": "['Fold', 'Call', 'Raise 8']",
        "prev_line": "HJ/2.0bb/BB/call",
        "correct_decision": "call",
    }
    example = featurize_v2(row)
    assert [(event.street, event.action) for event in example.observation.history] == [
        ("preflop", "post_sb"),
        ("preflop", "post_bb"),
        ("preflop", "raise"),
        ("preflop", "call"),
    ]
    assert example.observation.history[-1].amount_added == 10
    assert sum(example.encoded.history_mask) == 4.0
    assert example.history_audit.expected_action_tokens == 2
    assert example.history_audit.emitted_action_events == 2
    assert example.history_audit.fidelity == 1.0


def test_v2_accepts_published_postflop_ip_oop_position_vocabulary():
    row = {
        "preflop_action": "HJ/2.0bb/BB/call",
        "board_flop": "Ks7h2d",
        "board_turn": "Jc",
        "board_river": "7c",
        "postflop_action": (
            "OOP_CHECK/IP_CHECK/dealcards/Jc/OOP_CHECK/IP_BET_5/OOP_RAISE_14/"
            "IP_CALL/dealcards/7c/OOP_CHECK"
        ),
        "evaluation_at": "River",
        "pot_size": 32,
        "hero_position": "IP",
        "holding": "8h8c",
        "available_moves": "['Check', 'Bet 24']",
        "correct_decision": "Check",
    }
    example = featurize_v2(row)
    assert len(example.observation.players) == 2
    assert example.target_index == 1


def test_turn_decision_never_sees_the_future_river_card():
    row = {
        "preflop_action": "HJ/2.0bb/BB/call",
        "board_flop": "8h8cTc",
        "board_turn": "As",
        "board_river": "4d",
        "evaluation_at": "Turn",
        "postflop_action": "OOP_CHECK/IP_CHECK/dealcards/As/OOP_CHECK",
        "pot_size": 4.5,
        "hero_position": "IP",
        "holding": "Ac4d",
        "available_moves": "['Check', 'Bet 5', 'Bet 8']",
        "correct_decision": "Check",
    }
    example = featurize_v2(row)
    assert [str(card) for card in example.observation.board] == ["8h", "8c", "Tc", "As"]
    assert "4d" not in {str(card) for card in example.observation.board}
    assert [event.street for event in example.observation.history[-3:]] == [
        "flop",
        "flop",
        "turn",
    ]


def test_v2_never_interprets_a_dealt_card_as_a_bet_amount():
    row = {
        "preflop_action": "HJ/2.0bb/BB/call",
        "board_flop": "AsKdQh",
        "board_turn": "7c",
        "evaluation_at": "Turn",
        "postflop_action": "OOP_CHECK/IP_CHECK/dealcards/7c/OOP_CHECK",
        "pot_size": 4.5,
        "aggressor_position": "IP",
        "hero_position": "IP",
        "holding": "2s2d",
        "available_moves": "['Check', 'Bet 3']",
        "correct_decision": "Check",
    }
    example = featurize_v2(row)
    postflop = [event for event in example.observation.history if event.street != "preflop"]
    assert [event.action for event in postflop] == ["check", "check", "check"]
    assert all(event.amount_added == 0 for event in postflop)
    assert example.history_audit.dealt_cards == 1


def test_v2_rejects_history_card_that_contradicts_the_labelled_board():
    row = {
        "preflop_action": "HJ/2.0bb/BB/call",
        "board_flop": "AsKdQh",
        "board_turn": "7c",
        "evaluation_at": "Turn",
        "postflop_action": "OOP_CHECK/IP_CHECK/dealcards/8c/OOP_CHECK",
        "pot_size": 4.5,
        "hero_position": "IP",
        "holding": "2s2d",
        "available_moves": "['Check', 'Bet 3']",
        "correct_decision": "Check",
    }
    with pytest.raises(ValueError, match="contradicts the published board"):
        featurize_v2(row)


def test_v2_rejects_history_that_crosses_beyond_decision_street():
    row = {
        "preflop_action": "HJ/2.0bb/BB/call",
        "board_flop": "AsKdQh",
        "evaluation_at": "Flop",
        "postflop_action": "OOP_CHECK/IP_CHECK/dealcards/7c",
        "pot_size": 4.5,
        "hero_position": "IP",
        "holding": "2s2d",
        "available_moves": "['Check', 'Bet 3']",
        "correct_decision": "Check",
    }
    with pytest.raises(ValueError, match="beyond the labelled decision street"):
        featurize_v2(row)


def test_v2_preserves_decimal_blinds_and_subtracts_hero_prior_investment():
    row = {
        "hero_holding": "AsKd",
        "pot_size": 13.0,
        "hero_pos": "SB",
        "available_moves": "['Call', 'Fold']",
        "prev_line": "SB/3.0bb/BB/10.0bb",
        "correct_decision": "call",
    }
    example = featurize_v2(row)
    hero = example.observation.players[example.observation.seat]
    assert hero.current_bet == 30
    assert example.observation.current_bet == 100
    assert example.observation.to_call == 70
    assert example.observation.pot == 130


def test_v2_updates_folded_status_and_active_count_from_history():
    row = {
        "hero_holding": "AsKd",
        "pot_size": 5.5,
        "hero_pos": "BB",
        "available_moves": "['Call', 'Fold']",
        "prev_line": "HJ/2.0bb/CO/fold/BTN/call/SB/fold",
        "correct_decision": "call",
    }
    example = featurize_v2(row)
    by_name = {player.name: player for player in example.observation.players}
    assert by_name["CO"].status == by_name["SB"].status == "folded"
    assert example.observation.num_active == 4


def test_v2_published_preflop_roster_marks_every_unmentioned_position_folded():
    row = {
        "hero_holding": "AsKd",
        "pot_size": 5.5,
        "hero_pos": "BB",
        "num_players": "5",
        "available_moves": "['Call', 'Fold']",
        "prev_line": "HJ/2.0bb/CO/fold/BTN/call/SB/fold",
        "correct_decision": "call",
    }
    example = featurize_v2(row)
    by_name = {player.name: player for player in example.observation.players}
    assert by_name["UTG"].status == "folded"
    assert by_name["CO"].status == by_name["SB"].status == "folded"
    assert example.observation.num_active == 3


def test_v2_rejects_preflop_participant_count_that_contradicts_positions():
    row = {
        "hero_holding": "AsKd",
        "pot_size": 5.5,
        "hero_pos": "BB",
        "num_players": "4",
        "available_moves": "['Call', 'Fold']",
        "prev_line": "HJ/2.0bb/CO/fold/BTN/call/SB/fold",
        "correct_decision": "call",
    }
    with pytest.raises(ValueError, match="num_players contradicts"):
        featurize_v2(row)


def test_v2_all_in_is_capped_by_remaining_stack_after_preflop_commitment():
    row = {
        "preflop_action": "HJ/2.0bb/BB/call",
        "board_flop": "AsKdQh",
        "evaluation_at": "Flop",
        "postflop_action": "OOP_ALL_IN",
        "pot_size": 102.5,
        "hero_position": "IP",
        "holding": "2s2d",
        "available_moves": "['Fold', 'Call']",
        "correct_decision": "fold",
    }
    example = featurize_v2(row)
    by_name = {player.name: player for player in example.observation.players}
    assert by_name["OOP"].total_committed == 1000
    assert by_name["OOP"].stack == 0
    assert by_name["OOP"].status == "all_in"
    assert example.observation.current_bet == 980
    assert example.observation.to_call == 980


def test_v2_rejects_a_labelled_decision_after_every_player_is_all_in():
    row = {
        "preflop_action": "HJ/2.0bb/BB/call",
        "board_flop": "AsKdQh",
        "evaluation_at": "Flop",
        "postflop_action": "OOP_BET_98/IP_CALL",
        "pot_size": 198.5,
        "hero_position": "OOP",
        "holding": "2s2d",
        "available_moves": "['Check']",
        "correct_decision": "check",
    }
    with pytest.raises(ValueError, match="acting hero must be active"):
        featurize_v2(row)


def test_v2_rejects_large_published_vs_reconstructed_pot_contradiction():
    row = {
        "preflop_action": "HJ/2.0bb/BB/call",
        "board_flop": "AsKdQh",
        "evaluation_at": "Flop",
        "postflop_action": "OOP_ALL_IN",
        "pot_size": 4.5,
        "hero_position": "IP",
        "holding": "2s2d",
        "available_moves": "['Fold', 'Call']",
        "correct_decision": "fold",
    }
    with pytest.raises(ValueError, match="published pot"):
        featurize_v2(row)

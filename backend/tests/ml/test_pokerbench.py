from poker_arena.ml.encoder import ACTIONS, FEATURE_SIZE
from poker_arena.ml.pokerbench import (
    bucket_action,
    featurize,
    legal_from_moves,
    parse_card,
    parse_cards,
)

# registro pós-flop real (do dataset RZ412/PokerBench, exemplo verificado na fonte)
REAL_ROW = {
    "holding": "King of Diamond and Jack of Spade",
    "board_flop": "King Of Spade, Seven Of Heart, Two Of Diamond",
    "board_turn": "Jack Of Club",
    "board_river": "Seven Of Club",
    "pot_size": 24.0,
    "hero_position": "HJ",
    "available_moves": "['Bet', 'Check']",
    "preflop_action": "HJ raise 2.0 chips, and BB call",
    "postflop_action": "BB check, HJ bet 3 chips, BB raise 10 chips, HJ call",
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


def test_legal_from_moves():
    legal = legal_from_moves("['Fold', 'Call', 'Raise']")
    names = {a.value for a in legal}
    assert names == {"fold", "call", "raise"}


def test_featurize_real_row():
    feats, mask, target = featurize(REAL_ROW)
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

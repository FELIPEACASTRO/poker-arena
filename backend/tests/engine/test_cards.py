from poker_arena.engine.cards import Card, Deck, Rank, Suit


def test_card_string_is_treys_compatible():
    assert str(Card(Rank.ACE, Suit.SPADES)) == "As"
    assert str(Card(Rank.TEN, Suit.HEARTS)) == "Th"
    assert str(Card(Rank.TWO, Suit.CLUBS)) == "2c"


def test_deck_has_52_unique_cards():
    deck = Deck()
    assert len(deck.cards) == 52
    assert len(set(str(c) for c in deck.cards)) == 52


def test_shuffle_is_deterministic_with_seed():
    a, b = Deck(seed=42), Deck(seed=42)
    a.shuffle()
    b.shuffle()
    assert [str(c) for c in a.cards] == [str(c) for c in b.cards]


def test_deal_removes_cards_from_top():
    deck = Deck(seed=1)
    deck.shuffle()
    top2 = deck.cards[:2]
    dealt = deck.deal(2)
    assert dealt == top2
    assert len(deck.cards) == 50

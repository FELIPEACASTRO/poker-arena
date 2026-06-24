from poker_arena.bots.adaptive_bot import AdaptiveBot
from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.bots.opponent_model import OpponentModel
from poker_arena.engine.actions import ActionType
from poker_arena.engine.cards import Card, Rank, Suit


def _obs():
    # mao mediana (7-5 offsuit ~0.43), to_call=0 -> pode dar check OU raise
    players = (
        PublicPlayer(0, "me", 1000, 0, 0, "active", True),
        PublicPlayer(1, "voce", 1000, 0, 0, "active", False),
    )
    return Observation(
        seat=0,
        hole=(Card(Rank.SEVEN, Suit.SPADES), Card(Rank.FIVE, Suit.HEARTS)),
        board=(), pot=30, to_call=0, current_bet=0, min_raise_to=20,
        legal_actions=frozenset({ActionType.CHECK, ActionType.RAISE}),
        players=players, num_active=2,
    )


def _over_folder():
    m = OpponentModel()
    for _ in range(20):
        m.observe("fold", to_call=10)  # desiste sempre que enfrenta aposta
    return m


def _calling_station():
    m = OpponentModel()
    for _ in range(20):
        m.observe("call", to_call=10)  # paga sempre, nunca desiste
    return m


def test_bluffs_against_over_folder():
    # contra quem desiste demais, o bot pressiona (RAISE) ate com mao mediana
    action = AdaptiveBot(_over_folder()).act(_obs())
    assert action.type == ActionType.RAISE


def test_holds_back_against_calling_station():
    # contra quem paga tudo, o bot nao blefa -> da CHECK com a mesma mao
    action = AdaptiveBot(_calling_station()).act(_obs())
    assert action.type == ActionType.CHECK


def test_neutral_without_reads_does_not_bluff():
    # sem dados do oponente (modelo vazio), joga a forca crua -> CHECK
    action = AdaptiveBot(OpponentModel()).act(_obs())
    assert action.type == ActionType.CHECK

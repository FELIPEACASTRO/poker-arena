from poker_arena.bots.opponent_model import OpponentModel


def test_neutral_with_few_samples():
    m = OpponentModel()
    assert m.fold_to_bet == 0.5  # sem dados -> neutro
    assert m.aggression == 0.5
    assert m.samples == 0


def test_fold_to_bet_after_enough_samples():
    m = OpponentModel()
    for _ in range(10):
        m.observe("fold", to_call=10)  # sempre desiste diante de aposta
    assert m.fold_to_bet == 1.0
    assert m.samples == 10


def test_call_does_not_count_as_fold():
    m = OpponentModel()
    for _ in range(10):
        m.observe("call", to_call=10)
    assert m.fold_to_bet == 0.0  # nunca desistiu
    assert m.aggression == 0.0   # nenhum raise


def test_aggression_tracks_raises():
    m = OpponentModel()
    for _ in range(6):
        m.observe("raise", to_call=10)
    for _ in range(2):
        m.observe("call", to_call=10)
    assert round(m.aggression, 2) == 0.75  # 6 raises / 8 acoes agressivas+passivas


def test_action_with_no_bet_to_call_is_not_fold_to_bet():
    m = OpponentModel()
    m.observe("check", to_call=0)  # check de graca nao conta como enfrentar aposta
    assert m.faced_bet == 0


def test_read_returns_rounded_summary():
    m = OpponentModel()
    for _ in range(10):
        m.observe("fold", to_call=5)
    r = m.read()
    assert r.fold_to_bet == 1.0
    assert r.samples == 10

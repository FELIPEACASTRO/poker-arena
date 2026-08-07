from poker_arena.engine.evaluator import card_from_str, compare


def _c(s):
    """Helper: 'As' -> Card."""
    return card_from_str(s)


def test_royal_flush_beats_trips():
    board = [_c("Ah"), _c("Kh"), _c("Qh"), _c("2c"), _c("3d")]
    royal = [_c("Jh"), _c("Th")]  # straight flush real de copas
    trips = [_c("Ad"), _c("Ac")]  # trinca de ases
    assert compare(royal, trips, board) > 0


def test_higher_pair_beats_lower_pair():
    board = [_c("2h"), _c("7d"), _c("9s"), _c("Jc"), _c("4h")]
    kings = [_c("Kh"), _c("Kd")]
    queens = [_c("Qh"), _c("Qd")]
    assert compare(kings, queens, board) > 0


def test_identical_hands_tie():
    board = [_c("2h"), _c("7d"), _c("9s"), _c("Jc"), _c("4h")]
    a = [_c("Ah"), _c("Kd")]
    b = [_c("As"), _c("Kc")]
    assert compare(a, b, board) == 0

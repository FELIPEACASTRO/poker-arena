from __future__ import annotations

from copy import deepcopy

import pytest

from poker_arena.application import BotSpec, SessionConfig, build_session, match_log
from poker_arena.application.game_session import SessionIntegrityError


def test_fsync_failure_rolls_back_domain_stats_version_and_log(tmp_path, monkeypatch):
    monkeypatch.setenv("POKER_LOG_DIR", str(tmp_path))
    session = build_session(
        SessionConfig(
            mode="watch",
            bots=[BotSpec("A", "heuristic"), BotSpec("B", "heuristic")],
        ),
        seed=3,
    )
    logger = session._logger
    assert logger is not None
    original_fsync = match_log.os.fsync
    failed = False
    calls = 0

    def fail_once(file_descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated fsync failure")
        original_fsync(file_descriptor)

    monkeypatch.setattr(match_log.os, "fsync", fail_once)
    for index in range(100):
        before = session.snapshot()
        before_stats = deepcopy(vars(session._stats))
        before_log = logger.path.read_bytes()
        before_total = session.total_chips()
        try:
            session.execute_once(
                command_id=f"step-{index}",
                fingerprint=f"step-{index}",
                expected_version=before.version,
                operation=session.step,
            )
        except OSError as exc:
            assert "fsync" in str(exc)
            failed = True
            assert session.snapshot() == before
            assert vars(session._stats) == before_stats
            assert logger.path.read_bytes() == before_log
            assert session.total_chips() == before_total

            retry = session.execute_once(
                command_id=f"step-{index}",
                fingerprint=f"step-{index}",
                expected_version=before.version,
                operation=session.step,
            )
            assert retry.version == before.version + 1
            break

    assert failed, "the deterministic hand should have reached its durable append"


def test_uncopyable_bot_state_rejects_command_before_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("POKER_LOG_DIR", str(tmp_path))
    session = build_session(
        SessionConfig(bots=[BotSpec("B", "heuristic")]),
        seed=4,
    )
    bot = next(iter(session._bot_by_player.values()))
    executed = False

    class Uncopyable:
        def __deepcopy__(self, memo):
            del memo
            raise TypeError("cannot copy")

    bot._unsafe_test_state = Uncopyable()

    def operation() -> None:
        nonlocal executed
        executed = True

    with pytest.raises(SessionIntegrityError, match="cannot be transactionally checkpointed"):
        session.execute_once(
            command_id="unsafe",
            fingerprint="unsafe",
            expected_version=0,
            operation=operation,
        )

    assert not executed
    assert session.version == 0
    del bot._unsafe_test_state


@pytest.mark.parametrize("remove_during_active_hand", [True, False])
def test_removing_dealer_preserves_physical_successor(
    tmp_path, monkeypatch, remove_during_active_hand
):
    monkeypatch.setenv("POKER_LOG_DIR", str(tmp_path))
    session = build_session(
        SessionConfig(
            mode="watch",
            bots=[
                BotSpec("A", "heuristic"),
                BotSpec("B", "heuristic"),
                BotSpec("C", "heuristic"),
            ],
        ),
        seed=1,
    )
    if not remove_during_active_hand:
        while session.snapshot().view.phase == "bot_turn":
            session.step()

    button = session._table.button % len(session._table.players)
    roster = session.snapshot().view.roster
    expected_successor = roster[(button + 1) % len(roster)].player_id
    session.remove_player(button)

    if remove_during_active_hand:
        while session.snapshot().view.phase == "bot_turn":
            session.step()
    session.next_hand()

    next_button = next(seat for seat in session.snapshot().view.seats if seat.is_button)
    assert next_button.player_id == expected_successor

import pytest

from poker_arena.application import (
    BotSpec,
    InMemorySessionRepository,
    SessionConfig,
    SessionNotFound,
    build_session,
)


def _make(session_id):
    cfg = SessionConfig(bots=[BotSpec("B", "random")])
    return build_session(cfg, session_id=session_id, seed=1)


def test_add_get_remove():
    repo = InMemorySessionRepository()
    s = _make("abc")
    repo.add(s)
    assert repo.get("abc") is s
    repo.remove("abc")
    with pytest.raises(SessionNotFound):
        repo.get("abc")


def test_get_missing_raises():
    with pytest.raises(SessionNotFound):
        InMemorySessionRepository().get("nope")


def test_remove_missing_is_noop():
    InMemorySessionRepository().remove("nope")  # não levanta

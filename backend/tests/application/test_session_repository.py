import copy

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


def test_add_is_idempotent_for_same_object_but_rejects_id_collision():
    repo = InMemorySessionRepository()
    first = _make("same-id")
    # The audit layer now creates session logs exclusively, so constructing a
    # second real session with the same ID correctly fails before the repository
    # is reached.  A shallow duplicate isolates this repository identity contract
    # without weakening the write-once audit invariant.
    second = copy.copy(first)
    repo.add(first)
    repo.add(first)
    with pytest.raises(ValueError):
        repo.add(second)
    assert repo.get("same-id") is first


def test_generated_session_id_uses_full_uuid_entropy():
    session = build_session(
        SessionConfig(bots=[BotSpec("B", "random")]),
        seed=1,
    )
    assert len(session.id) == 32

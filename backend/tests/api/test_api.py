import pytest
from fastapi.testclient import TestClient

from poker_arena.api.app import create_app
from poker_arena.api.dependencies import get_repository
from poker_arena.application import InMemorySessionRepository


@pytest.fixture
def client():
    app = create_app()
    repo = InMemorySessionRepository()  # repo isolado por teste
    app.dependency_overrides[get_repository] = lambda: repo
    return TestClient(app)


def _create(client, level="heuristic", n=5, stack=500):
    body = {
        "bots": [{"name": f"B{i}", "level": level} for i in range(n)],
        "starting_stack": stack,
        "seed": 7,
    }
    return client.post("/tables", json=body)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_table_returns_state(client):
    r = _create(client)
    assert r.status_code == 201
    data = r.json()
    assert data["table_id"]
    assert len(data["seats"]) == 6
    assert data["phase"] in ("human_turn", "hand_over", "game_over")
    human = next(s for s in data["seats"] if s["kind"] == "human")
    assert human["cards"] is not None and len(human["cards"]) == 2


def test_get_table(client):
    tid = _create(client).json()["table_id"]
    r = client.get(f"/tables/{tid}")
    assert r.status_code == 200
    assert r.json()["table_id"] == tid


def test_get_missing_table_is_404(client):
    assert client.get("/tables/nope").status_code == 404


def test_unknown_bot_level_is_400(client):
    r = client.post("/tables", json={"bots": [{"name": "X", "level": "supergto"}]})
    assert r.status_code == 400


def test_human_fold_advances_the_hand(client):
    data = _create(client).json()
    tid = data["table_id"]
    if data["phase"] == "human_turn":
        r = client.post(f"/tables/{tid}/actions", json={"type": "fold"})
        assert r.status_code == 200
        assert r.json()["phase"] in ("hand_over", "game_over")


def test_illegal_check_returns_400(client):
    data = _create(client).json()
    tid = data["table_id"]
    if data["phase"] == "human_turn" and "check" not in (data["legal"] or {}).get("actions", []):
        r = client.post(f"/tables/{tid}/actions", json={"type": "check"})
        assert r.status_code == 400


def test_full_session_over_http_runs_clean(client):
    tid = _create(client, n=5).json()["table_id"]
    for _ in range(60):
        st = client.get(f"/tables/{tid}").json()
        if st["phase"] == "human_turn":
            assert client.post(f"/tables/{tid}/actions", json={"type": "fold"}).status_code == 200
        elif st["phase"] == "hand_over":
            assert client.post(f"/tables/{tid}/next-hand").status_code == 200
        else:  # game_over
            break
    # chegou a um estado terminal valido sem erro de HTTP
    assert client.get(f"/tables/{tid}").json()["phase"] in (
        "human_turn", "hand_over", "game_over"
    )


def test_next_hand_before_hand_over_is_400(client):
    data = _create(client).json()
    tid = data["table_id"]
    if data["phase"] == "human_turn":
        r = client.post(f"/tables/{tid}/next-hand")
        assert r.status_code == 400

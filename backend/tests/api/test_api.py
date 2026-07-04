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


def test_root_redirects_to_docs(client):
    # a raiz '/' nao pode dar 404 feio: redireciona pra documentacao interativa
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == "/docs"
    # e seguindo o redirect, chega na doc (200)
    assert client.get("/").status_code == 200


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_copilot_reviews_a_spot(client):
    r = client.post("/copilot", json={
        "hole": ["As", "Ah"], "board": ["Kd", "7c", "2s"],
        "pot": 100, "to_call": 20, "my_stack": 1000, "num_opponents": 1, "in_position": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["equity_pct"] >= 75  # AA overpair
    assert body["recommendation"] in ("call", "raise", "all_in")
    assert body["options"] and body["headline"]


def test_copilot_rejects_invalid_spot(client):
    r = client.post("/copilot", json={
        "hole": ["As", "As"], "board": [], "pot": 100, "to_call": 20, "my_stack": 1000,
    })
    assert r.status_code == 400


def test_from_image_reads_a_synthetic_table(client):
    import io

    from poker_arena.vision.synth import CANONICAL, render_table

    img, truth = render_table(seed=42, style=CANONICAL, n_board=5)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    r = client.post(
        "/copilot/from-image",
        files={"image": ("mesa.png", buf, "image/png")},
        data={"to_call": "40", "my_stack": "1000", "num_opponents": "2"},
    )
    assert r.status_code == 200
    body = r.json()
    # a visão detectou as cartas certas (estilo canônico) e o pipeline decidiu
    assert set(body["detected"]["hole"]) == set(truth["hole"])
    assert body["sanity"]["ok"] is True
    assert body["decision"] is not None
    assert body["decision"]["recommendation"] in ("fold", "check", "call", "raise", "all_in")


def test_levels_lists_available(client):
    from poker_arena.application.bot_factory import expert_model_path

    r = client.get("/levels")
    assert r.status_code == 200
    levels = r.json()["levels"]
    assert {"random", "heuristic", "montecarlo", "adaptive"} <= set(levels)
    # 'expert' aparece exatamente quando o modelo treinado existe no ambiente
    assert ("expert" in levels) == expert_model_path().exists()


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


def test_websocket_pushes_state_and_accepts_action(client):
    tid = _create(client).json()["table_id"]
    with client.websocket_connect(f"/tables/{tid}/ws") as ws:
        state = ws.receive_json()  # estado inicial enviado no connect
        assert state["table_id"] == tid
        assert len(state["seats"]) == 6
        if state["phase"] == "human_turn":
            ws.send_json({"type": "fold"})
            nxt = ws.receive_json()
            assert nxt["phase"] in ("hand_over", "game_over")


def test_watch_mode_steps_through_a_hand(client):
    body = {
        "mode": "watch",
        "bots": [{"name": f"B{i}", "level": "heuristic"} for i in range(6)],
        "starting_stack": 500,
        "seed": 7,
    }
    r = client.post("/tables", json=body)
    assert r.status_code == 201
    data = r.json()
    tid = data["table_id"]
    assert all(s["kind"] != "human" for s in data["seats"])
    assert all(s["cards"] is not None for s in data["seats"])  # cartas abertas
    assert data["phase"] in ("bot_turn", "hand_over")
    for _ in range(200):
        st = client.get(f"/tables/{tid}").json()
        if st["phase"] == "bot_turn":
            assert client.post(f"/tables/{tid}/step").status_code == 200
        else:
            break
    assert client.get(f"/tables/{tid}").json()["phase"] in ("hand_over", "game_over")


def test_glass_box_exposes_bot_reasoning(client):
    """Glass-box: ao jogar, o bot expõe o raciocínio REAL no assento."""
    body = {
        "mode": "watch",
        "bots": [{"name": f"B{i}", "level": "montecarlo"} for i in range(6)],
        "starting_stack": 500,
        "seed": 7,
    }
    tid = client.post("/tables", json=body).json()["table_id"]
    for _ in range(8):  # avança algumas jogadas pros bots decidirem
        st = client.get(f"/tables/{tid}").json()
        if st["phase"] == "bot_turn":
            client.post(f"/tables/{tid}/step")
        else:
            break
    seats = client.get(f"/tables/{tid}").json()["seats"]
    insights = [s["insight"] for s in seats if s["insight"] is not None]
    assert insights, "algum bot já deveria ter exposto seu raciocínio"
    ins = insights[0]
    assert ins["kind"] == "montecarlo"
    assert 0.0 <= ins["confidence"] <= 1.0
    assert ins["label"]


def test_step_in_play_mode_is_400(client):
    tid = _create(client).json()["table_id"]  # modo jogar
    assert client.post(f"/tables/{tid}/step").status_code == 400


def test_websocket_reports_illegal_action(client):
    data = _create(client).json()
    tid = data["table_id"]
    legal = (data.get("legal") or {}).get("actions", [])
    if data["phase"] == "human_turn" and "check" not in legal:
        with client.websocket_connect(f"/tables/{tid}/ws") as ws:
            ws.receive_json()  # estado inicial
            ws.send_json({"type": "check"})  # ilegal (há aposta a pagar)
            resp = ws.receive_json()
            assert "error" in resp

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
    r = client.post(
        "/copilot",
        json={
            "hole": ["As", "Ah"],
            "board": ["Kd", "7c", "2s"],
            "pot": 100,
            "to_call": 20,
            "my_stack": 1000,
            "effective_stack": 1000,
            "num_opponents": 1,
            "table_size": 2,
            "in_position": True,
            "hero_current_bet": 0,
            "current_bet": 20,
            "min_raise_increment": 20,
            "raise_reopened": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["equity_pct"] >= 75  # AA overpair
    assert body["recommendation"] in ("call", "raise", "all_in")
    assert body["options"] and body["headline"]


def test_copilot_rejects_invalid_spot(client):
    r = client.post(
        "/copilot",
        json={
            "hole": ["As", "As"],
            "board": [],
            "pot": 100,
            "to_call": 20,
            "my_stack": 1000,
            "effective_stack": 1000,
            "table_size": 2,
            "hero_current_bet": 0,
            "current_bet": 20,
            "min_raise_increment": 20,
            "raise_reopened": True,
        },
    )
    assert r.status_code == 400


def test_copilot_api_preserves_real_raise_to_context(client):
    response = client.post(
        "/copilot",
        json={
            "hole": ["As", "Ah"],
            "board": ["Kd", "7c", "2s"],
            "pot": 140,
            "to_call": 40,
            "my_stack": 980,
            "effective_stack": 980,
            "num_opponents": 1,
            "in_position": False,
            "position": "BB",
            "table_size": 3,
            "hero_current_bet": 20,
            "current_bet": 60,
            "min_raise_increment": 40,
            "raise_reopened": True,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["recommendation"] == "raise"
    assert response.json()["recommendation_amount"] == 100


@pytest.mark.parametrize("invalid_card", ["Asjunk", "10s", "Ás"])
def test_copilot_rejects_noncanonical_full_card_tokens(client, invalid_card):
    response = client.post(
        "/copilot",
        json={
            "hole": [invalid_card, "Kd"],
            "board": [],
            "pot": 10,
            "to_call": 0,
            "my_stack": 100,
            "effective_stack": 100,
            "num_opponents": 1,
            "in_position": False,
            "position": "SB",
            "hero_current_bet": 0,
            "current_bet": 0,
            "min_raise_increment": 20,
            "table_size": 2,
            "raise_reopened": True,
        },
    )

    assert response.status_code == 400


def test_from_image_reads_a_synthetic_table_and_fails_closed(client, tmp_path, monkeypatch):
    import io

    from poker_arena.vision.synth import CANONICAL, render_table

    # força a F1 (baseline determinístico) mesmo se houver um modelo F2 instalado localmente
    monkeypatch.setenv("POKER_VISION_MODEL", str(tmp_path / "sem_modelo.onnx"))
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
    # A F1 reconhece as cartas, mas a confiança conjunta fica abaixo do limiar
    # de produção. O endpoint deve abster-se, sem inventar uma decisão.
    assert set(body["detected"]["hole"]) == set(truth["hole"])
    assert body["sanity"]["ok"] is False
    assert body["decision"] is None
    assert body["engine"] == "F1-template"  # sem .onnx instalado -> baseline


def test_from_image_strict_mode_is_accepted(client, tmp_path, monkeypatch):
    import io

    from poker_arena.vision.synth import CANONICAL, render_table

    monkeypatch.setenv("POKER_VISION_MODEL", str(tmp_path / "sem_modelo.onnx"))  # força F1
    img, _ = render_table(seed=42, style=CANONICAL, n_board=5)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    r = client.post(
        "/copilot/from-image",
        files={"image": ("mesa.png", buf, "image/png")},
        data={"my_stack": "1000", "strict": "true"},
    )
    assert r.status_code == 200
    body = r.json()
    # em modo strict: ou decide (leitura confiável) ou abstém com motivo — nunca 500
    assert body["decision"] is not None or not body["sanity"]["ok"]
    import io

    from poker_arena.vision.synth import CANONICAL, render_table

    img, _ = render_table(seed=1, style=CANONICAL, n_board=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    # num_opponents=0 é inválido (mesa tem >=1 oponente) -> 422, não abstenção enganosa
    r = client.post(
        "/copilot/from-image",
        files={"image": ("mesa.png", buf, "image/png")},
        data={"num_opponents": "0"},
    )
    assert r.status_code == 422


def test_from_image_falls_back_to_f1_when_model_is_invalid(client, tmp_path, monkeypatch):
    import io

    from poker_arena.vision.synth import CANONICAL, render_table

    bad = tmp_path / "poker_vision.onnx"
    bad.write_bytes(b"nao sou um onnx valido")  # arquivo existe, mas é lixo
    monkeypatch.setenv("POKER_VISION_MODEL", str(bad))
    img, truth = render_table(seed=42, style=CANONICAL, n_board=5)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    r = client.post(
        "/copilot/from-image",
        files={"image": ("mesa.png", buf, "image/png")},
        data={"my_stack": "1000"},
    )
    assert r.status_code == 200  # NUNCA 500 por modelo inválido
    assert r.json()["engine"] == "F1-template"  # caiu na F1 graciosamente


def test_levels_lists_available(client):
    from poker_arena.application.bot_factory import expert_model_available

    r = client.get("/levels")
    assert r.status_code == 200
    levels = r.json()["levels"]
    assert {"random", "heuristic", "montecarlo", "adaptive"} <= set(levels)
    # existência isolada não basta: o gate de manifesto/hash/governança decide.
    assert ("expert" in levels) == expert_model_available()


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


def test_unknown_bot_level_is_validation_error(client):
    r = client.post("/tables", json={"bots": [{"name": "X", "level": "supergto"}]})
    assert r.status_code == 422


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
    assert client.get(f"/tables/{tid}").json()["phase"] in ("human_turn", "hand_over", "game_over")


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

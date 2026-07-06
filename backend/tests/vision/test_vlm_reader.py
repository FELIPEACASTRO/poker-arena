"""Leitor F3-VLM: prova o parsing/normalização/ausência-graciosa e o RESGATE no abstain.

Tudo sem um modelo real — o POST HTTP (`_post`) é mockado. Cobre: sem endpoint -> indispo-
nível; JSON puro / com cercas markdown / com texto ao redor -> RecognizedState; normalização
de cartas (10h->Th, maiúsc/minúsc, inválidas fora); erro de rede -> RuntimeError; e o wiring
do /from-image (VLM resgata um estado que o caminho rápido abandonou -> engine 'F3-vlm').
"""

from __future__ import annotations

import io
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from poker_arena.api.app import create_app
from poker_arena.vision import RecognizedState, vlm_reader


def _payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def _img_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (80, 60), (10, 80, 40)).save(buf, format="PNG")
    return buf.getvalue()


# ---------- disponibilidade ----------

def test_indisponivel_sem_endpoint(monkeypatch):
    monkeypatch.delenv("POKER_VLM_URL", raising=False)
    assert vlm_reader.vlm_available() is False
    with pytest.raises(vlm_reader.VlmUnavailable):
        vlm_reader.read_table_vlm(Image.new("RGB", (10, 10)))


def test_disponivel_com_endpoint(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://localhost:8080/v1/chat/completions")
    assert vlm_reader.vlm_available() is True


# ---------- parsing ----------

def test_le_json_puro(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://x/v1/chat/completions")
    monkeypatch.setattr(vlm_reader, "_post", lambda *a, **k: _payload(
        '{"hole":["As","Kd"],"board":["2h","6c","Tc"],"pot":700,'
        '"num_players":6,"position":"BTN","stacks":{"0":1500,"1":900}}'))
    st = vlm_reader.read_table_vlm(Image.new("RGB", (300, 200)))
    assert st.hole == ["As", "Kd"]
    assert st.board == ["2h", "6c", "Tc"]
    assert st.pot == 700 and st.pot_source == "vlm"
    assert st.n_players == 6 and st.position == "BTN"
    assert st.stacks == {0: 1500, 1: 900}
    assert st.n_cards == 5


def test_le_json_com_cercas_markdown(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://x")
    monkeypatch.setattr(vlm_reader, "_post", lambda *a, **k: _payload(
        '```json\n{"hole":["Qd","Th"],"board":[],"pot":null}\n```'))
    st = vlm_reader.read_table_vlm(Image.new("RGB", (10, 10)))
    assert st.hole == ["Qd", "Th"] and st.board == [] and st.pot is None


def test_extrai_json_com_texto_ao_redor(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://x")
    monkeypatch.setattr(vlm_reader, "_post", lambda *a, **k: _payload(
        'Claro! Aqui está: {"hole":["Ac","2d"],"board":["3s"]} — espero ajudar.'))
    st = vlm_reader.read_table_vlm(Image.new("RGB", (10, 10)))
    assert st.hole == ["Ac", "2d"] and st.board == ["3s"]


def test_normaliza_cartas(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://x")
    # '10h'->'Th', 'AS'->'As', 'kD'->'Kd', duplicata some, 'Zx'/'99' inválidas caem fora
    monkeypatch.setattr(vlm_reader, "_post", lambda *a, **k: _payload(
        '{"hole":["10h","AS"],"board":["kD","kD","Zx","99","7c"]}'))
    st = vlm_reader.read_table_vlm(Image.new("RGB", (10, 10)))
    assert st.hole == ["Th", "As"]
    assert st.board == ["Kd", "7c"]  # dedup + inválidas removidas


def test_campos_ausentes_viram_vazio(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://x")
    monkeypatch.setattr(vlm_reader, "_post", lambda *a, **k: _payload('{}'))
    st = vlm_reader.read_table_vlm(Image.new("RGB", (10, 10)))
    assert st.hole == [] and st.board == [] and st.pot is None
    assert st.n_players == 0 and st.position == "" and st.stacks is None


def test_posicao_invalida_e_descartada(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://x")
    monkeypatch.setattr(vlm_reader, "_post", lambda *a, **k: _payload(
        '{"hole":["As","Ks"],"position":"CADEIRA_5"}'))
    st = vlm_reader.read_table_vlm(Image.new("RGB", (10, 10)))
    assert st.position == ""


def test_erro_de_rede_vira_runtimeerror(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://x")

    def _boom(*a, **k):
        raise urllib.error.URLError("conexão recusada")

    monkeypatch.setattr(vlm_reader, "_post", _boom)
    with pytest.raises(RuntimeError):
        vlm_reader.read_table_vlm(Image.new("RGB", (10, 10)))


def test_json_lixo_vira_valueerror(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://x")
    monkeypatch.setattr(vlm_reader, "_post", lambda *a, **k: _payload("sem json aqui"))
    with pytest.raises(ValueError):
        vlm_reader.read_table_vlm(Image.new("RGB", (10, 10)))


# ---------- caminho HTTP REAL (urllib -> socket -> parse), não mockado ----------

def test_caminho_http_real_contra_stub(monkeypatch):
    """Sobe um servidor-stub que imita o llama-server e roda read_table_vlm pelo caminho
    de REDE real (urllib POST -> socket -> resposta). Valida o contrato request/response
    que os testes com _post mockado NÃO cobrem: prompt + imagem base64 + JSON de volta."""
    seen: dict = {}
    canned = json.dumps({"choices": [{"message": {"content":
        '{"hole":["As","Kd"],"board":["2h","6c","Tc"],"pot":700,"num_players":6,'
        '"position":"BTN","stacks":{"0":1500}}'}}]}).encode()

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencia o log do http.server
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            content = body["messages"][0]["content"]
            seen["text"] = any(c.get("type") == "text" for c in content)
            seen["image"] = any(
                c.get("type") == "image_url" and "base64," in c["image_url"]["url"]
                for c in content)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(canned)))
            self.end_headers()
            self.wfile.write(canned)

    srv = HTTPServer(("127.0.0.1", 0), _Handler)  # porta efêmera
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("POKER_VLM_URL", f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions")
        st = vlm_reader.read_table_vlm(Image.new("RGB", (900, 600)))
    finally:
        srv.shutdown()

    assert seen["text"] and seen["image"]  # o request REAL levou prompt + imagem base64
    assert st.hole == ["As", "Kd"] and st.board == ["2h", "6c", "Tc"]
    assert st.pot == 700 and st.pot_source == "vlm"
    assert st.n_players == 6 and st.position == "BTN" and st.stacks == {0: 1500}


# ---------- wiring no /from-image: o VLM RESGATA o abstain ----------

def test_from_image_vlm_resgata_quando_caminho_rapido_abstem(monkeypatch):
    import poker_arena.vision as vision_pkg

    # caminho rápido ABSTÉM: sem F2, e a F1 devolve um estado sem cartas (sanity reprova)
    monkeypatch.setattr(vision_pkg, "vision_model_available", lambda: False)
    monkeypatch.setattr(vision_pkg, "recognize_table",
                        lambda *a, **k: RecognizedState(hole=[], board=[], pot=None))
    # VLM disponível e lê um estado VÁLIDO (UI inédita lida semanticamente)
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: True)
    monkeypatch.setattr(vision_pkg, "read_table_vlm", lambda *a, **k: RecognizedState(
        hole=["As", "Kd"], board=["2h", "6c", "Tc"], pot=700, n_cards=5,
        confidence=0.9, n_players=6, position="BTN", pot_source="vlm"))

    client = TestClient(create_app())
    r = client.post("/copilot/from-image", files={"image": ("t.png", _img_bytes(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "F3-vlm"
    assert body["sanity"]["ok"] is True
    assert body["detected"]["hole"] == ["As", "Kd"]
    assert body["decision"] is not None  # o copiloto decidiu sobre o estado lido pelo VLM


def test_from_image_sem_vlm_mantem_abstain(monkeypatch):
    import poker_arena.vision as vision_pkg

    monkeypatch.setattr(vision_pkg, "vision_model_available", lambda: False)
    monkeypatch.setattr(vision_pkg, "recognize_table",
                        lambda *a, **k: RecognizedState(hole=[], board=[], pot=None))
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: False)  # sem VLM configurado

    client = TestClient(create_app())
    r = client.post("/copilot/from-image", files={"image": ("t.png", _img_bytes(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] != "F3-vlm"
    assert body["sanity"]["ok"] is False  # abstém, como antes
    assert body["decision"] is None

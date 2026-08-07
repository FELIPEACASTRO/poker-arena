"""Leitor F3-VLM: prova o parsing/normalização/ausência-graciosa e o RESGATE no abstain.

Tudo sem um modelo real — o POST HTTP (`_post`) é mockado. Cobre: sem endpoint -> indispo-
nível; JSON puro / com cercas markdown / com texto ao redor -> RecognizedState; normalização
de cartas (10h->Th, maiúsc/minúsc, inválidas fora); erro de rede -> RuntimeError; e o wiring
do /from-image (VLM resgata um estado que o caminho rápido abandonou -> engine 'F3-vlm').
"""

from __future__ import annotations

import io
import json
import re
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from poker_arena.api.app import create_app
from poker_arena.vision import RecognizedState, check_state, vlm_reader

_API_TOKEN = "a" * 32


def _payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def _img_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (80, 60), (10, 80, 40)).save(buf, format="PNG")
    return buf.getvalue()


def _context(*, consent: bool = True, redactor=None) -> vlm_reader.VlmRequestContext:
    return vlm_reader.VlmRequestContext(
        consent=consent,
        session_id="123e4567-e89b-42d3-a456-426614174000",
        redaction_hook=redactor or (lambda image: image.copy()),
        redaction_policy="unit-test-mask-v1",
    )


def _read_vlm(img: Image.Image, **kwargs):
    return vlm_reader.read_table_vlm(img, context=_context(), **kwargs)


def _mint_remote_consent(client: TestClient) -> str:
    response = client.post(
        "/copilot/remote-vlm/consent-sessions",
        headers={"X-Poker-Token": _API_TOKEN},
        json={"consent": True},
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def test_erro_de_parse_nao_vaza_resposta_remota_em_logs():
    sensitive_provider_output = "hole=AsKs session-private-marker"
    with pytest.raises(ValueError) as caught:
        vlm_reader._extract_json(sensitive_provider_output)

    assert sensitive_provider_output not in str(caught.value)
    assert "AsKs" not in str(caught.value)


def test_extrai_objeto_com_chave_fechando_dentro_de_string_e_texto_ao_redor():
    parsed = vlm_reader._extract_json(
        'prefixo {ignorado; payload={"hole":["As","Kd"],"label":"literal } seguro"} fim'
    )

    assert parsed == {"hole": ["As", "Kd"], "label": "literal } seguro"}


# ---------- disponibilidade ----------


def test_indisponivel_sem_endpoint(monkeypatch):
    monkeypatch.delenv("POKER_VLM_URL", raising=False)
    assert vlm_reader.vlm_available() is False
    with pytest.raises(vlm_reader.VlmUnavailable):
        _read_vlm(Image.new("RGB", (10, 10)))


def test_disponivel_com_endpoint(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://localhost:8080/v1/chat/completions")
    monkeypatch.setenv("POKER_VLM_REDACT_REGIONS", "0,0,0.1,0.1")
    assert vlm_reader.vlm_available() is True


def test_redaction_masks_only_configured_region_and_drops_metadata(monkeypatch):
    monkeypatch.setenv("POKER_VLM_REDACT_REGIONS", "0,0,0.5,0.5")
    image = Image.new("RGB", (10, 10), "white")
    image.info["sensitive-source-metadata"] = "must-not-survive"

    redacted = vlm_reader.redact_configured_regions(image)

    assert redacted.getpixel((1, 1)) == (0, 0, 0)
    assert redacted.getpixel((8, 8)) == (255, 255, 255)
    assert redacted.info == {}


def test_redaction_total_uses_union_not_duplicate_rectangle_sum(monkeypatch):
    monkeypatch.setenv(
        "POKER_VLM_REDACT_REGIONS",
        "0,0,0.05,0.1;0,0,0.05,0.1",
    )

    with pytest.raises(vlm_reader.VlmPrivacyError, match="cobrir area material"):
        vlm_reader.configured_redaction_policy()


@pytest.mark.parametrize(
    "url",
    [
        "http://vlm.example.test/v1/chat/completions",
        "https://random-name.trycloudflare.com/v1/chat/completions",
        "https://user:secret@vlm.example.test/v1/chat/completions",
        "https://vlm.example.test/v1/chat/completions?redirect=1",
    ],
)
def test_endpoint_remoto_inseguro_fica_indisponivel(monkeypatch, url):
    monkeypatch.setenv("POKER_VLM_URL", url)
    monkeypatch.setenv("POKER_VLM_ALLOWED_HOSTS", "vlm.example.test")
    monkeypatch.setenv("POKER_VLM_API_TOKEN", "t" * 32)
    monkeypatch.setenv("POKER_VLM_REDACT_REGIONS", "0,0,0.1,0.1")
    assert vlm_reader.vlm_available() is False


def test_endpoint_remoto_exige_allowlist_token_e_redacao(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "https://vlm.example.test/v1/chat/completions")
    monkeypatch.delenv("POKER_VLM_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("POKER_VLM_API_TOKEN", raising=False)
    monkeypatch.delenv("POKER_VLM_REDACT_REGIONS", raising=False)
    assert vlm_reader.vlm_available() is False

    monkeypatch.setenv("POKER_VLM_ALLOWED_HOSTS", "vlm.example.test")
    monkeypatch.setenv("POKER_VLM_API_TOKEN", "t" * 32)
    monkeypatch.setenv("POKER_VLM_REDACT_REGIONS", "0,0,0.1,0.1")
    monkeypatch.setattr(
        vlm_reader.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    assert vlm_reader.vlm_available() is True


@pytest.mark.parametrize("resolved", ["10.0.0.8", "169.254.169.254", "127.0.0.2"])
def test_endpoint_remoto_rejeita_resolucao_nao_publica(monkeypatch, resolved):
    monkeypatch.setenv("POKER_VLM_URL", "https://vlm.example.test/v1/chat/completions")
    monkeypatch.setenv("POKER_VLM_ALLOWED_HOSTS", "vlm.example.test")
    monkeypatch.setenv("POKER_VLM_API_TOKEN", "t" * 32)
    monkeypatch.setenv("POKER_VLM_REDACT_REGIONS", "0,0,0.1,0.1")
    monkeypatch.setattr(
        vlm_reader.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved, 443))],
    )

    assert vlm_reader.vlm_available() is False


def test_endpoint_remoto_pina_o_ip_publico_aprovado(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "https://vlm.example.test/v1/chat/completions")
    monkeypatch.setenv("POKER_VLM_ALLOWED_HOSTS", "vlm.example.test")
    monkeypatch.setenv("POKER_VLM_API_TOKEN", "t" * 32)
    monkeypatch.setenv("POKER_VLM_REDACT_REGIONS", "0,0,0.1,0.1")
    monkeypatch.setattr(
        vlm_reader.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    config = vlm_reader._endpoint_config()

    assert config.remote is True
    assert config.connect_ip == "93.184.216.34"


def test_post_disables_environment_proxy_for_pixels_and_authorization(monkeypatch):
    captured_handlers = []

    class Headers(dict):
        def get_content_type(self):
            return "application/json"

    class Response:
        headers = Headers({"Content-Length": "12"})

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"ok": true}'

        def close(self):
            return None

    class Opener:
        def open(self, _request, *, timeout):
            assert timeout == 1.0
            return Response()

    def fake_build_opener(*handlers):
        captured_handlers.extend(handlers)
        return Opener()

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)

    payload = vlm_reader._post(
        "https://vlm.example.test/v1/chat/completions",
        {"messages": []},
        1.0,
        token="t" * 32,
        session_digest="d" * 64,
        redaction_policy="unit-test-mask-v1",
    )

    assert payload == {"ok": True}
    proxy_handlers = [
        handler for handler in captured_handlers if isinstance(handler, urllib.request.ProxyHandler)
    ]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}


@pytest.mark.parametrize("failure_stage", ["request", "getresponse"])
def test_post_pinado_fecha_conexao_em_falha_de_transporte(monkeypatch, failure_stage):
    closed: list[bool] = []

    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            if failure_stage == "request":
                raise OSError("falha de envio")

        def getresponse(self):
            raise OSError("falha de resposta")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(vlm_reader, "_PinnedHTTPSConnection", Connection)

    with pytest.raises(OSError):
        vlm_reader._post(
            "https://vlm.example.test/v1/chat/completions",
            {"messages": []},
            1.0,
            token="t" * 32,
            session_digest="d" * 64,
            redaction_policy="unit-test-mask-v1",
            connect_ip="93.184.216.34",
        )

    assert closed == [True]


def test_consentimento_e_redacao_falham_antes_do_post(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    post = monkeypatch.setattr(
        vlm_reader,
        "_post",
        lambda *args, **kwargs: pytest.fail("nenhum byte deveria sair"),
    )
    del post
    image = Image.new("RGB", (20, 20))
    with pytest.raises(vlm_reader.VlmPrivacyError, match="consentimento"):
        vlm_reader.read_table_vlm(image, context=_context(consent=False))

    def broken_redactor(_image):
        raise RuntimeError("falha intencional")

    with pytest.raises(vlm_reader.VlmPrivacyError, match="redaction hook falhou"):
        vlm_reader.read_table_vlm(image, context=_context(redactor=broken_redactor))


def test_timeout_e_tamanho_de_imagem_sao_limitados(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setenv("POKER_VLM_TIMEOUT", "999")
    assert vlm_reader.vlm_available() is False
    with pytest.raises(vlm_reader.VlmConfigurationError, match="TIMEOUT"):
        _read_vlm(Image.new("RGB", (10, 10)))

    monkeypatch.setenv("POKER_VLM_TIMEOUT", "1")
    monkeypatch.setattr(vlm_reader, "_MAX_ENCODED_IMAGE_BYTES", 1)
    with pytest.raises(vlm_reader.VlmPrivacyError, match="limite"):
        _read_vlm(Image.new("RGB", (20, 20), "white"))


# ---------- parsing ----------


def test_le_json_puro(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(
        vlm_reader,
        "_post",
        lambda *a, **k: _payload(
            '{"hole":["As","Kd"],"board":["2h","6c","Tc"],"pot":700,'
            '"num_players":6,"position":"BTN","stacks":{"0":1500,"1":900}}'
        ),
    )
    st = _read_vlm(Image.new("RGB", (300, 200)))
    assert st.hole == ["As", "Kd"]
    assert st.board == ["2h", "6c", "Tc"]
    assert st.pot == 700 and st.pot_source == "vlm"
    assert st.n_players == 6 and st.position == "BTN"
    assert st.stacks == {0: 1500, 1: 900}
    assert st.n_cards == 5


def test_vlm_syntax_does_not_create_fabricated_high_confidence(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(
        vlm_reader, "_post", lambda *a, **k: _payload('{"hole":["As","Kd"],"board":[],"pot":700}')
    )
    st = _read_vlm(Image.new("RGB", (300, 200)))
    assert st.confidence == 0.0
    assert st.card_confidences == [0.0, 0.0]
    assert not check_state(st).ok


def test_le_json_com_cercas_markdown(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(
        vlm_reader,
        "_post",
        lambda *a, **k: _payload('```json\n{"hole":["Qd","Th"],"board":[],"pot":null}\n```'),
    )
    st = _read_vlm(Image.new("RGB", (10, 10)))
    assert st.hole == ["Qd", "Th"] and st.board == [] and st.pot is None


def test_extrai_json_com_texto_ao_redor(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(
        vlm_reader,
        "_post",
        lambda *a, **k: _payload(
            'Claro! Aqui está: {"hole":["Ac","2d"],"board":["3s"]} — espero ajudar.'
        ),
    )
    st = _read_vlm(Image.new("RGB", (10, 10)))
    assert st.hole == ["Ac", "2d"] and st.board == ["3s"]


def test_normaliza_cartas(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    # '10h'->'Th', 'AS'->'As', 'kD'->'Kd'; duplicatas ficam visíveis ao sanity.
    monkeypatch.setattr(
        vlm_reader,
        "_post",
        lambda *a, **k: _payload('{"hole":["10h","AS"],"board":["kD","kD","7c"]}'),
    )
    st = _read_vlm(Image.new("RGB", (10, 10)))
    assert st.hole == ["Th", "As"]
    assert st.board == ["Kd", "Kd", "7c"]  # duplicata é preservada para o sanity rejeitar
    assert not check_state(st).ok


def test_posicao_vlm_usa_somente_taxonomia_canonica(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(
        vlm_reader,
        "_post",
        lambda *a, **k: _payload('{"hole":["As","Kd"],"position":"UTG+1"}'),
    )
    assert _read_vlm(Image.new("RGB", (10, 10))).position == "UTG+1"

    monkeypatch.setattr(
        vlm_reader,
        "_post",
        lambda *a, **k: _payload('{"hole":["As","Kd"],"position":"UTG1"}'),
    )
    with pytest.raises(ValueError, match="position"):
        _read_vlm(Image.new("RGB", (10, 10)))


def test_vlm_rejeita_carta_invalida_em_vez_de_ocultar_saida_malformada(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(
        vlm_reader,
        "_post",
        lambda *a, **k: _payload('{"hole":["As","Zx"],"board":[]}'),
    )
    with pytest.raises(ValueError, match="carta inválida"):
        _read_vlm(Image.new("RGB", (10, 10)))


def test_vlm_does_not_truncate_overfull_hole_into_a_valid_state(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(
        vlm_reader,
        "_post",
        lambda *a, **k: _payload('{"hole":["As","Kd","Qh"],"board":[],"pot":10}'),
    )
    with pytest.raises(ValueError, match="cardinalidade"):
        _read_vlm(Image.new("RGB", (10, 10)))


def test_vlm_rejects_ambiguous_numeric_normalization(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(
        vlm_reader,
        "_post",
        lambda *a, **k: _payload(
            '{"hole":["As","Kd"],"board":[],"pot":10,"num_players":"6.5",'
            '"stacks":{"0":"$10.50","1":"1.5K"}}'
        ),
    )
    with pytest.raises(ValueError, match="num_players"):
        _read_vlm(Image.new("RGB", (10, 10)))


def test_campos_ausentes_viram_vazio(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(vlm_reader, "_post", lambda *a, **k: _payload("{}"))
    st = _read_vlm(Image.new("RGB", (10, 10)))
    assert st.hole == [] and st.board == [] and st.pot is None
    assert st.n_players == 0 and st.position == "" and st.stacks is None


def test_posicao_invalida_e_descartada(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(
        vlm_reader, "_post", lambda *a, **k: _payload('{"hole":["As","Ks"],"position":"CADEIRA_5"}')
    )
    with pytest.raises(ValueError, match="position"):
        _read_vlm(Image.new("RGB", (10, 10)))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"board": ["As", "Kd", "Qh", "Jc", "Ts", "9d"]}, "cardinalidade"),
        ({"num_players": 10}, "num_players"),
        ({"stacks": {str(seat): 100 for seat in range(10)}}, "cardinalidade"),
        ({"stacks": {"9": 100}}, "assento"),
        ({"stacks": {"0": 1_000_000_000}}, "stack"),
        ({"pot": 1_000_000_000.0}, "pot"),
        ({"hole": [], "provider_debug": "unexpected"}, "campos"),
    ],
)
def test_vlm_limita_cardinalidade_assentos_fichas_e_campos(payload, message):
    with pytest.raises(ValueError, match=message):
        vlm_reader._to_state(payload)


def test_erro_de_rede_vira_runtimeerror(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")

    def _boom(*a, **k):
        raise urllib.error.URLError("conexão recusada")

    monkeypatch.setattr(vlm_reader, "_post", _boom)
    with pytest.raises(RuntimeError):
        _read_vlm(Image.new("RGB", (10, 10)))


def test_json_lixo_vira_valueerror(monkeypatch):
    monkeypatch.setenv("POKER_VLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(vlm_reader, "_post", lambda *a, **k: _payload("sem json aqui"))
    with pytest.raises(ValueError):
        _read_vlm(Image.new("RGB", (10, 10)))


# ---------- caminho HTTP REAL (urllib -> socket -> parse), não mockado ----------


def test_caminho_http_real_contra_stub(monkeypatch):
    """Sobe um servidor-stub que imita o llama-server e roda read_table_vlm pelo caminho
    de REDE real (urllib POST -> socket -> resposta). Valida o contrato request/response
    que os testes com _post mockado NÃO cobrem: prompt + imagem base64 + JSON de volta."""
    seen: dict = {}
    canned = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"hole":["As","Kd"],"board":["2h","6c","Tc"],"pot":700,"num_players":6,'
                        '"position":"BTN","stacks":{"0":1500}}'
                    }
                }
            ]
        }
    ).encode()

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencia o log do http.server
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            content = body["messages"][0]["content"]
            seen["text"] = any(c.get("type") == "text" for c in content)
            seen["image"] = any(
                c.get("type") == "image_url" and "base64," in c["image_url"]["url"] for c in content
            )
            seen["authorization"] = self.headers.get("Authorization")
            seen["cache_control"] = self.headers.get("Cache-Control")
            seen["data_handling"] = self.headers.get("X-Poker-Data-Handling")
            seen["consent_digest"] = self.headers.get("X-Poker-Consent-Session-SHA256")
            seen["redaction"] = self.headers.get("X-Poker-Redaction")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(canned)))
            self.end_headers()
            self.wfile.write(canned)

    srv = HTTPServer(("127.0.0.1", 0), _Handler)  # porta efêmera
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv(
            "POKER_VLM_URL", f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions"
        )
        monkeypatch.setenv("POKER_VLM_API_TOKEN", "a" * 32)
        st = _read_vlm(Image.new("RGB", (900, 600)))
    finally:
        srv.shutdown()

    assert seen["text"] and seen["image"]  # o request REAL levou prompt + imagem base64
    assert seen["authorization"] == f"Bearer {'a' * 32}"
    assert seen["cache_control"] == "no-store"
    assert seen["data_handling"] == "transient-no-store"
    assert re.fullmatch(r"[a-f0-9]{64}", seen["consent_digest"])
    assert seen["redaction"] == "unit-test-mask-v1"
    assert st.hole == ["As", "Kd"] and st.board == ["2h", "6c", "Tc"]
    assert st.pot == 700 and st.pot_source == "vlm"
    assert st.n_players == 6 and st.position == "BTN" and st.stacks == {0: 1500}


# ---------- wiring no /from-image: consentimento por request + abstain ----------


def test_from_image_so_chama_vlm_com_consentimento_e_mantem_confianca_zero(monkeypatch):
    import poker_arena.vision as vision_pkg

    monkeypatch.setenv("POKER_ENABLE_REMOTE_VLM", "1")
    monkeypatch.setenv("POKER_API_TOKEN", _API_TOKEN)
    monkeypatch.setenv("POKER_VLM_REDACT_REGIONS", "0,0,0.5,0.5")
    seen: dict = {}
    # caminho rápido ABSTÉM: sem F2, e a F1 devolve um estado sem cartas (sanity reprova)
    monkeypatch.setattr(vision_pkg, "vision_model_available", lambda: False)
    monkeypatch.setattr(
        vision_pkg, "recognize_table", lambda *a, **k: RecognizedState(hole=[], board=[], pot=None)
    )
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: True)

    def fake_remote_reader(_image, *, context, **_kwargs):
        seen["context"] = context
        return RecognizedState(
            hole=["As", "Kd"],
            board=["2h", "6c", "Tc"],
            pot=700,
            n_cards=5,
            confidence=0.0,
            card_confidences=[0.0] * 5,
            pot_confidence=0.0,
            n_players=6,
            position="BTN",
            pot_source="vlm",
        )

    monkeypatch.setattr(vision_pkg, "read_table_vlm", fake_remote_reader)

    client = TestClient(create_app())
    session_id = _mint_remote_consent(client)
    r = client.post(
        "/copilot/from-image",
        headers={"X-Poker-Token": _API_TOKEN},
        files={"image": ("t.png", _img_bytes(), "image/png")},
        data={"remote_vlm_consent": "true", "remote_vlm_session_id": session_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert seen["context"].consent is True
    assert seen["context"].session_id == session_id
    assert callable(seen["context"].redaction_hook)
    assert seen["context"].redaction_policy.startswith("configured-mask-v1-")
    assert body["engine"] == "F3-vlm"
    assert body["detected"]["hole"] == ["As", "Kd"]
    assert body["detected"]["confidence"] == 0.0
    assert body["sanity"]["ok"] is False
    assert body["decision"] is None
    assert "proposta VLM remota não calibrada" in body["sanity"]["problems"]
    assert any("somente para inspeção" in warning for warning in body["sanity"]["warnings"])


def test_from_image_falha_remota_mantem_recomendacao_suprimida(monkeypatch):
    import poker_arena.vision as vision_pkg

    monkeypatch.setenv("POKER_ENABLE_REMOTE_VLM", "1")
    monkeypatch.setenv("POKER_API_TOKEN", _API_TOKEN)
    monkeypatch.setenv("POKER_VLM_REDACT_REGIONS", "0,0,0.5,0.5")
    monkeypatch.setattr(vision_pkg, "vision_model_available", lambda: False)
    monkeypatch.setattr(
        vision_pkg, "recognize_table", lambda *a, **k: RecognizedState(hole=[], board=[], pot=None)
    )
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: True)

    def fail_remote_reader(*_args, **_kwargs):
        raise RuntimeError("falha remota controlada")

    monkeypatch.setattr(vision_pkg, "read_table_vlm", fail_remote_reader)

    client = TestClient(create_app())
    session_id = _mint_remote_consent(client)
    response = client.post(
        "/copilot/from-image",
        headers={"X-Poker-Token": _API_TOKEN},
        files={"image": ("t.png", _img_bytes(), "image/png")},
        data={"remote_vlm_consent": "true", "remote_vlm_session_id": session_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "F1-template"
    assert body["decision"] is None
    assert (
        "fallback VLM falhou; recomendação permaneceu suprimida por segurança"
        in body["sanity"]["warnings"]
    )


def test_from_image_nao_envia_sem_consentimento_da_sessao(monkeypatch):
    import poker_arena.vision as vision_pkg

    monkeypatch.setenv("POKER_ENABLE_REMOTE_VLM", "1")
    monkeypatch.setenv("POKER_API_TOKEN", _API_TOKEN)
    monkeypatch.setattr(vision_pkg, "vision_model_available", lambda: False)
    monkeypatch.setattr(
        vision_pkg, "recognize_table", lambda *a, **k: RecognizedState(hole=[], board=[], pot=None)
    )
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: True)
    monkeypatch.setattr(
        vision_pkg,
        "read_table_vlm",
        lambda *a, **k: pytest.fail("VLM não pode receber imagem sem consentimento"),
    )

    client = TestClient(create_app())
    response = client.post(
        "/copilot/from-image",
        headers={"X-Poker-Token": _API_TOKEN},
        files={"image": ("t.png", _img_bytes(), "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] is None
    assert any("consentimento" in warning for warning in body["sanity"]["warnings"])

    invalid = client.post(
        "/copilot/from-image",
        headers={"X-Poker-Token": _API_TOKEN},
        files={"image": ("t.png", _img_bytes(), "image/png")},
        data={"remote_vlm_consent": "true", "remote_vlm_session_id": "curta"},
    )
    assert invalid.status_code == 422


def test_from_image_forca_abstain_mesmo_se_reader_remoto_reportar_confianca(monkeypatch):
    """Defesa em profundidade: um futuro adapter não pode promover o F3 por engano."""
    import poker_arena.vision as vision_pkg

    monkeypatch.setenv("POKER_ENABLE_REMOTE_VLM", "1")
    monkeypatch.setenv("POKER_API_TOKEN", _API_TOKEN)
    monkeypatch.setenv("POKER_VLM_REDACT_REGIONS", "0,0,0.5,0.5")
    monkeypatch.setattr(vision_pkg, "vision_model_available", lambda: False)
    monkeypatch.setattr(
        vision_pkg, "recognize_table", lambda *a, **k: RecognizedState(hole=[], board=[], pot=None)
    )
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: True)
    monkeypatch.setattr(
        vision_pkg,
        "read_table_vlm",
        lambda *a, **k: RecognizedState(
            hole=["As", "Kd"],
            board=[],
            pot=100,
            n_cards=2,
            confidence=1.0,
            card_confidences=[1.0, 1.0],
            pot_confidence=1.0,
            n_players=2,
            position="BTN",
            pot_source="vlm",
        ),
    )

    client = TestClient(create_app())
    session_id = _mint_remote_consent(client)
    response = client.post(
        "/copilot/from-image",
        headers={"X-Poker-Token": _API_TOKEN},
        files={"image": ("t.png", _img_bytes(), "image/png")},
        data={
            "remote_vlm_consent": "true",
            "remote_vlm_session_id": session_id,
        },
    )
    body = response.json()
    assert body["engine"] == "F3-vlm"
    assert body["sanity"]["ok"] is False
    assert body["decision"] is None
    assert body["detected"]["confidence"] == 0.0
    assert "proposta VLM remota não calibrada" in body["sanity"]["problems"]


def test_consentimento_remoto_revogado_nao_autoriza_novo_quadro(monkeypatch):
    import poker_arena.vision as vision_pkg

    monkeypatch.setenv("POKER_ENABLE_REMOTE_VLM", "1")
    monkeypatch.setenv("POKER_API_TOKEN", _API_TOKEN)
    monkeypatch.setattr(vision_pkg, "vision_model_available", lambda: False)
    monkeypatch.setattr(
        vision_pkg, "recognize_table", lambda *a, **k: RecognizedState(hole=[], board=[], pot=None)
    )
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: True)
    monkeypatch.setattr(
        vision_pkg,
        "read_table_vlm",
        lambda *a, **k: pytest.fail("sessão revogada não pode enviar pixels"),
    )
    client = TestClient(create_app())
    session_id = _mint_remote_consent(client)

    revoked = client.request(
        "DELETE",
        "/copilot/remote-vlm/consent-sessions",
        headers={"X-Poker-Token": _API_TOKEN},
        json={"session_id": session_id},
    )
    assert revoked.status_code == 200
    assert revoked.json() == {"revoked": True}

    response = client.post(
        "/copilot/from-image",
        headers={"X-Poker-Token": _API_TOKEN},
        files={"image": ("t.png", _img_bytes(), "image/png")},
        data={"remote_vlm_consent": "true", "remote_vlm_session_id": session_id},
    )
    assert response.status_code == 200
    assert response.json()["engine"] == "F1-template"
    assert any("revogada" in item for item in response.json()["sanity"]["warnings"])


def test_consentimento_remoto_expira_no_servidor(monkeypatch):
    import poker_arena.api.app as app_module
    import poker_arena.vision as vision_pkg

    clock = {"now": 100.0}
    monkeypatch.setattr(app_module, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    monkeypatch.setenv("POKER_ENABLE_REMOTE_VLM", "1")
    monkeypatch.setenv("POKER_API_TOKEN", _API_TOKEN)
    monkeypatch.setenv("POKER_REMOTE_VLM_CONSENT_TTL_SECONDS", "30")
    monkeypatch.setattr(vision_pkg, "vision_model_available", lambda: False)
    monkeypatch.setattr(
        vision_pkg, "recognize_table", lambda *a, **k: RecognizedState(hole=[], board=[], pot=None)
    )
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: True)
    monkeypatch.setattr(
        vision_pkg,
        "read_table_vlm",
        lambda *a, **k: pytest.fail("sessão expirada não pode enviar pixels"),
    )
    client = TestClient(create_app())
    session_id = _mint_remote_consent(client)
    clock["now"] += 31

    response = client.post(
        "/copilot/from-image",
        headers={"X-Poker-Token": _API_TOKEN},
        files={"image": ("t.png", _img_bytes(), "image/png")},
        data={"remote_vlm_consent": "true", "remote_vlm_session_id": session_id},
    )
    assert response.status_code == 200
    assert response.json()["engine"] == "F1-template"
    assert any("expirada" in item for item in response.json()["sanity"]["warnings"])


def test_vlm_remoto_sem_token_de_entrada_fica_fail_closed(monkeypatch):
    import poker_arena.vision as vision_pkg

    monkeypatch.setenv("POKER_ENABLE_REMOTE_VLM", "1")
    monkeypatch.delenv("POKER_API_TOKEN", raising=False)
    monkeypatch.setattr(vision_pkg, "vision_model_available", lambda: False)
    monkeypatch.setattr(
        vision_pkg, "recognize_table", lambda *a, **k: RecognizedState(hole=[], board=[], pot=None)
    )
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: True)
    monkeypatch.setattr(
        vision_pkg,
        "read_table_vlm",
        lambda *a, **k: pytest.fail("VLM remoto exige POKER_API_TOKEN válido"),
    )
    client = TestClient(create_app())

    assert client.get("/ready").status_code == 503
    mint = client.post("/copilot/remote-vlm/consent-sessions", json={"consent": True})
    assert mint.status_code == 503
    response = client.post(
        "/copilot/from-image",
        files={"image": ("t.png", _img_bytes(), "image/png")},
        data={
            "remote_vlm_consent": "true",
            "remote_vlm_session_id": "123e4567-e89b-42d3-a456-426614174000",
        },
    )
    assert response.status_code == 200
    assert any("POKER_API_TOKEN" in item for item in response.json()["sanity"]["warnings"])


def test_from_image_sem_vlm_mantem_abstain(monkeypatch):
    import poker_arena.vision as vision_pkg

    monkeypatch.setattr(vision_pkg, "vision_model_available", lambda: False)
    monkeypatch.setattr(
        vision_pkg, "recognize_table", lambda *a, **k: RecognizedState(hole=[], board=[], pot=None)
    )
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: False)  # sem VLM configurado

    client = TestClient(create_app())
    r = client.post("/copilot/from-image", files={"image": ("t.png", _img_bytes(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] != "F3-vlm"
    assert body["sanity"]["ok"] is False  # abstém, como antes
    assert body["decision"] is None

"""Leitor F3-VLM: um Vision-Language Model lê QUALQUER tela de poker -> estado.

POR QUE ISTO existe: o F2 (YOLO treinado em sintético) é *keyed a pixels* — decora a
aparência de um estilo e NÃO generaliza pra 100-1000 UIs inéditas (leu 0/2 cartas no
PokerTH real). Um VLM lê carta e dígito SEMANTICAMENTE, então uma UI nunca vista já é
"in-distribution". É a peça que ataca o gap sim->real de forma agnóstica (pesquisa 2026:
Qwen3-VL / VLMs de screen-understanding). Ver [[audit-readiness-verdict]].

COMO se encaixa: mesma SAÍDA da F1/F2 (`RecognizedState`), então o sanity-check, o
endpoint e o copiloto NÃO mudam — só troca QUEM lê. Entra como fallback do abstain: o
caminho rápido (F1/F2/OCR em CPU) decide o comum; quando abstém (UI inédita), o VLM lê.

AUSÊNCIA GRACIOSA (espelha o padrão do F2/OCR): fala com um servidor local OpenAI-
compatível (o `llama-server` do llama.cpp servindo o Qwen3-VL GGUF na GPU) via
`POKER_VLM_URL`. Sem a var setada, `vlm_available()` é False e o pipeline usa F1/F2. Erro
de rede/parse -> exceção -> o chamador cai no abstain do caminho rápido. Nada de dep nova:
usa só `urllib` da stdlib.

Subir o modelo (uma vez, na GPU):
    llama-server -hf unsloth/Qwen3-VL-4B-Instruct-GGUF:Q4_K_M --mmproj <mmproj.gguf> --port 8080
    set POKER_VLM_URL=http://localhost:8080/v1/chat/completions   (Windows: setx)
Latência: com Instruct (não Thinking) + max_tokens travado + imagem <=1280px, alveja ~1-3s
na GPU — MAS meça end-to-end antes de prometer <=4s à banca.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request

from PIL import Image

from .recognize import RecognizedState
from .synth import RANKS, SUITS

_CARD_SET = frozenset(r + s for r in RANKS for s in SUITS)  # 52 nomes válidos (ex.: "As","Td")
_POSITIONS = frozenset({"BTN", "SB", "BB", "UTG", "UTG1", "UTG2", "MP", "MP1", "LJ", "HJ", "CO"})
_MAX_SIDE = 1280  # redimensiona o maior lado: latência + custo de tokens do VLM
_MAX_TOKENS = 256  # trava o output (VLM over-gera se não for contido -> estoura os 4s)


class VlmUnavailable(RuntimeError):
    """POKER_VLM_URL não está configurado — não há VLM pra chamar."""


def vlm_endpoint() -> str | None:
    """Endpoint OpenAI-compatível do VLM local (chat/completions). None se não configurado."""
    url = os.environ.get("POKER_VLM_URL", "").strip()
    return url or None


def vlm_model() -> str:
    return os.environ.get("POKER_VLM_MODEL", "qwen3-vl").strip() or "qwen3-vl"


def vlm_timeout() -> float:
    try:
        return float(os.environ.get("POKER_VLM_TIMEOUT", "20"))
    except ValueError:
        return 20.0


def vlm_available() -> bool:
    """True se há um endpoint configurado (não faz ping — erro real cai no fallback)."""
    return vlm_endpoint() is not None


_SCHEMA_PROMPT = (
    "Você é um leitor de telas de poker Texas Hold'em No-Limit. Analise a imagem de UMA "
    "mesa e devolva SOMENTE um objeto JSON (sem texto, sem markdown, sem explicação) com "
    "este schema exato:\n"
    '{"hole": [cartas do HERÓI, no máx 2, ficam EMBAIXO/na frente do jogador de baixo],'
    ' "board": [cartas comunitárias, no máx 5, ficam no CENTRO],'
    ' "pot": inteiro do POTE total (número central perto do board) ou null,'
    ' "num_players": nº de jogadores sentados na mesa ou null,'
    ' "position": posição do herói entre '
    '["BTN","SB","BB","UTG","MP","HJ","CO"] ou "",'
    ' "stacks": {"<índice do assento>": fichas} ou {}}\n'
    "NOTAÇÃO DE CARTA obrigatória: rank em [2 3 4 5 6 7 8 9 T J Q K A] seguido do naipe em "
    "[s h d c] (s=espadas, h=copas, d=ouros, c=paus). Use T para o 10. Exemplos válidos: "
    '"As", "Td", "6h", "2c". Se um campo não estiver claramente visível, use null, [] ou {}. '
    "NUNCA invente cartas que você não consegue ler com certeza — é melhor omitir."
)


def _encode_image(img: Image.Image) -> str:
    """Redimensiona pro maior lado <= _MAX_SIDE e devolve PNG em base64 (data URI)."""
    im = img.convert("RGB")
    w, h = im.size
    scale = min(1.0, _MAX_SIDE / max(w, h))
    if scale < 1.0:
        im = im.resize((round(w * scale), round(h * scale)), Image.BILINEAR)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _post(url: str, body: dict, timeout: float) -> dict:
    """POST JSON -> JSON (urllib puro). Isolado pra ser trivial de mockar nos testes."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (url é config local)
        return json.loads(resp.read().decode("utf-8"))


def _extract_json(text: str) -> dict:
    """Extrai o objeto JSON da resposta do VLM (tolera cercas ```json e texto ao redor)."""
    t = text.strip()
    if t.startswith("```"):  # remove cercas de markdown
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")  # último recurso: pega do 1º { ao } equilibrado
    if start >= 0:
        depth = 0
        for i in range(start, len(t)):
            depth += t[i] == "{"
            depth -= t[i] == "}"
            if depth == 0:
                return json.loads(t[start : i + 1])
    raise ValueError(f"resposta do VLM não continha JSON válido: {text[:120]!r}")


def _norm_card(raw: object) -> str | None:
    """Normaliza uma carta pro formato do projeto (rank maiúsculo + naipe minúsculo);
    aceita '10h'->'Th', 'AS'->'As'. Devolve None se não for uma das 52 válidas."""
    if not isinstance(raw, str):
        return None
    s = raw.strip().replace("10", "T")
    if len(s) != 2:
        return None
    card = s[0].upper() + s[1].lower()
    return card if card in _CARD_SET else None


def _norm_cards(raw: object, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        c = _norm_card(item)
        if c and c not in out:  # sem duplicata (o sanity pega o resto)
            out.append(c)
    return out[:limit]


def _norm_int(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, float) and raw > 0:
        return int(raw)
    if isinstance(raw, str):
        digits = re.sub(r"[^0-9]", "", raw)
        return int(digits) if digits else None
    return None


def _to_state(data: dict) -> RecognizedState:
    """Mapeia o JSON do VLM pro RecognizedState (mesma saída da F1/F2)."""
    hole = _norm_cards(data.get("hole"), 2)
    board = _norm_cards(data.get("board"), 5)
    pot = _norm_int(data.get("pot"))
    n_players = _norm_int(data.get("num_players")) or 0
    position = str(data.get("position") or "").upper().strip()
    if position not in _POSITIONS:
        position = ""
    stacks: dict[int, int] = {}
    raw_stacks = data.get("stacks")
    if isinstance(raw_stacks, dict):
        for k, v in raw_stacks.items():
            seat, chips = _norm_int(k), _norm_int(v)
            if seat is not None and chips is not None:
                stacks[seat] = chips
    # confiança NOMINAL: o VLM não dá confiança por-carta confiável. O gate real é o
    # sanity-check estrutural (treys: 52 únicas, hero<=2) + o cross-check de números (OCR).
    # 0.9 quando leu o herói (passa no strict SE estruturalmente válido); 0.5 se nem isso.
    confidence = 0.9 if len(hole) == 2 else 0.5
    return RecognizedState(
        hole=hole, board=board, pot=pot, n_cards=len(hole) + len(board),
        confidence=confidence, n_players=n_players, position=position,
        stacks=stacks or None, pot_source="vlm" if pot is not None else "template",
    )


def read_table_vlm(img: Image.Image, timeout: float | None = None) -> RecognizedState:
    """Lê a mesa com o VLM (leitor agnóstico). Requer POKER_VLM_URL apontando pro
    `llama-server` local (ou outro endpoint OpenAI-compatível com visão).

    Levanta `VlmUnavailable` se não configurado; `RuntimeError`/`ValueError` em erro de
    rede/parse — o chamador (`/from-image`) faz try/except e cai no abstain do caminho
    rápido. A saída é um `RecognizedState`, então passa pela MESMA rede de abstenção."""
    url = vlm_endpoint()
    if url is None:
        raise VlmUnavailable("POKER_VLM_URL não configurado — sem VLM pra chamar")
    body = {
        "model": vlm_model(),
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _SCHEMA_PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{_encode_image(img)}"}},
            ],
        }],
        "temperature": 0,
        "max_tokens": _MAX_TOKENS,
        "response_format": {"type": "json_object"},  # força JSON (llama-server suporta)
    }
    try:
        payload = _post(url, body, timeout if timeout is not None else vlm_timeout())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"falha ao chamar o VLM em {url}: {e}") from e
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"resposta do VLM em formato inesperado: {payload!r:.120}") from e
    return _to_state(_extract_json(content))

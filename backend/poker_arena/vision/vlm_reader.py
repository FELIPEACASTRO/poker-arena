"""Fail-closed remote VLM reader for an explicitly authorized screenshot.

The remote lane is experimental.  A syntactically valid answer is not calibrated
evidence, so every field proposed by the VLM keeps confidence ``0.0``.  Sending pixels
also has a stricter trust boundary than the local readers: a request needs an explicit
consent context, a redaction hook, a pinned/configured model endpoint, bounded I/O and,
for non-loopback hosts, verified HTTPS, an exact host allow-list and a Bearer token.

No image, token or raw consent identifier is logged or persisted by this module.  The
outbound request carries ``no-store`` metadata and only a SHA-256 digest of the ephemeral
consent-session identifier.  Remote service retention still depends on the operator's
service configuration; this client cannot turn a third-party retention policy into a
guarantee.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import io
import ipaddress
import json
import math
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, ImageDraw

from .ocr import _parse_amount
from .recognize import RecognizedState
from .synth import RANKS, SUITS

_CARD_SET = frozenset(r + s for r in RANKS for s in SUITS)
_POSITIONS = frozenset({"BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"})
_MAX_SIDE = 1280
_MAX_TOKENS = 256
_MAX_ENCODED_IMAGE_BYTES = 2_500_000
_MAX_REQUEST_BYTES = 3_500_000
_MAX_RESPONSE_BYTES = 256_000
_DEFAULT_TIMEOUT_SECONDS = 20.0
_MIN_TIMEOUT_SECONDS = 0.5
_MAX_TIMEOUT_SECONDS = 30.0
_DEFAULT_MODEL = "qwen3-vl-4b-instruct-q4-k-m-00c00da"
_MAX_SEATS = 9
_MAX_CHIPS = 999_999_999
_ALLOWED_RESPONSE_FIELDS = frozenset(
    {"hole", "board", "pot", "num_players", "position", "stacks"}
)
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_POLICY_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9._@:/+-]{1,160}$")
_BLOCKED_REMOTE_SUFFIXES = (".trycloudflare.com",)

RedactionHook = Callable[[Image.Image], Image.Image]


class VlmUnavailable(RuntimeError):
    """The remote VLM trust boundary is not fully configured."""


class VlmConfigurationError(VlmUnavailable):
    """An endpoint, credential or resource limit is unsafe or invalid."""


class VlmPrivacyError(VlmUnavailable):
    """Consent or redaction did not satisfy the outbound-image contract."""


@dataclass(frozen=True)
class VlmRequestContext:
    """Per-request authorization; callers must create a fresh session for each capture run."""

    consent: bool
    session_id: str
    redaction_hook: RedactionHook
    redaction_policy: str = "configured-mask-v1"


@dataclass(frozen=True)
class _EndpointConfig:
    url: str
    remote: bool
    connect_ip: str | None
    token: str | None
    timeout: float
    model: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never replay a screenshot or Authorization header to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the DNS-approved IP while checking TLS against the configured host."""

    def __init__(self, host: str, port: int, connect_ip: str, timeout: float) -> None:
        self._ssl_context = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self._ssl_context)
        self._connect_ip = connect_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection((self._connect_ip, self.port), self.timeout)
        try:
            self.sock = self._ssl_context.wrap_socket(raw_socket, server_hostname=self.host)
        except BaseException:
            raw_socket.close()
            raise


def _is_loopback(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _allowed_remote_hosts() -> frozenset[str]:
    raw = os.environ.get("POKER_VLM_ALLOWED_HOSTS", "")
    hosts = frozenset(item.strip().lower().rstrip(".") for item in raw.split(",") if item.strip())
    if any("*" in host or "/" in host or ":" in host for host in hosts):
        raise VlmConfigurationError("POKER_VLM_ALLOWED_HOSTS deve conter hosts exatos")
    return hosts


def _validated_endpoint() -> tuple[str, bool, str | None]:
    raw = os.environ.get("POKER_VLM_URL", "").strip()
    if not raw:
        raise VlmConfigurationError("POKER_VLM_URL nao configurado")
    try:
        parts = urllib.parse.urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise VlmConfigurationError("POKER_VLM_URL invalido") from exc
    if parts.username or parts.password or parts.query or parts.fragment:
        raise VlmConfigurationError("POKER_VLM_URL nao pode conter credencial, query ou fragmento")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or parts.path.rstrip("/") != "/v1/chat/completions":
        raise VlmConfigurationError("POKER_VLM_URL deve terminar em /v1/chat/completions")
    if any(host == suffix[1:] or host.endswith(suffix) for suffix in _BLOCKED_REMOTE_SUFFIXES):
        raise VlmConfigurationError("quick tunnels anonimos nao sao permitidos")
    local = _is_loopback(host)
    if local:
        if parts.scheme not in {"http", "https"}:
            raise VlmConfigurationError("endpoint loopback deve usar HTTP ou HTTPS")
    else:
        if parts.scheme != "https":
            raise VlmConfigurationError("endpoint VLM remoto exige HTTPS com verificacao TLS")
        if host not in _allowed_remote_hosts():
            raise VlmConfigurationError("host VLM remoto nao consta em POKER_VLM_ALLOWED_HOSTS")
    if port is not None and not 1 <= port <= 65535:
        raise VlmConfigurationError("porta do endpoint VLM invalida")
    connect_ip = None
    if not local:
        effective_port = port or 443
        try:
            addresses = {ipaddress.ip_address(host)}
        except ValueError:
            try:
                infos = socket.getaddrinfo(host, effective_port, type=socket.SOCK_STREAM)
            except OSError as exc:
                raise VlmConfigurationError("host VLM remoto nao resolveu") from exc
            addresses = {
                ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) for info in infos
            }
        if not addresses or any(not address.is_global for address in addresses):
            raise VlmConfigurationError("host VLM remoto resolveu fora da Internet publica")
        connect_ip = sorted(str(address) for address in addresses)[0]
    return raw, not local, connect_ip


def _validated_token(*, required: bool) -> str | None:
    token = os.environ.get("POKER_VLM_API_TOKEN", "")
    if not token:
        if required:
            raise VlmConfigurationError("endpoint VLM remoto exige POKER_VLM_API_TOKEN")
        return None
    if not 32 <= len(token) <= 512 or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise VlmConfigurationError("POKER_VLM_API_TOKEN tem formato invalido")
    return token


def vlm_timeout() -> float:
    raw = os.environ.get("POKER_VLM_TIMEOUT", str(_DEFAULT_TIMEOUT_SECONDS))
    try:
        value = float(raw)
    except ValueError as exc:
        raise VlmConfigurationError("POKER_VLM_TIMEOUT deve ser numerico") from exc
    if not math.isfinite(value) or not _MIN_TIMEOUT_SECONDS <= value <= _MAX_TIMEOUT_SECONDS:
        raise VlmConfigurationError(
            f"POKER_VLM_TIMEOUT deve ficar entre {_MIN_TIMEOUT_SECONDS:g} e "
            f"{_MAX_TIMEOUT_SECONDS:g} segundos"
        )
    return value


def vlm_model() -> str:
    value = os.environ.get("POKER_VLM_MODEL", _DEFAULT_MODEL).strip()
    if not _MODEL_RE.fullmatch(value):
        raise VlmConfigurationError("POKER_VLM_MODEL tem formato invalido")
    return value


def _endpoint_config() -> _EndpointConfig:
    url, remote, connect_ip = _validated_endpoint()
    return _EndpointConfig(
        url=url,
        remote=remote,
        connect_ip=connect_ip,
        token=_validated_token(required=remote),
        timeout=vlm_timeout(),
        model=vlm_model(),
    )


def vlm_endpoint() -> str | None:
    """Return a safe configured endpoint, or ``None`` if the lane must remain disabled."""

    try:
        return _endpoint_config().url
    except VlmConfigurationError:
        return None


def _configured_redaction_regions() -> tuple[tuple[float, float, float, float], ...]:
    raw = os.environ.get("POKER_VLM_REDACT_REGIONS", "").strip()
    if not raw:
        raise VlmPrivacyError("POKER_VLM_REDACT_REGIONS nao configurado; imagem nao enviada")
    chunks = [chunk.strip() for chunk in raw.split(";") if chunk.strip()]
    if not 1 <= len(chunks) <= 32:
        raise VlmPrivacyError("configure entre 1 e 32 regioes de redacao")
    regions: list[tuple[float, float, float, float]] = []
    for chunk in chunks:
        try:
            x0, y0, x1, y1 = (float(item.strip()) for item in chunk.split(","))
        except (TypeError, ValueError) as exc:
            raise VlmPrivacyError("regiao de redacao deve usar x0,y0,x1,y1 normalizados") from exc
        values = (x0, y0, x1, y1)
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
            raise VlmPrivacyError("coordenadas de redacao devem ficar entre 0 e 1")
        if x0 >= x1 or y0 >= y1:
            raise VlmPrivacyError("regiao de redacao deve ter area positiva")
        regions.append(values)
    return tuple(regions)


def redact_configured_regions(img: Image.Image) -> Image.Image:
    """Mask operator-configured normalized rectangles and drop all source metadata."""

    regions = _configured_redaction_regions()
    source = img.convert("RGB")
    clean = Image.new("RGB", source.size)
    clean.paste(source)
    draw = ImageDraw.Draw(clean)
    width, height = clean.size
    for x0, y0, x1, y1 in regions:
        left = max(0, min(width - 1, int(x0 * width)))
        top = max(0, min(height - 1, int(y0 * height)))
        right = max(left, min(width - 1, math.ceil(x1 * width) - 1))
        bottom = max(top, min(height - 1, math.ceil(y1 * height) - 1))
        draw.rectangle((left, top, right, bottom), fill=(0, 0, 0))
    return clean


def vlm_available() -> bool:
    """True only when endpoint, token, limits and configured redaction all validate."""

    try:
        _endpoint_config()
        _configured_redaction_regions()
    except VlmUnavailable:
        return False
    return True


_SCHEMA_PROMPT = (
    "Voce e um leitor de telas de poker Texas Hold'em No-Limit. Analise a imagem de UMA "
    "mesa e devolva SOMENTE um objeto JSON (sem texto, markdown ou explicacao) com "
    "este schema exato:\n"
    '{"hole": [cartas do HEROI, no maximo 2], "board": [cartas comunitarias, no maximo 5],'
    ' "pot": inteiro do pote total ou null, "num_players": numero de jogadores ou null,'
    ' "position": uma de ["BTN","SB","BB","UTG","UTG+1","MP","LJ","HJ","CO"] ou "",'
    ' "stacks": {"<indice do assento>": fichas} ou {}}\n'
    "Notacao: rank em [2 3 4 5 6 7 8 9 T J Q K A] seguido do naipe em [s h d c]. "
    'Exemplos: "As", "Td", "6h", "2c". Se nao estiver claramente visivel, use null, [] '
    "ou {}. Nunca invente campos ilegíveis."
)


def _sanitize_redacted_image(img: object) -> Image.Image:
    if not isinstance(img, Image.Image) or img.width <= 0 or img.height <= 0:
        raise VlmPrivacyError("redaction hook nao devolveu uma imagem valida")
    rgb = img.convert("RGB")
    # Reconstruct from pixels so EXIF, ICC profiles and arbitrary PIL metadata cannot leave.
    return Image.frombytes("RGB", rgb.size, rgb.tobytes())


def _encode_image(img: Image.Image) -> str:
    im = img
    width, height = im.size
    scale = min(1.0, _MAX_SIDE / max(width, height))
    if scale < 1.0:
        im = im.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.BILINEAR,
        )
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85, optimize=True)
    encoded = buf.getvalue()
    if len(encoded) > _MAX_ENCODED_IMAGE_BYTES:
        raise VlmPrivacyError("imagem redigida excede o limite para envio remoto")
    return base64.b64encode(encoded).decode("ascii")


def _post(
    url: str,
    body: dict,
    timeout: float,
    *,
    token: str | None,
    session_digest: str,
    redaction_policy: str,
    connect_ip: str | None = None,
) -> dict:
    data = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(data) > _MAX_REQUEST_BYTES:
        raise VlmPrivacyError("request VLM excede o limite de tamanho")
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-store",
        "Content-Type": "application/json",
        "Pragma": "no-cache",
        "User-Agent": "poker-arena-vlm/1",
        "X-Poker-Consent-Session-SHA256": session_digest,
        "X-Poker-Data-Handling": "transient-no-store",
        "X-Poker-Redaction": redaction_policy,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    connection: _PinnedHTTPSConnection | None = None
    response: http.client.HTTPResponse | None = None
    try:
        if connect_ip is not None:
            parts = urllib.parse.urlsplit(url)
            if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
                raise VlmConfigurationError("endpoint remoto pinado invalido")
            connection = _PinnedHTTPSConnection(
                parts.hostname, parts.port or 443, connect_ip, timeout
            )
            connection.request("POST", parts.path, body=data, headers=headers)
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                raise VlmConfigurationError("redirect VLM remoto recusado")
            if response.status >= 400:
                raise urllib.error.HTTPError(
                    url, response.status, response.reason, response.headers, None
                )
        else:
            req = urllib.request.Request(  # noqa: S310 - loopback URL validated above
                url, data=data, headers=headers, method="POST"
            )
            # Local poker pixels must never inherit HTTP(S)_PROXY from the shell.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            response = opener.open(req, timeout=timeout)  # noqa: S310 - validated loopback URL
        content_type = response.headers.get_content_type()
        if content_type != "application/json":
            raise ValueError("resposta VLM nao declarou application/json")
        declared = response.headers.get("Content-Length")
        if declared:
            try:
                declared_bytes = int(declared)
            except ValueError as exc:
                raise ValueError("Content-Length invalido na resposta VLM") from exc
            if declared_bytes < 0 or declared_bytes > _MAX_RESPONSE_BYTES:
                raise ValueError("resposta VLM excede o limite de tamanho")
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ValueError("resposta VLM excede o limite de tamanho")
    finally:
        if response is not None:
            response.close()
        if connection is not None:
            connection.close()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("resposta VLM deve ser um objeto JSON")
    return payload


def _extract_json(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE).strip()
    decoder = json.JSONDecoder()
    try:
        parsed = decoder.decode(value)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    # ``raw_decode`` understands braces and escapes inside JSON strings. A manual
    # brace counter does not, and used to reject otherwise valid provider replies.
    # Try each object boundary because prose before the payload may itself contain ``{``.
    for match in re.finditer(r"\{", value):
        try:
            parsed, _end = decoder.raw_decode(value, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    # Do not echo provider output into exceptions: the API logs failures and the
    # response can contain table-derived data that must not become persistent logs.
    raise ValueError("resposta VLM nao continha objeto JSON valido")


def _norm_card(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip().replace("10", "T")
    if len(value) != 2:
        return None
    card = value[0].upper() + value[1].lower()
    return card if card in _CARD_SET else None


def _norm_cards(raw: object, limit: int, *, field: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"campo {field} da resposta VLM deve ser uma lista")
    if len(raw) > limit:
        raise ValueError(f"campo {field} da resposta VLM excede a cardinalidade permitida")
    cards: list[str] = []
    for item in raw:
        card = _norm_card(item)
        if card is None:
            raise ValueError(f"campo {field} da resposta VLM contém carta inválida")
        cards.append(card)
    return cards


def _norm_int(raw: object, *, allow_zero: bool = False) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 or (allow_zero and raw == 0) else None
    if isinstance(raw, float) and raw.is_integer() and (raw > 0 or (allow_zero and raw == 0)):
        return int(raw)
    if isinstance(raw, str) and re.fullmatch(r"\d+", raw.strip()):
        value = int(raw)
        return value if value > 0 or (allow_zero and value == 0) else None
    return None


def _to_state(data: dict) -> RecognizedState:
    unknown = set(data) - _ALLOWED_RESPONSE_FIELDS
    if unknown:
        raise ValueError("resposta VLM contém campos não permitidos")

    hole = _norm_cards(data.get("hole"), 2, field="hole")
    board = _norm_cards(data.get("board"), 5, field="board")

    raw_pot = data.get("pot")
    pot = _parse_amount(raw_pot)
    if raw_pot is not None and pot is None:
        raise ValueError("campo pot da resposta VLM é inválido ou excede o limite")
    if pot is not None and not 0 <= pot <= _MAX_CHIPS:
        raise ValueError("campo pot da resposta VLM excede o limite")

    raw_players = data.get("num_players")
    if raw_players is None:
        n_players = 0
    else:
        normalized_players = _norm_int(raw_players)
        if normalized_players is None or not 2 <= normalized_players <= _MAX_SEATS:
            raise ValueError("campo num_players da resposta VLM deve ficar entre 2 e 9")
        n_players = normalized_players

    raw_position = data.get("position")
    if raw_position is None or raw_position == "":
        position = ""
    elif not isinstance(raw_position, str):
        raise ValueError("campo position da resposta VLM deve ser texto")
    else:
        position = raw_position.upper().strip()
        if position not in _POSITIONS:
            raise ValueError("campo position da resposta VLM é inválido")

    stacks: dict[int, int] = {}
    raw_stacks = data.get("stacks")
    if raw_stacks is not None:
        if not isinstance(raw_stacks, dict):
            raise ValueError("campo stacks da resposta VLM deve ser um objeto")
        if len(raw_stacks) > _MAX_SEATS:
            raise ValueError("campo stacks da resposta VLM excede a cardinalidade permitida")
        for key, value in raw_stacks.items():
            seat, chips = _norm_int(key, allow_zero=True), _parse_amount(value)
            if seat is None or not 0 <= seat < _MAX_SEATS:
                raise ValueError("assento da resposta VLM está fora do limite")
            if seat in stacks:
                raise ValueError("resposta VLM contém assentos duplicados")
            if chips is None or not 0 <= chips <= _MAX_CHIPS:
                raise ValueError("stack da resposta VLM é inválido ou excede o limite")
            stacks[seat] = chips
    # Valid syntax does not calibrate pixel recognition.  This must stay zero.
    confidence = 0.0
    return RecognizedState(
        hole=hole,
        board=board,
        pot=pot,
        n_cards=len(hole) + len(board),
        confidence=confidence,
        card_confidences=[0.0] * (len(hole) + len(board)),
        pot_confidence=0.0 if pot is not None else None,
        n_players=n_players,
        position=position,
        stacks=stacks or None,
        pot_source="vlm",
    )


def _validate_context(context: VlmRequestContext) -> str:
    if context.consent is not True:
        raise VlmPrivacyError("consentimento remoto explicito ausente")
    if not _SESSION_RE.fullmatch(context.session_id):
        raise VlmPrivacyError("identificador da sessao de consentimento invalido")
    if not callable(context.redaction_hook):
        raise VlmPrivacyError("redaction hook ausente")
    if not _POLICY_RE.fullmatch(context.redaction_policy):
        raise VlmPrivacyError("identificador da politica de redacao invalido")
    return hashlib.sha256(context.session_id.encode("utf-8")).hexdigest()


def read_table_vlm(
    img: Image.Image,
    *,
    context: VlmRequestContext,
    timeout: float | None = None,
) -> RecognizedState:
    """Return an uncalibrated VLM proposal after all privacy/security gates pass."""

    session_digest = _validate_context(context)
    config = _endpoint_config()
    effective_timeout = config.timeout if timeout is None else float(timeout)
    if (
        not math.isfinite(effective_timeout)
        or not _MIN_TIMEOUT_SECONDS <= effective_timeout <= _MAX_TIMEOUT_SECONDS
    ):
        raise VlmConfigurationError("timeout da chamada VLM fora do limite")
    try:
        redacted = context.redaction_hook(img)
    except VlmUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - privacy hook is an explicit trust boundary
        raise VlmPrivacyError("redaction hook falhou; imagem nao enviada") from exc
    clean = _sanitize_redacted_image(redacted)
    body = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _SCHEMA_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(clean)}"},
                    },
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": _MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    try:
        payload = _post(
            config.url,
            body,
            effective_timeout,
            token=config.token,
            session_digest=session_digest,
            redaction_policy=context.redaction_policy,
            connect_ip=config.connect_ip,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"falha ao chamar o VLM em {config.url}: {exc}") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("resposta VLM em formato inesperado") from exc
    if not isinstance(content, str):
        raise RuntimeError("conteudo da resposta VLM nao e texto")
    return _to_state(_extract_json(content))

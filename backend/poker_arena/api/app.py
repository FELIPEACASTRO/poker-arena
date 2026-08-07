"""FastAPI app — rotas REST sobre a aplicação.

CQRS na prática: POST cria/altera (comandos), GET lê (query). Erros do domínio/
aplicação são traduzidos em códigos HTTP no único ponto que conhece HTTP.
Dependência injetada via `Annotated[...]` (idioma moderno do FastAPI).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import math
import os
import re
import secrets
import stat
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlsplit

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

from ..application import (
    ExpertUnavailable,
    GameSession,
    InvalidActionError,
    SessionNotFound,
    SessionRepository,
    UnknownBotLevel,
    available_levels,
    build_session,
)
from ..application.game_session import (
    CommandResult,
    IdempotencyConflictError,
    SessionIntegrityError,
    VersionConflictError,
)
from ..engine.game import IllegalActionError
from .dependencies import get_repository
from .mappers import to_config, to_response
from .openapi_contract import enrich_contract
from .schemas import (
    MAX_CHIPS,
    REMOTE_VLM_SESSION_PATTERN,
    ActionRequest,
    AddPlayerRequest,
    CopilotRequest,
    CopilotResponse,
    CreateTableRequest,
    DetectedStateSchema,
    FromImageResponse,
    GameListResponse,
    GameLogPageResponse,
    HandReviewRequest,
    HandReviewResponse,
    RemoteVlmConsentCreateRequest,
    RemoteVlmConsentRevokeRequest,
    RemoteVlmConsentRevokeResponse,
    RemoteVlmConsentSessionResponse,
    SanitySchema,
    TableStateResponse,
)

RepoDep = Annotated[SessionRepository, Depends(get_repository)]

LOGGER = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_MULTIPART_OVERHEAD_BYTES = 256 * 1024
MAX_IMAGE_PIXELS = 16_000_000
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
LOCAL_ORIGIN = re.compile(r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$")
PROXY_USER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._+:-]{0,253}$")
MAX_WEBSOCKET_MESSAGE_BYTES = 4096
MAX_WEBSOCKET_JSON_DEPTH = 32
WEBSOCKET_SEND_TIMEOUT_SECONDS = 1.0
MAX_IDEMPOTENCY_KEYS = 256
MAX_IDEMPOTENCY_TOMBSTONES = 4096
MAX_SESSION_VERSION = (1 << 63) - 1
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DEFAULT_REMOTE_VLM_CONSENT_TTL_SECONDS = 600
MIN_REMOTE_VLM_CONSENT_TTL_SECONDS = 30
MAX_REMOTE_VLM_CONSENT_TTL_SECONDS = 3600
MAX_REMOTE_VLM_CONSENT_SESSIONS = 256
MIN_API_TOKEN_LENGTH = 32
MAX_API_TOKEN_LENGTH = 512


class _RequestBodyTooLarge(Exception):
    pass


class _ImageBodyLimitMiddleware:
    """Count image-request bytes before the multipart parser can spool them."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and str(scope.get("path", "")).endswith("/copilot/from-image")
        ):
            await self.app(scope, receive, send)
            return
        limit = _configured_limit("POKER_MAX_IMAGE_BYTES", MAX_IMAGE_BYTES)
        request_limit = limit + MAX_MULTIPART_OVERHEAD_BYTES
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = request_limit + 1
            if declared < 0 or declared > request_limit:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": "corpo da imagem excede o limite seguro"},
                )
                await response(scope, receive, send)
                return

        consumed = 0

        async def bounded_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > request_limit:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, bounded_receive, send)
        except _RequestBodyTooLarge:
            response = JSONResponse(
                status_code=413,
                content={"detail": "corpo da imagem excede o limite seguro"},
            )
            await response(scope, receive, send)


@dataclass(frozen=True)
class CommandHeaders:
    command_id: str
    expected_version: int | None
    supplied_idempotency_key: bool


@dataclass(eq=False)
class _WebSocketPeer:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_version: int = -1
    failed: bool = False


class _WebSocketHub:
    """Per-table connection registry with serialized, monotonic state delivery."""

    def __init__(self, *, send_timeout: float = WEBSOCKET_SEND_TIMEOUT_SECONDS) -> None:
        if not math.isfinite(send_timeout) or send_timeout <= 0:
            raise ValueError("send_timeout precisa ser finito e positivo")
        self._lock = asyncio.Lock()
        self._peers: dict[str, set[_WebSocketPeer]] = {}
        self._send_timeout = send_timeout

    async def register(self, table_id: str, websocket: WebSocket) -> _WebSocketPeer:
        peer = _WebSocketPeer(websocket)
        async with self._lock:
            self._peers.setdefault(table_id, set()).add(peer)
        return peer

    async def unregister(self, table_id: str, peer: _WebSocketPeer) -> None:
        async with self._lock:
            peers = self._peers.get(table_id)
            if peers is None:
                return
            peers.discard(peer)
            if not peers:
                self._peers.pop(table_id, None)

    async def send(
        self,
        table_id: str,
        peer: _WebSocketPeer,
        payload: dict[str, object],
        *,
        allow_equal_version: bool = False,
    ) -> bool:
        """Send one frame; stale state is dropped so concurrent publishes stay monotonic."""

        async with peer.send_lock:
            sent = not peer.failed
            version = payload.get("version")
            if sent and (
                isinstance(version, int)
                and not isinstance(version, bool)
                and (
                    version < peer.last_version
                    or (version == peer.last_version and not allow_equal_version)
                )
            ):
                return True
            if sent:
                try:
                    await asyncio.wait_for(
                        peer.websocket.send_json(payload), timeout=self._send_timeout
                    )
                except Exception:  # noqa: BLE001 - a dead socket is isolated from other clients
                    peer.failed = True
                    sent = False
                else:
                    if isinstance(version, int) and not isinstance(version, bool):
                        peer.last_version = max(peer.last_version, version)
        if not sent:
            await self.unregister(table_id, peer)
        return sent

    async def broadcast(self, table_id: str, payload: dict[str, object]) -> None:
        async with self._lock:
            peers = tuple(self._peers.get(table_id, ()))
        if peers:
            await asyncio.gather(*(self.send(table_id, peer, payload) for peer in peers))


def _json_depth_within_limit(raw: str, limit: int = MAX_WEBSOCKET_JSON_DEPTH) -> bool:
    """Bound JSON nesting before invoking the recursive stdlib decoder."""

    depth = 0
    in_string = False
    escaped = False
    for char in raw:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                return False
        elif char in "]}":
            depth -= 1
            if depth < 0:
                return True  # malformed structure is handled by json.loads
    return True


def _parse_if_match(raw: str | None) -> int | None:
    if raw is None:
        return None
    value = raw.strip()
    if value.startswith("W/"):
        value = value[2:].strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    max_digits = len(str(MAX_SESSION_VERSION))
    if not value.isascii() or not value.isdigit() or len(value) > max_digits:
        raise HTTPException(400, "If-Match deve conter uma versão inteira não negativa")
    parsed = int(value)
    if parsed > MAX_SESSION_VERSION:
        raise HTTPException(400, "If-Match excede a maior versão aceita")
    return parsed


def _command_headers(
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Chave única para repetir o mesmo comando sem duplicar efeitos. O servidor "
                "mantém 256 respostas e 4096 tombstones por escopo; uma resposta expirada "
                "dentro dessa janela retorna 409 e nunca repete o comando."
            ),
        ),
    ] = None,
    if_match: Annotated[
        str | None,
        Header(
            alias="If-Match",
            description="Versão recebida no estado anterior ou no cabeçalho ETag.",
        ),
    ] = None,
) -> CommandHeaders:
    supplied = idempotency_key is not None
    if supplied and not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key or ""):
        raise HTTPException(400, "Idempotency-Key inválida")
    return CommandHeaders(
        command_id=idempotency_key or f"auto:{secrets.token_hex(16)}",
        expected_version=_parse_if_match(if_match),
        supplied_idempotency_key=supplied,
    )


CommandDep = Annotated[CommandHeaders, Depends(_command_headers)]


def _fingerprint(operation: str, payload: object = None) -> str:
    canonical = json.dumps(
        {"operation": operation, "payload": payload},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _set_version_headers(response: Response, version: int, *, replayed: bool) -> None:
    response.headers["etag"] = f'"{version}"'
    response.headers["x-session-version"] = str(version)
    response.headers["x-idempotent-replay"] = str(replayed).lower()


def _run_command(
    session: GameSession,
    command: CommandHeaders,
    response: Response,
    *,
    fingerprint: str,
    operation: Callable[[], Any],
) -> TableStateResponse:
    try:
        result = session.execute_once(
            command_id=command.command_id,
            fingerprint=fingerprint,
            expected_version=command.expected_version,
            operation=operation,
            store_result=command.supplied_idempotency_key,
        )
    except (VersionConflictError, IdempotencyConflictError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except (InvalidActionError, IllegalActionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except SessionIntegrityError as exc:
        raise HTTPException(503, "sessão bloqueada para preservar a integridade") from exc
    _set_version_headers(response, result.version, replayed=result.replayed)
    return to_response(result.view, version=result.version)


def _get(repo: SessionRepository, table_id: str) -> GameSession:
    try:
        return repo.get(table_id)
    except SessionNotFound as e:
        raise HTTPException(404, f"mesa {table_id} não encontrada") from e


def _state(session: GameSession) -> dict[str, object]:
    snapshot = session.snapshot()
    return to_response(snapshot.view, version=snapshot.version).model_dump()


def _configured_limit(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        LOGGER.warning("Ignoring invalid %s=%r", name, raw)
        return default
    return value if value > 0 else default


def _decode_image(data: bytes) -> PILImage:
    from PIL import Image as PILImage
    from PIL import UnidentifiedImageError

    try:
        with PILImage.open(io.BytesIO(data)) as source:
            width, height = source.size
            if width <= 0 or height <= 0:
                raise ValueError("imagem sem dimensões válidas")
            if width * height > _configured_limit("POKER_MAX_IMAGE_PIXELS", MAX_IMAGE_PIXELS):
                raise OverflowError("imagem excede o limite de pixels")
            source.load()
            return source.convert("RGB")
    except PILImage.DecompressionBombError as exc:
        # Pillow can reject hostile dimensions while parsing the header, before the
        # explicit pixel-count check above is reached.  Normalize that protection to
        # the same bounded-upload contract instead of leaking an internal HTTP 500.
        raise OverflowError("imagem excede o limite seguro de descompressão") from exc
    except UnidentifiedImageError as exc:
        raise ValueError("formato de imagem inválido") from exc


def _review_image(
    img: PILImage,
    *,
    to_call: int | None,
    my_stack: int | None,
    effective_stack: int | None,
    num_opponents: int | None,
    in_position: bool | None,
    position: str | None,
    hero_current_bet: int | None,
    current_bet: int | None,
    min_raise_increment: int | None,
    raise_reopened: bool | None,
    strict: bool,
    remote_vlm_consent: bool,
    remote_vlm_session_id: str | None,
    remote_vlm_session_authorizer: Callable[[str], bool],
) -> FromImageResponse:
    from dataclasses import asdict

    from ..application.copilot import InvalidSpotError, review_spot
    from ..model_artifacts import ModelArtifactUnavailable
    from ..vision import (
        VlmRequestContext,
        check_state,
        configured_redaction_policy,
        read_table_vlm,
        recognize_table,
        recognize_table_onnx,
        redact_configured_regions,
    )

    warnings: list[str] = []
    engine, state = "F1-template", None
    try:
        state = recognize_table_onnx(
            img, ocr_numbers=True, fail_fast_abstain_below=0.85 if strict else None
        )
        engine = "F2-onnx"
    except (FileNotFoundError, ModelArtifactUnavailable):
        pass
    except Exception:  # noqa: BLE001 - controlled fallback with visible warning
        LOGGER.exception("Vision ONNX inference failed; using template fallback")
        warnings.append("modelo ONNX indisponível; foi usado o baseline")
    if state is None:
        state = recognize_table(
            img, ocr_numbers=True, fail_fast_abstain_below=0.85 if strict else None
        )

    threshold = 0.85 if strict else None
    sanity = check_state(state, abstain_below=threshold)
    sanity.warnings.extend(warnings)

    # F1 is a diagnostic baseline calibrated on the synthetic renderer.  Structural
    # sanity and a high similarity score cannot prove that a plausible card was read
    # correctly on an unseen real client.  Only F2 artifacts carrying the external
    # promotion receipt may authorize a strategic decision.
    if engine == "F1-template":
        sanity.ok = False
        baseline_problem = "baseline F1 sem validação externa; proposta não autoriza decisão"
        if baseline_problem not in sanity.problems:
            sanity.problems.append(baseline_problem)

    remote_vlm_enabled = os.environ.get("POKER_ENABLE_REMOTE_VLM", "0") == "1"
    if not sanity.ok and remote_vlm_enabled:
        if _configured_api_token() is None:
            sanity.warnings.append(
                "fallback VLM remoto bloqueado: POKER_API_TOKEN ausente ou inválido"
            )
        elif remote_vlm_consent is not True or not remote_vlm_session_id:
            sanity.warnings.append(
                "fallback VLM remoto bloqueado: consentimento explícito da sessão ausente"
            )
        elif not remote_vlm_session_authorizer(remote_vlm_session_id):
            sanity.warnings.append(
                "fallback VLM remoto bloqueado: sessão expirada, revogada ou inválida"
            )
        elif not _remote_vlm_provider_available():
            sanity.warnings.append(
                "fallback VLM remoto bloqueado: TLS, token, host ou redação não configurados"
            )
        else:
            context = VlmRequestContext(
                consent=True,
                session_id=remote_vlm_session_id,
                redaction_hook=redact_configured_regions,
                redaction_policy=configured_redaction_policy(),
            )
            try:
                vlm_state = read_table_vlm(img, context=context)
                # Provider syntax is never recognition calibration.  Enforce the F3
                # contract here as well as in the reader so an adapter cannot promote it.
                vlm_state.confidence = 0.0
                vlm_state.card_confidences = [0.0] * len(vlm_state.hole + vlm_state.board)
                vlm_state.pot_confidence = 0.0 if vlm_state.pot is not None else None
                vlm_sanity = check_state(vlm_state, abstain_below=threshold)
                # The remote proposal is useful for supervised inspection, but it is never
                # decision-authorizing evidence until an independent calibration receipt
                # exists.  Keep it visible while forcing the gate closed even if a future
                # reader accidentally reports a positive confidence.
                state, sanity, engine = vlm_state, vlm_sanity, "F3-vlm"
                sanity.ok = False
                if "proposta VLM remota não calibrada" not in sanity.problems:
                    sanity.problems.append("proposta VLM remota não calibrada")
                sanity.warnings.append(
                    "quadro remoto redigido; proposta exibida somente para inspeção"
                )
            except Exception:  # noqa: BLE001 - remote fallback must remain fail-closed
                LOGGER.exception("Remote VLM fallback failed without recording image or token")
                sanity.warnings.append("fallback VLM falhou; decisão permaneceu bloqueada")

    if state.pot is None:
        sanity.ok = False
        if "pote não detectado" not in sanity.problems:
            sanity.problems.append("pote não detectado")

    if engine == "F2-onnx" and (
        state.n_players < 2
        or not state.position
        or state.player_count_confidence is None
        or state.position_confidence is None
    ):
        sanity.ok = False
        sanity.problems.append("contexto estratégico F2 sem confiança explícita")
    if engine == "F2-onnx":
        sanity.warnings.append(
            "visão validada pelo gate F2; preço, stack, oponentes ativos e ordem de "
            "ação continuam sendo contexto manual não verificado pela imagem"
        )

    effective_position = state.position or position
    decision = None
    manual_context = (
        to_call,
        my_stack,
        effective_stack,
        num_opponents,
        in_position,
        hero_current_bet,
        current_bet,
        min_raise_increment,
        raise_reopened,
    )
    if engine == "F2-onnx" and any(value is None for value in manual_context):
        sanity.ok = False
        sanity.problems.append("contexto manual de apostas incompleto; decisão bloqueada")
    if (
        sanity.ok
        and state.pot is not None
        and to_call is not None
        and my_stack is not None
        and effective_stack is not None
        and num_opponents is not None
        and in_position is not None
        and hero_current_bet is not None
        and current_bet is not None
        and min_raise_increment is not None
        and raise_reopened is not None
    ):
        try:
            view = review_spot(
                state.hole,
                state.board,
                state.pot,
                to_call,
                my_stack,
                num_opponents,
                in_position,
                list(available_levels()),
                position=effective_position,
                table_size=(state.n_players if state.n_players >= 2 else None),
                effective_stack=effective_stack,
                hero_current_bet=hero_current_bet,
                current_bet=current_bet,
                min_raise_increment=min_raise_increment,
                raise_reopened=raise_reopened,
            )
            decision = CopilotResponse(**asdict(view))
        except InvalidSpotError:
            sanity.ok = False
            sanity.problems.append("estado detectado não formou um spot válido")

    return FromImageResponse(
        engine=engine,
        detected=DetectedStateSchema(
            hole=state.hole,
            board=state.board,
            pot=state.pot,
            n_cards=state.n_cards,
            confidence=state.confidence,
            n_players=state.n_players,
            position=state.position,
            player_count_confidence=state.player_count_confidence,
            position_confidence=state.position_confidence,
            stacks=state.stacks or {},
            pot_source=state.pot_source,
        ),
        sanity=SanitySchema(
            ok=sanity.ok,
            problems=sanity.problems,
            warnings=sanity.warnings,
        ),
        decision=decision,
    )


def _public_deployment_enabled() -> bool:
    raw = os.environ.get("POKER_PUBLIC_DEPLOYMENT", "0")
    if raw not in {"0", "1"}:
        raise RuntimeError("POKER_PUBLIC_DEPLOYMENT deve ser 0 ou 1")
    return raw == "1"


def _configured_browser_origins(*, public: bool) -> tuple[str, ...]:
    if not public:
        return ()
    raw = os.environ.get("POKER_ALLOWED_ORIGINS", "")
    origins: list[str] = []
    for item in raw.split(","):
        origin = item.strip()
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or origin.endswith("/")
        ):
            raise RuntimeError(
                "POKER_ALLOWED_ORIGINS deve conter apenas origens HTTPS exatas, sem caminho"
            )
        origins.append(origin)
    if not origins or len(origins) != len(set(origins)):
        raise RuntimeError("POKER_ALLOWED_ORIGINS deve conter origens HTTPS únicas")
    return tuple(origins)


def _origin_allowed(origin: str | None) -> bool:
    public = _public_deployment_enabled()
    if public:
        return origin is not None and origin in _configured_browser_origins(public=True)
    return origin is None or bool(LOCAL_ORIGIN.fullmatch(origin))


def _websocket_origin_allowed(origin: str | None) -> bool:
    return _origin_allowed(origin)


def _proxy_user_valid(candidate: str | None) -> bool:
    return candidate is not None and PROXY_USER_PATTERN.fullmatch(candidate) is not None


def _token_valid(candidate: str | None) -> bool:
    token_source_configured = bool(
        os.environ.get("POKER_API_TOKEN") or os.environ.get("POKER_API_TOKEN_FILE")
    )
    if not token_source_configured:
        return True
    expected = _configured_api_token()
    if expected is None:
        return False
    return candidate is not None and secrets.compare_digest(candidate, expected)


def _token_from_file(path_value: str) -> str | None:
    """Read a bounded regular-file secret without following a replaced final path."""

    path = Path(path_value)
    if not path.is_absolute():
        return None
    try:
        before = path.lstat()
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            not stat.S_ISREG(before.st_mode)
            or bool(getattr(before, "st_file_attributes", 0) & reparse_flag)
            or before.st_nlink != 1
            or (os.name != "nt" and bool(before.st_mode & stat.S_IWOTH))
        ):
            return None
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or not stat.S_ISREG(
                after.st_mode
            ):
                return None
            raw = os.read(fd, MAX_API_TOKEN_LENGTH + 3)
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return None
    if len(raw) > MAX_API_TOKEN_LENGTH + 2:
        return None
    raw = raw.removesuffix(b"\r\n").removesuffix(b"\n")
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return None


def _configured_api_token() -> str | None:
    """Return the inbound API token only when its single source meets the contract."""

    direct = os.environ.get("POKER_API_TOKEN", "")
    file_path = os.environ.get("POKER_API_TOKEN_FILE", "")
    if direct and file_path:
        return None
    token = _token_from_file(file_path) if file_path else direct
    if token is None:
        return None
    if not MIN_API_TOKEN_LENGTH <= len(token) <= MAX_API_TOKEN_LENGTH:
        return None
    if any(ord(char) < 33 or ord(char) > 126 for char in token):
        return None
    return token


def _validate_public_deployment(allowed_hosts: list[str]) -> tuple[str, ...]:
    """Validate the proxy-only profile at startup; partial security is never accepted."""

    if not _public_deployment_enabled():
        return ()
    origins = _configured_browser_origins(public=True)
    if os.environ.get("POKER_API_TOKEN"):
        raise RuntimeError("deploy público exige POKER_API_TOKEN_FILE, não segredo em ambiente")
    secret_file = os.environ.get("POKER_API_TOKEN_FILE", "")
    if not secret_file or _configured_api_token() is None:
        raise RuntimeError("deploy público exige POKER_API_TOKEN_FILE absoluto e válido")
    if not allowed_hosts or any(
        host == "*"
        or ".." in host
        or re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host) is None
        for host in allowed_hosts
    ):
        raise RuntimeError("deploy público exige POKER_ALLOWED_HOSTS explícito, sem wildcard")
    if os.environ.get("POKER_ROOT_PATH") != "/api":
        raise RuntimeError("deploy público exige POKER_ROOT_PATH=/api")
    origin_hosts = {urlsplit(origin).hostname for origin in origins}
    if origin_hosts != set(allowed_hosts):
        raise RuntimeError("hosts de POKER_ALLOWED_ORIGINS e POKER_ALLOWED_HOSTS devem coincidir")
    return origins


def _remote_api_token_valid(candidate: str | None) -> bool:
    expected = _configured_api_token()
    return (
        expected is not None
        and candidate is not None
        and secrets.compare_digest(candidate, expected)
    )


def _remote_vlm_provider_available() -> bool:
    from ..vision import vlm_available

    try:
        return vlm_available()
    except Exception:  # noqa: BLE001 - readiness and privacy gates stay fail-closed
        LOGGER.exception("Remote VLM configuration check failed")
        return False


def _remote_vlm_consent_ttl() -> int:
    raw = os.environ.get(
        "POKER_REMOTE_VLM_CONSENT_TTL_SECONDS",
        str(DEFAULT_REMOTE_VLM_CONSENT_TTL_SECONDS),
    )
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("POKER_REMOTE_VLM_CONSENT_TTL_SECONDS deve ser inteiro") from exc
    if not MIN_REMOTE_VLM_CONSENT_TTL_SECONDS <= value <= MAX_REMOTE_VLM_CONSENT_TTL_SECONDS:
        raise ValueError("POKER_REMOTE_VLM_CONSENT_TTL_SECONDS fora do intervalo permitido")
    return value


@dataclass(frozen=True)
class _RemoteVlmConsentRecord:
    expires_at: float
    token_digest: str


class _RemoteVlmConsentRegistry:
    """Bounded in-memory consent capabilities; raw nonces and API tokens are not stored."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: OrderedDict[str, _RemoteVlmConsentRecord] = OrderedDict()

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _purge_expired(self, now: float) -> None:
        for digest, record in list(self._records.items()):
            if record.expires_at <= now:
                self._records.pop(digest, None)

    def issue(self, candidate_token: str | None) -> tuple[str, int]:
        if not _remote_api_token_valid(candidate_token):
            raise PermissionError("token de API remoto ausente ou inválido")
        ttl = _remote_vlm_consent_ttl()
        token_digest = self._digest(candidate_token or "")
        now = time.monotonic()
        with self._lock:
            self._purge_expired(now)
            while len(self._records) >= MAX_REMOTE_VLM_CONSENT_SESSIONS:
                self._records.popitem(last=False)
            while True:
                nonce = secrets.token_urlsafe(32)
                nonce_digest = self._digest(nonce)
                if nonce_digest not in self._records:
                    break
            self._records[nonce_digest] = _RemoteVlmConsentRecord(
                expires_at=now + ttl,
                token_digest=token_digest,
            )
        return nonce, ttl

    def is_active(self, session_id: str) -> bool:
        if not re.fullmatch(REMOTE_VLM_SESSION_PATTERN, session_id):
            return False
        current_token = _configured_api_token()
        if current_token is None:
            return False
        now = time.monotonic()
        digest = self._digest(session_id)
        with self._lock:
            self._purge_expired(now)
            record = self._records.get(digest)
            if record is None:
                return False
            return secrets.compare_digest(record.token_digest, self._digest(current_token))

    def revoke(self, session_id: str) -> bool:
        digest = self._digest(session_id)
        with self._lock:
            self._purge_expired(time.monotonic())
            return self._records.pop(digest, None) is not None


API_DESCRIPTION = """
API do **Poker Arena** — um **Texas Hold'em No-Limit de 2 a 9 jogadores** em que um humano joga
contra bots de IA de níveis configuráveis, ou assiste os bots se enfrentarem no
**Modo Laboratório** (comparando os paradigmas de IA ao vivo, com as cartas abertas).

### Como funciona
1. **Crie uma mesa** com `POST /tables` (escolha os bots, blinds, formato e modo).
   A resposta traz o `table_id` — use-o em todas as próximas chamadas.
2. **Acompanhe o estado** pela `TableStateResponse`. O campo `phase` diz o que fazer:
   - `human_turn` → é a sua vez: envie uma jogada em `POST /tables/{id}/actions`
     (as jogadas válidas vêm em `legal.actions`).
   - `bot_turn` → vez de um bot. No modo `watch`, avance com `POST /tables/{id}/step`.
   - `hand_over` → a mão acabou: comece a próxima com `POST /tables/{id}/next-hand`.
   - `game_over` → a partida terminou (torneio/limite de mãos).
3. **Gerencie a mesa ao vivo**: sente novos bots (`POST .../players`) ou remova
   jogadores (`DELETE .../players/{seat}`) entre as mãos.
4. **Revise depois**: toda partida é gravada — liste em `GET /games` e veja o replay
   mão a mão em `GET /games/{id}`.

### Caixa de vidro (glass-box AI)
Cada bot expõe o **raciocínio real** da última jogada no campo `seats[].insight`
(ex.: *"Equity 37% (200 simulações)"*). No seu turno, o campo `analysis` traz uma
análise completa da sua mão (equity, outs, pot odds, EV simplificado de checkdown e o que cada IA faria).

### Níveis de IA
`random` (Iniciante), `heuristic` (Amador), `montecarlo` (Intermediário),
`adaptive` (Adaptativo) e `expert` (Expert — IA treinada, aparece em `GET /levels`
só quando o modelo está disponível).
"""

TAGS_METADATA = [
    {"name": "Mesa", "description": "Criar uma partida e ler o estado da mesa."},
    {"name": "Jogada", "description": "Avançar o jogo: sua jogada, jogada dos bots e próxima mão."},
    {
        "name": "Jogadores",
        "description": "Entrar/sair de jogadores na mesa ao vivo (como num cassino).",
    },
    {
        "name": "Copiloto",
        "description": "Revisar um spot pós-jogo (equity, MDF, veredito das jogadas, conselho das IAs) — offline.",
    },
    {"name": "Catálogo", "description": "Dados de apoio (níveis de IA disponíveis)."},
    {"name": "Auditoria", "description": "Histórico das partidas gravadas e replay mão a mão."},
    {"name": "Tempo real", "description": "Canal WebSocket para jogar com push de estado."},
    {"name": "Sistema", "description": "Saúde do serviço."},
]


def _warmup_vision() -> None:
    """Carrega os modelos de visão (ONNX) + OCR (RapidOCR) rodando UMA inferência dummy.

    O custo dominante da PRIMEIRA leitura é CARREGAR os modelos (sessão ONNX + engine
    RapidOCR) — cold-start medido em ~4-6s (varia com o tamanho da imagem). Pagando esse
    custo no boot, POUCOS SEGUNDOS depois de subir o servidor o /copilot/from-image já fica
    no regime quente (~1.5-2.4s), dentro do orçamento de 4s da banca. Os singletons têm lock
    (ocr._engine / onnx_recognize._cached_recognizer): uma requisição que chegue DURANTE o
    warmup espera a MESMA carga (paga uma vez), nunca um cold-start duplicado — mas quem
    chegar antes do warmup terminar ainda espera a carga. Best-effort: falha aqui não derruba
    o servidor (roda em thread daemon, tudo sob try/except)."""
    try:
        import numpy as np
        from PIL import Image as PILImage

        from ..model_artifacts import ModelArtifactUnavailable
        from ..vision import recognize_table, recognize_table_onnx

        dummy = PILImage.fromarray(np.full((400, 640, 3), 60, np.uint8))  # cinza: força o load
        try:
            recognize_table_onnx(dummy, ocr_numbers=True)
        except (FileNotFoundError, ModelArtifactUnavailable):
            recognize_table(dummy, ocr_numbers=True)
        except Exception:
            recognize_table(dummy, ocr_numbers=True)
    except Exception:  # noqa: BLE001 — aquecimento é opcional, nunca fatal
        LOGGER.exception("Optional vision warmup failed; cold-start remains enabled")


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Aquece a visão num thread daemon ao subir (não bloqueia o boot; some com o processo).
    Desligável com POKER_WARMUP=0 (ex.: testes que não tocam na visão)."""
    if os.environ.get("POKER_WARMUP", "1") != "0":
        threading.Thread(target=_warmup_vision, name="vision-warmup", daemon=True).start()
    yield


def create_app() -> FastAPI:
    create_lock = threading.RLock()
    create_commands: OrderedDict[str, tuple[str, CommandResult]] = OrderedDict()
    create_tombstones: OrderedDict[str, str] = OrderedDict()
    remote_vlm_consents = _RemoteVlmConsentRegistry()
    websocket_hub = _WebSocketHub()
    root_path = os.environ.get("POKER_ROOT_PATH", "")
    public_deployment = _public_deployment_enabled()
    app = FastAPI(
        title="Poker Arena API",
        version="0.2.0",
        summary="Texas Hold'em No-Limit de 2 a 9 jogadores contra IAs configuráveis.",
        description=API_DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        contact={"name": "Poker Arena", "url": "http://localhost:5173"},
        license_info={"name": "Licença do projeto não declarada — consulte os model cards"},
        servers=(
            [{"url": "/api", "description": "Gateway público autenticado"}]
            if public_deployment
            else [{"url": "http://127.0.0.1:8000", "description": "Servidor local"}]
        ),
        root_path=root_path,
        lifespan=_lifespan,
    )
    allowed_hosts = [
        item.strip()
        for item in os.environ.get("POKER_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(
            ","
        )
        if item.strip()
    ]
    public_origins = _validate_public_deployment(allowed_hosts)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.add_middleware(_ImageBodyLimitMiddleware)

    async def run_and_publish(
        table_id: str,
        session: GameSession,
        command: CommandHeaders,
        response: Response,
        *,
        fingerprint: str,
        operation: Callable[[], Any],
    ) -> TableStateResponse:
        result = await run_in_threadpool(
            partial(
                _run_command,
                session,
                command,
                response,
                fingerprint=fingerprint,
                operation=operation,
            )
        )
        if response.headers.get("x-idempotent-replay") != "true":
            await websocket_hub.broadcast(table_id, result.model_dump(mode="json"))
        return result

    @app.middleware("http")
    async def security_boundary(request: Request, call_next: RequestResponseEndpoint) -> Response:
        public_paths = {"/", "/health", "/ready", "/docs", "/redoc", "/openapi.json"}
        authorization = request.headers.get("authorization", "")
        bearer = authorization[7:] if authorization.lower().startswith("bearer ") else None
        candidate = request.headers.get("x-poker-token") or bearer
        request.state.api_token = candidate
        response: Response
        method = request.method.upper()
        unsafe_method = method in {"POST", "PUT", "PATCH", "DELETE"}
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
        cors_preflight = (
            method == "OPTIONS"
            and origin is not None
            and bool(request.headers.get("access-control-request-method"))
        )
        if cors_preflight and not _origin_allowed(origin):
            response = JSONResponse(
                status_code=403,
                content={"detail": "origem de preflight nao autorizada"},
            )
        elif cors_preflight and fetch_site == "cross-site":
            response = JSONResponse(
                status_code=403,
                content={"detail": "preflight cross-site de navegador bloqueado"},
            )
        elif unsafe_method and origin is not None and not _origin_allowed(origin):
            response = JSONResponse(
                status_code=403,
                content={"detail": "origem de navegador não autorizada"},
            )
        elif unsafe_method and fetch_site == "cross-site":
            response = JSONResponse(
                status_code=403,
                content={"detail": "requisição cross-site de navegador bloqueada"},
            )
        elif (
            not cors_preflight
            and request.url.path not in public_paths
            and (
                not _token_valid(candidate)
                or (
                    _public_deployment_enabled()
                    and not _proxy_user_valid(request.headers.get("x-authenticated-user"))
                )
            )
        ):
            response = JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "autenticação ausente ou inválida"
                        if _public_deployment_enabled()
                        else "token de API ausente ou inválido"
                    )
                },
            )
        else:
            response = await call_next(request)
        return response

    # Starlette wraps middleware in reverse registration order. CORS stays outside
    # authentication so local browsers can read structured 401/403 responses and
    # complete preflights; TrustedHost remains inside the auth boundary.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(public_origins),
        allow_origin_regex=(
            None if public_origins else r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
        ),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def response_security_headers(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Apply security and correlation headers to every HTTP response."""

        response = await call_next(request)
        request_id = request.headers.get("x-request-id")
        if not request_id or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id):
            request_id = secrets.token_hex(16)
        response.headers.setdefault("x-request-id", request_id)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault("referrer-policy", "no-referrer")
        response.headers.setdefault(
            "content-security-policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:",
        )
        response.headers.setdefault("cache-control", "no-store")
        return response

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """Raiz amiga: manda pra documentação interativa (evita o 404 feio de quem
        abre a URL base do backend por engano). Não é um endpoint da API."""
        return RedirectResponse(url="/docs")

    @app.get("/health", tags=["Sistema"], summary="Saúde do serviço")
    def health() -> dict[str, str]:
        """Retorna `{"status": "ok"}` se a API está no ar. Útil para o launcher/monitor."""
        return {"status": "ok"}

    @app.get(
        "/ready",
        tags=["Sistema"],
        summary="Prontidão e dependências opcionais",
        responses={
            503: {"description": "Autenticação ou VLM remoto configurado de forma inválida."}
        },
    )
    def readiness(response: Response, repo: RepoDep) -> dict[str, object]:
        from ..application.match_log import MatchLogCorruptionError, audit_log_health
        from ..vision import vision_model_available

        remote_vlm_enabled = os.environ.get("POKER_ENABLE_REMOTE_VLM", "0") == "1"
        token_source_configured = bool(
            os.environ.get("POKER_API_TOKEN") or os.environ.get("POKER_API_TOKEN_FILE")
        )
        api_token_configuration_ready = (
            not token_source_configured or _configured_api_token() is not None
        )
        remote_api_token_ready = _configured_api_token() is not None
        try:
            _remote_vlm_consent_ttl()
            remote_consent_ttl_ready = True
        except ValueError:
            remote_consent_ttl_ready = False
        remote_provider_ready = _remote_vlm_provider_available() if remote_vlm_enabled else False
        remote_vlm_ready = not remote_vlm_enabled or (
            remote_provider_ready and remote_api_token_ready and remote_consent_ttl_ready
        )
        try:
            audit_health = audit_log_health()
            audit_logs_ready = audit_health["unreadable_logs"] == 0
        except MatchLogCorruptionError:
            audit_health = {"readable_logs": 0, "unreadable_logs": 1}
            audit_logs_ready = False

        checks = {
            "repository": type(repo).__name__,
            "audit_logs": "complete" if audit_logs_ready else "incomplete-or-unreadable",
            "vision_model": "available" if vision_model_available() else "optional-missing",
            "expert_model": "available" if "expert" in available_levels() else "optional-missing",
            "remote_vlm": (
                "configured"
                if remote_vlm_enabled and remote_vlm_ready
                else "misconfigured"
                if remote_vlm_enabled
                else "disabled"
            ),
            "remote_vlm_api_token": (
                "configured"
                if remote_vlm_enabled and remote_api_token_ready
                else "missing-or-invalid"
                if remote_vlm_enabled
                else "not-required"
            ),
            "remote_vlm_consent_ttl": (
                "configured"
                if remote_vlm_enabled and remote_consent_ttl_ready
                else "invalid"
                if remote_vlm_enabled
                else "not-required"
            ),
            "api_auth_token": (
                "configured"
                if token_source_configured and api_token_configuration_ready
                else "invalid"
                if token_source_configured
                else "disabled"
            ),
        }
        service_ready = remote_vlm_ready and api_token_configuration_ready and audit_logs_ready
        if not service_ready:
            response.status_code = 503
        return {"status": "ready" if service_ready else "degraded", "checks": checks}

    @app.post(
        "/copilot",
        response_model=CopilotResponse,
        tags=["Copiloto"],
        summary="Copiloto: revisar um spot (pós-jogo, offline)",
        responses={
            400: {
                "description": "Spot inválido (cartas repetidas, quantidade errada, valores inválidos)."
            }
        },
    )
    def copilot(req: CopilotRequest) -> CopilotResponse:
        """Analisa um SPOT que você descreve (suas cartas, board, pote, preço, posição)
        e devolve a leitura completa: equity modelada, pot odds, EV simplificado de checkdown,
        MDF, outs, a nut,
        textura, blockers, o veredito de CADA jogada (boa/arriscada/ruim + por quê) e o
        conselho dos níveis de IA disponíveis. Este endpoint usa somente algoritmos
        locais e não acessa sites de poker. É destinado a estudo e revisão pós-jogo."""
        from ..application.copilot import InvalidSpotError, review_spot

        try:
            view = review_spot(
                req.hole,
                req.board,
                req.pot,
                req.to_call,
                req.my_stack,
                req.num_opponents,
                req.in_position,
                list(available_levels()),
                position=req.position,
                table_size=req.table_size,
                big_blind=req.big_blind,
                effective_stack=req.effective_stack,
                hero_current_bet=req.hero_current_bet,
                current_bet=req.current_bet,
                min_raise_increment=req.min_raise_increment,
                raise_reopened=req.raise_reopened,
            )
        except InvalidSpotError as e:
            raise HTTPException(400, str(e)) from e
        from dataclasses import asdict

        return CopilotResponse(**asdict(view))

    @app.post(
        "/copilot/remote-vlm/consent-sessions",
        response_model=RemoteVlmConsentSessionResponse,
        status_code=201,
        tags=["Copiloto"],
        summary="Criar autorização efêmera para o fallback VLM remoto",
        responses={
            401: {"description": "Token de API ausente ou inválido."},
            503: {"description": "Fallback remoto incompleto ou desabilitado."},
        },
    )
    def create_remote_vlm_consent_session(
        req: RemoteVlmConsentCreateRequest,
        request: Request,
    ) -> RemoteVlmConsentSessionResponse:
        """Issue a bounded, process-local nonce after explicit consent and authentication."""

        del req  # Literal[True] validation is the consent gate.
        if os.environ.get("POKER_ENABLE_REMOTE_VLM", "0") != "1":
            raise HTTPException(503, "fallback VLM remoto está desabilitado")
        if _configured_api_token() is None:
            raise HTTPException(503, "POKER_API_TOKEN remoto ausente ou inválido")
        if not _remote_vlm_provider_available():
            raise HTTPException(503, "configuração do VLM remoto está incompleta")
        try:
            session_id, ttl = remote_vlm_consents.issue(request.state.api_token)
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
        return RemoteVlmConsentSessionResponse(
            session_id=session_id,
            expires_in_seconds=ttl,
        )

    @app.delete(
        "/copilot/remote-vlm/consent-sessions",
        response_model=RemoteVlmConsentRevokeResponse,
        tags=["Copiloto"],
        summary="Revogar autorização efêmera do fallback VLM remoto",
        responses={
            401: {"description": "Token de API ausente ou inválido."},
            503: {"description": "Token remoto ausente ou inválido."},
        },
    )
    def revoke_remote_vlm_consent_session(
        req: RemoteVlmConsentRevokeRequest,
        request: Request,
    ) -> RemoteVlmConsentRevokeResponse:
        """Revoke by request body so the capability never appears in logs as a URL."""

        if not _remote_api_token_valid(request.state.api_token):
            if _configured_api_token() is None:
                raise HTTPException(503, "POKER_API_TOKEN remoto ausente ou inválido")
            raise HTTPException(401, "token de API ausente ou inválido")
        return RemoteVlmConsentRevokeResponse(revoked=remote_vlm_consents.revoke(req.session_id))

    @app.post(
        "/copilot/from-image",
        response_model=FromImageResponse,
        tags=["Copiloto"],
        summary="Copiloto: ler uma imagem; decidir somente com F2 validado",
        responses={400: {"description": "Imagem inválida."}},
    )
    async def from_image(
        image: Annotated[UploadFile, File(description="Screenshot 2D da mesa de poker.")],
        to_call: Annotated[int | None, Form(ge=0, le=MAX_CHIPS)] = None,
        my_stack: Annotated[int | None, Form(gt=0, le=MAX_CHIPS)] = None,
        effective_stack: Annotated[int | None, Form(ge=0, le=MAX_CHIPS)] = None,
        num_opponents: Annotated[int | None, Form(ge=1, le=8)] = None,
        in_position: Annotated[bool | None, Form()] = None,
        position: Annotated[str | None, Form()] = None,
        hero_current_bet: Annotated[int | None, Form(ge=0, le=MAX_CHIPS)] = None,
        current_bet: Annotated[int | None, Form(ge=0, le=MAX_CHIPS)] = None,
        min_raise_increment: Annotated[int | None, Form(gt=0, le=MAX_CHIPS)] = None,
        raise_reopened: Annotated[bool | None, Form()] = None,
        strict: Annotated[
            bool,
            Form(
                description=(
                    "Obrigatoriamente true. O modo permissivo foi removido porque permitia "
                    "contornar o limiar de confiança da visão."
                )
            ),
        ] = True,
        remote_vlm_consent: Annotated[
            bool,
            Form(
                description=(
                    "Opt-in explícito desta requisição para o fallback VLM remoto. "
                    "Só é considerado junto com remote_vlm_session_id."
                )
            ),
        ] = False,
        remote_vlm_session_id: Annotated[
            str | None,
            Form(
                min_length=20,
                max_length=128,
                pattern=REMOTE_VLM_SESSION_PATTERN,
                description=(
                    "Identificador efêmero da sessão de captura autorizada; não é persistido "
                    "nem enviado em claro ao VLM."
                ),
            ),
        ] = None,
    ) -> FromImageResponse:
        """VISÃO → estado → sanity → Copiloto. A imagem é lida (cartas + pote + stacks)
        pela visão e passa pelo sanity-check de regras. A decisão só é autorizada quando
        o engine é F2 e seu artefato carrega validação externa promovida; F1 e VLM são
        diagnósticos e sempre abstêm. Leituras implausíveis também abstêm. `strict=true`
        é obrigatório e exige o limiar de confiança, além das validações estruturais;
        isso reduz risco, mas não garante exatidão. O
        fallback VLM remoto fica desligado, salvo opt-in do operador e consentimento
        explícito e efêmero em cada requisição da sessão de captura. Antes de sair da
        máquina, a imagem passa pela redação configurada; qualquer falha mantém abstain."""
        if strict is not True:
            raise HTTPException(422, "strict deve permanecer true")
        if image.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(415, "tipo de imagem não permitido")

        limit = _configured_limit("POKER_MAX_IMAGE_BYTES", MAX_IMAGE_BYTES)
        data = await image.read(limit + 1)
        await image.close()
        if len(data) > limit:
            raise HTTPException(413, "imagem excede o limite de upload")
        try:
            img = await run_in_threadpool(_decode_image, data)
        except OverflowError as exc:
            raise HTTPException(413, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(400, f"imagem inválida: {exc}") from exc

        return await run_in_threadpool(
            _review_image,
            img,
            to_call=to_call,
            my_stack=my_stack,
            effective_stack=effective_stack,
            num_opponents=num_opponents,
            in_position=in_position,
            position=position,
            hero_current_bet=hero_current_bet,
            current_bet=current_bet,
            min_raise_increment=min_raise_increment,
            raise_reopened=raise_reopened,
            strict=strict,
            remote_vlm_consent=remote_vlm_consent,
            remote_vlm_session_id=remote_vlm_session_id,
            remote_vlm_session_authorizer=remote_vlm_consents.is_active,
        )

    @app.post(
        "/copilot/review-hand",
        response_model=HandReviewResponse,
        tags=["Copiloto"],
        summary="Copiloto: revisar uma mão do subconjunto PHH-NLHE inteiro",
        responses={
            400: {"description": "Histórico inválido, jogador inexistente ou sem decisões suas."}
        },
    )
    def review_hand_endpoint(req: HandReviewRequest) -> HandReviewResponse:
        """Cole o histórico da mão (subconjunto PHH variant='NT', valores inteiros —
        o texto que o jogo exporta ao FIM da
        mão) e escolha qual jogador é você. O copiloto reproduz a mão e revisa CADA
        decisão sua, comparando com a recomendação. É estudo pós-jogo (como rever um
        PGN de xadrez), executado localmente — não lê tela de jogo ao vivo."""
        from ..application.copilot import InvalidSpotError, review_hand

        try:
            view = review_hand(req.phh, req.player - 1, list(available_levels()))
        except InvalidSpotError as e:
            raise HTTPException(400, str(e)) from e
        from dataclasses import asdict

        return HandReviewResponse(**asdict(view))

    @app.get("/levels", tags=["Catálogo"], summary="Níveis de IA disponíveis")
    def levels() -> dict[str, list[str]]:
        """Lista os níveis de bot que podem ser usados ao criar uma mesa ou adicionar
        um jogador. O `expert` só aparece quando o modelo treinado está instalado."""
        return {"levels": list(available_levels())}

    @app.get(
        "/games",
        response_model=GameListResponse,
        tags=["Auditoria"],
        summary="Listar partidas gravadas",
    )
    def games(
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> GameListResponse:
        """Histórico de todas as partidas (resumo: id, modo, nº de mãos, data).
        Toda partida é gravada automaticamente em disco para auditoria/replay."""
        from ..application.match_log import list_games_page

        return GameListResponse(**list_games_page(offset=offset, limit=limit))

    @app.get(
        "/games/{game_id}",
        response_model=GameLogPageResponse,
        tags=["Auditoria"],
        summary="Replay paginado de uma partida",
        responses={
            404: {"description": "Partida não encontrada."},
            409: {"description": "Trilha de auditoria corrompida ou incompleta."},
        },
    )
    def game(
        game_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> GameLogPageResponse:
        """Devolve uma página do log da partida: cada mão com as ações, o **raciocínio
        de cada bot** no momento (glass-box), o board, os vencedores e o saldo em fichas."""
        from ..application.match_log import MatchLogCorruptionError, read_game_page

        try:
            g = read_game_page(game_id, offset=offset, limit=limit)
        except MatchLogCorruptionError as exc:
            raise HTTPException(409, "trilha de auditoria corrompida") from exc
        if g is None:
            raise HTTPException(404, "jogo não encontrado")
        return GameLogPageResponse(**g)

    @app.post(
        "/tables",
        response_model=TableStateResponse,
        status_code=201,
        tags=["Mesa"],
        summary="Criar uma mesa (nova partida)",
        response_description="Estado inicial da mesa, já com a 1ª mão distribuída.",
        responses={400: {"description": "Nível de bot inválido ou Expert indisponível."}},
    )
    def create_table(
        req: CreateTableRequest,
        response: Response,
        command: CommandDep,
        repo: RepoDep,
    ) -> TableStateResponse:
        """Cria uma partida com os bots, blinds, formato (cash/torneio) e modo (play/watch)
        escolhidos. **Guarde o `table_id` da resposta** — ele identifica a mesa em todas
        as chamadas seguintes."""
        if command.expected_version is not None:
            raise HTTPException(400, "If-Match não se aplica à criação de mesa")
        fingerprint = _fingerprint("POST /tables", req.model_dump(mode="json"))
        with create_lock:
            cached = create_commands.get(command.command_id)
            if cached is not None and command.supplied_idempotency_key:
                cached_fingerprint, cached_result = cached
                if cached_fingerprint != fingerprint:
                    raise HTTPException(
                        409,
                        "Idempotency-Key já foi usada com outro payload",
                    )
                create_commands.move_to_end(command.command_id)
                _set_version_headers(response, cached_result.version, replayed=True)
                return to_response(cached_result.view, version=cached_result.version)
            if command.supplied_idempotency_key:
                expired_fingerprint = create_tombstones.get(command.command_id)
                if expired_fingerprint is not None:
                    create_tombstones.move_to_end(command.command_id)
                    if expired_fingerprint != fingerprint:
                        raise HTTPException(
                            409,
                            "Idempotency-Key já foi usada com outro payload",
                        )
                    raise HTTPException(
                        409,
                        "resultado da Idempotency-Key expirou; a mesa não foi criada novamente",
                    )
            try:
                session = build_session(to_config(req), seed=req.seed)
            except (UnknownBotLevel, ExpertUnavailable) as exc:
                raise HTTPException(400, str(exc)) from exc
            repo.add(session)
            result = session.snapshot()
            if command.supplied_idempotency_key:
                create_commands[command.command_id] = (fingerprint, result)
                while len(create_commands) > MAX_IDEMPOTENCY_KEYS:
                    expired_id, (expired_fingerprint, _) = create_commands.popitem(last=False)
                    create_tombstones[expired_id] = expired_fingerprint
                while len(create_tombstones) > MAX_IDEMPOTENCY_TOMBSTONES:
                    create_tombstones.popitem(last=False)
        _set_version_headers(response, result.version, replayed=False)
        return to_response(result.view, version=result.version)

    @app.get(
        "/tables/{table_id}",
        response_model=TableStateResponse,
        tags=["Mesa"],
        summary="Ler o estado atual da mesa",
        responses={404: {"description": "Mesa não encontrada."}},
    )
    def get_table(table_id: str, response: Response, repo: RepoDep) -> TableStateResponse:
        """Devolve o estado completo e atual da mesa (fase, cartas, pote, cadeiras,
        jogadas válidas, análises). É o jeito de 'dar refresh' sem alterar nada."""
        result = _get(repo, table_id).snapshot()
        _set_version_headers(response, result.version, replayed=False)
        return to_response(result.view, version=result.version)

    @app.post(
        "/tables/{table_id}/actions",
        response_model=TableStateResponse,
        tags=["Jogada"],
        summary="Fazer a sua jogada (turno do humano)",
        responses={
            400: {
                "description": "Jogada ilegal (não está em `legal.actions` ou valor fora do permitido)."
            },
            404: {"description": "Mesa não encontrada."},
        },
    )
    async def act(
        table_id: str,
        action: ActionRequest,
        response: Response,
        command: CommandDep,
        repo: RepoDep,
    ) -> TableStateResponse:
        """Aplica a sua jogada quando `phase == human_turn`. Só valem as ações listadas
        em `legal.actions`; para `raise`, o `amount` é o valor TOTAL (entre `min_raise_to`
        e `max_raise_to`). Os bots jogam sozinhos em seguida, até voltar a ser a sua vez."""
        session = _get(repo, table_id)
        return await run_and_publish(
            table_id,
            session,
            command,
            response,
            fingerprint=_fingerprint(
                f"POST /tables/{table_id}/actions",
                action.model_dump(mode="json"),
            ),
            operation=lambda: session.apply_human_action(action.type, action.amount),
        )

    @app.post(
        "/tables/{table_id}/next-hand",
        response_model=TableStateResponse,
        tags=["Jogada"],
        summary="Começar a próxima mão",
        responses={
            400: {"description": "A mão atual ainda não terminou (`phase` != `hand_over`)."},
            404: {"description": "Mesa não encontrada."},
        },
    )
    async def next_hand(
        table_id: str, response: Response, command: CommandDep, repo: RepoDep
    ) -> TableStateResponse:
        """Distribui uma nova mão. Só é válido quando `phase == hand_over`."""
        session = _get(repo, table_id)
        return await run_and_publish(
            table_id,
            session,
            command,
            response,
            fingerprint=_fingerprint(f"POST /tables/{table_id}/next-hand"),
            operation=session.next_hand,
        )

    @app.post(
        "/tables/{table_id}/step",
        response_model=TableStateResponse,
        tags=["Jogada"],
        summary="Avançar uma jogada de bot (Modo Laboratório)",
        responses={
            400: {"description": "Não há jogada de bot pendente (`phase` != `bot_turn`)."},
            404: {"description": "Mesa não encontrada."},
        },
    )
    async def step(
        table_id: str, response: Response, command: CommandDep, repo: RepoDep
    ) -> TableStateResponse:
        """No modo `watch`, avança UMA jogada de bot por vez — é assim que você acompanha
        a partida lance a lance, vendo o raciocínio de cada IA. Válido só em `bot_turn`."""
        session = _get(repo, table_id)
        return await run_and_publish(
            table_id,
            session,
            command,
            response,
            fingerprint=_fingerprint(f"POST /tables/{table_id}/step"),
            operation=session.step,
        )

    @app.post(
        "/tables/{table_id}/players",
        response_model=TableStateResponse,
        tags=["Jogadores"],
        summary="Sentar um novo bot na mesa",
        responses={
            400: {"description": "Mesa cheia (máx. 9) ou nível inválido."},
            404: {"description": "Mesa não encontrada."},
        },
    )
    async def add_player(
        table_id: str,
        req: AddPlayerRequest,
        response: Response,
        command: CommandDep,
        repo: RepoDep,
    ) -> TableStateResponse:
        """Adiciona um bot do nível escolhido. A mudança vale **a partir da próxima mão**
        (a mão atual termina normalmente). A mesa aceita no máximo 9 assentos."""
        session = _get(repo, table_id)
        return await run_and_publish(
            table_id,
            session,
            command,
            response,
            fingerprint=_fingerprint(
                f"POST /tables/{table_id}/players",
                req.model_dump(mode="json"),
            ),
            operation=lambda: session.add_bot(req.level, name=req.name, buy_in=req.buy_in),
        )

    @app.delete(
        "/tables/{table_id}/players/{seat}",
        response_model=TableStateResponse,
        tags=["Jogadores"],
        summary="Remover um jogador da mesa",
        responses={
            400: {
                "description": "Cadeira inválida, é o humano, ou restariam menos de 2 jogadores."
            },
            404: {"description": "Mesa não encontrada."},
        },
    )
    async def remove_player(
        table_id: str,
        seat: int,
        response: Response,
        command: CommandDep,
        repo: RepoDep,
    ) -> TableStateResponse:
        """Remove o jogador da cadeira indicada (índice em `roster`). Vale a partir da
        próxima mão. Não dá para remover o humano nem deixar a mesa com menos de 2."""
        session = _get(repo, table_id)
        return await run_and_publish(
            table_id,
            session,
            command,
            response,
            fingerprint=_fingerprint(f"DELETE /tables/{table_id}/players/{seat}"),
            operation=lambda: session.remove_player(seat),
        )

    @app.websocket("/tables/{table_id}/ws")
    async def ws(websocket: WebSocket, table_id: str, repo: RepoDep) -> None:
        if not _websocket_origin_allowed(websocket.headers.get("origin")):
            await websocket.close(code=4403)
            return
        token = websocket.headers.get("x-poker-token")
        if not _token_valid(token) or (
            _public_deployment_enabled()
            and not _proxy_user_valid(websocket.headers.get("x-authenticated-user"))
        ):
            await websocket.close(code=4401)
            return
        try:
            session = repo.get(table_id)
        except SessionNotFound:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        peer = await websocket_hub.register(table_id, websocket)
        try:
            initial = await run_in_threadpool(_state, session)
            if not await websocket_hub.send(table_id, peer, initial, allow_equal_version=True):
                return
            while True:
                try:
                    raw = await websocket.receive_text()
                except WebSocketDisconnect:
                    break
                if len(raw.encode("utf-8")) > MAX_WEBSOCKET_MESSAGE_BYTES:
                    if not await websocket_hub.send(
                        table_id, peer, {"error": "mensagem excede o limite"}
                    ):
                        break
                    continue
                if not _json_depth_within_limit(raw):
                    if not await websocket_hub.send(
                        table_id,
                        peer,
                        {
                            "error": "JSON excede a profundidade máxima",
                            "code": "validation_error",
                        },
                    ):
                        break
                    continue
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, RecursionError, ValueError):
                    if not await websocket_hub.send(table_id, peer, {"error": "JSON inválido"}):
                        break
                    continue
                if not isinstance(msg, dict):
                    if not await websocket_hub.send(
                        table_id, peer, {"error": "mensagem deve ser um objeto JSON"}
                    ):
                        break
                    continue
                allowed_fields = {"type", "amount", "command_id", "expected_version"}
                if set(msg) - allowed_fields:
                    if not await websocket_hub.send(
                        table_id,
                        peer,
                        {
                            "error": "campos desconhecidos na mensagem",
                            "code": "validation_error",
                        },
                    ):
                        break
                    continue
                try:
                    action = ActionRequest.model_validate(
                        {"type": msg.get("type"), "amount": msg.get("amount", 0)}
                    )
                except ValidationError as exc:
                    if not await websocket_hub.send(
                        table_id,
                        peer,
                        {"error": str(exc), "code": "validation_error"},
                    ):
                        break
                    continue
                raw_command_id = msg.get("command_id")
                if raw_command_id is None:
                    command_id = f"auto:{secrets.token_hex(16)}"
                elif not isinstance(raw_command_id, str) or not IDEMPOTENCY_KEY_PATTERN.fullmatch(
                    raw_command_id
                ):
                    if not await websocket_hub.send(
                        table_id,
                        peer,
                        {"error": "command_id inválido", "code": "validation_error"},
                    ):
                        break
                    continue
                else:
                    command_id = raw_command_id
                expected_version = msg.get("expected_version")
                if expected_version is not None and (
                    isinstance(expected_version, bool)
                    or not isinstance(expected_version, int)
                    or expected_version < 0
                    or expected_version > MAX_SESSION_VERSION
                ):
                    if not await websocket_hub.send(
                        table_id,
                        peer,
                        {"error": "expected_version inválida", "code": "validation_error"},
                    ):
                        break
                    continue
                try:
                    result = await run_in_threadpool(
                        partial(
                            session.execute_once,
                            command_id=command_id,
                            fingerprint=_fingerprint(
                                f"WS /tables/{table_id}/ws",
                                action.model_dump(mode="json"),
                            ),
                            expected_version=expected_version,
                            operation=partial(
                                session.apply_human_action, action.type, action.amount
                            ),
                            store_result=raw_command_id is not None,
                        )
                    )
                except IdempotencyConflictError as exc:
                    if not await websocket_hub.send(
                        table_id,
                        peer,
                        {"error": str(exc), "code": "idempotency_conflict"},
                    ):
                        break
                    continue
                except VersionConflictError as exc:
                    if not await websocket_hub.send(
                        table_id, peer, {"error": str(exc), "code": "version_conflict"}
                    ):
                        break
                    continue
                except (InvalidActionError, IllegalActionError) as exc:
                    if not await websocket_hub.send(
                        table_id, peer, {"error": str(exc), "code": "invalid_action"}
                    ):
                        break
                    continue
                except SessionIntegrityError:
                    await websocket_hub.send(
                        table_id,
                        peer,
                        {
                            "error": "sessão bloqueada para preservar a integridade",
                            "code": "session_unavailable",
                        },
                    )
                    break
                payload = to_response(result.view, version=result.version).model_dump(mode="json")
                if result.replayed:
                    if not await websocket_hub.send(
                        table_id, peer, payload, allow_equal_version=True
                    ):
                        break
                else:
                    await websocket_hub.broadcast(table_id, payload)
        finally:
            await websocket_hub.unregister(table_id, peer)

    default_openapi = app.openapi

    def canonical_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            contract = enrich_contract(default_openapi())
            if public_deployment:
                contract["servers"] = [
                    {"url": "/api", "description": "Gateway público autenticado"}
                ]
                components = contract.setdefault("components", {})
                security_schemes = components.setdefault("securitySchemes", {})
                security_schemes["EdgeSession"] = {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "__Host-poker_auth",
                    "description": (
                        "Sessão individual OIDC emitida pelo oauth2-proxy no gateway; "
                        "não é criada nem lida diretamente pelo FastAPI."
                    ),
                }
                contract["security"] = [{"EdgeSession": []}]
                for path_item in contract.get("paths", {}).values():
                    if not isinstance(path_item, dict):
                        continue
                    for method, operation in path_item.items():
                        if method.lower() in {
                            "get",
                            "post",
                            "put",
                            "patch",
                            "delete",
                            "options",
                            "head",
                        } and isinstance(operation, dict):
                            operation["security"] = [{"EdgeSession": []}]
                contract["x-public-deployment-trust"] = (
                    "Autenticação individual no gateway; recursos pertencem ao "
                    "workspace compartilhado e não são multi-tenant."
                )
            app.openapi_schema = contract
        return app.openapi_schema

    app.openapi = canonical_openapi  # type: ignore[method-assign]

    return app


app = create_app()

"""Gravação e leitura da trilha de AUDITORIA das partidas.

Guarda TUDO de cada mão em disco (JSONL, 1 mão por linha): quem jogou, a ação, o
RACIOCÍNIO da IA naquele instante (glass-box), as cartas, o board por rua, os
vencedores e o resultado em fichas. Permite auditar/replay qualquer jogo depois.

Por padrão, o logger não apaga histórico. Retenção só ocorre quando o chamador fornece
`retention` explicitamente ou chama `prune_old_games`; ambos validam um limite positivo.

Formato (logs/{session_id}.jsonl):
  linha 1: {"type":"meta", id, created, mode, blinds, seats...}
  linhas N: {"type":"hand", hand, ts, button, seats, actions[], board, pot, winners, result[]}
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import stat
import threading
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

_DEFAULT_EXPLICIT_PRUNE_KEEP = 10
_SAFE_SESSION_ID = re.compile(r"[A-Za-z0-9_-]+")
_MAX_LOG_FILE_BYTES = 64 * 1024 * 1024
_MAX_LOG_LINE_BYTES = 2 * 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_OPEN_BINARY = getattr(os, "O_BINARY", 0)
_OPEN_NOINHERIT = getattr(os, "O_NOINHERIT", 0)
_OPEN_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_LOG_ACTIONS = {"fold", "check", "call", "raise", "all_in"}
_BOARD_SIZE_BY_STREET = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}
_CARD = re.compile(r"[2-9TJQKA][cdhs]")
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchLogCheckpoint:
    """In-memory hand buffer and durable file boundary before a command."""

    file_size: int
    current_hand: dict | None


class MatchLogCorruptionError(ValueError):
    """A persisted audit file violates the bounded JSONL contract."""


def _reject_duplicate_log_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MatchLogCorruptionError("registro de auditoria contém chave JSON duplicada")
        result[key] = value
    return result


def _reject_nonfinite_log_number(value: str) -> None:
    raise MatchLogCorruptionError(f"registro de auditoria contém número não finito: {value}")


def _parse_finite_log_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise MatchLogCorruptionError(f"registro de auditoria contém número não finito: {value}")
    return parsed


def _parse_bounded_log_int(value: str) -> int:
    digits = value.removeprefix("-")
    if len(digits) > 19:
        raise MatchLogCorruptionError("registro de auditoria contém inteiro fora do limite")
    return int(value)


def _validate_log_json_value(value: object) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        if len(str(abs(value))) > 19:
            raise MatchLogCorruptionError("registro de auditoria contém inteiro fora do limite")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MatchLogCorruptionError("registro de auditoria contém número não finito")
        return
    if isinstance(value, list):
        for item in value:
            _validate_log_json_value(item)
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise MatchLogCorruptionError("registro de auditoria contém chave não textual")
        for item in value.values():
            _validate_log_json_value(item)
        return
    raise MatchLogCorruptionError("registro de auditoria contém tipo não serializável")


def _hand_roster(seats: object) -> dict[int, dict]:
    if not isinstance(seats, list):
        raise MatchLogCorruptionError("mão de auditoria não contém uma lista de assentos")
    roster: dict[int, dict] = {}
    player_ids: set[str] = set()
    for raw in seats:
        if not isinstance(raw, dict):
            raise MatchLogCorruptionError("assento de auditoria inválido")
        seat = raw.get("seat")
        player_id = raw.get("player_id")
        if (
            not isinstance(seat, int)
            or isinstance(seat, bool)
            or seat < 0
            or not isinstance(player_id, str)
            or not player_id
        ):
            raise MatchLogCorruptionError("assento de auditoria sem identidade válida")
        if (
            not isinstance(raw.get("name"), str)
            or not isinstance(raw.get("level"), str)
            or type(raw.get("start")) is not int
            or raw["start"] < 0
        ):
            raise MatchLogCorruptionError("assento de auditoria contém dados inválidos")
        if seat in roster or player_id in player_ids:
            raise MatchLogCorruptionError("mão de auditoria repete assento ou identidade")
        roster[seat] = raw
        player_ids.add(player_id)
    return roster


def _validate_roster_reference(item: object, roster: dict[int, dict], *, label: str) -> None:
    if not isinstance(item, dict):
        raise MatchLogCorruptionError(f"{label} de auditoria inválido")
    seat = item.get("seat")
    expected = roster.get(seat) if isinstance(seat, int) and not isinstance(seat, bool) else None
    if (
        expected is None
        or item.get("player_id") != expected.get("player_id")
        or item.get("name") != expected.get("name")
    ):
        raise MatchLogCorruptionError(f"{label} não corresponde ao roster da mão")


def _validate_board(board: object, *, street: str | None = None) -> None:
    if not isinstance(board, list):
        raise MatchLogCorruptionError("board de auditoria deve ser uma lista")
    if any(not isinstance(card, str) or _CARD.fullmatch(card) is None for card in board):
        raise MatchLogCorruptionError("board de auditoria contém carta inválida")
    if len(board) != len(set(board)) or len(board) not in {0, 3, 4, 5}:
        raise MatchLogCorruptionError("board de auditoria tem tamanho/duplicata inválido")
    if street is not None and len(board) != _BOARD_SIZE_BY_STREET.get(street):
        raise MatchLogCorruptionError("street e board de auditoria divergem")


def _is_reparse_or_link(file_stat: os.stat_result) -> bool:
    """Recognize POSIX links and Windows symlink/junction reparse points."""

    return stat.S_ISLNK(file_stat.st_mode) or bool(
        getattr(file_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _absolute_lexical(path: Path) -> Path:
    """Return an absolute path without resolving links or junctions."""

    return Path(os.path.abspath(os.fspath(path)))


def _assert_no_reparse_components(path: Path) -> Path:
    """Fail closed if any existing path component is a link/reparse point."""

    absolute = _absolute_lexical(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            component_stat = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as exc:
            raise MatchLogCorruptionError(
                "componente do caminho de auditoria nao pode ser inspecionado"
            ) from exc
        if _is_reparse_or_link(component_stat):
            raise MatchLogCorruptionError("links e reparse points nao sao permitidos na auditoria")
    return absolute


def _validated_directory(path: Path, *, create: bool) -> Path:
    absolute = _assert_no_reparse_components(path)
    if create:
        try:
            absolute.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise MatchLogCorruptionError("diretorio de auditoria nao pode ser criado") from exc
    absolute = _assert_no_reparse_components(absolute)
    try:
        directory_stat = os.lstat(absolute)
    except OSError as exc:
        raise MatchLogCorruptionError("diretorio de auditoria nao pode ser inspecionado") from exc
    if not stat.S_ISDIR(directory_stat.st_mode) or _is_reparse_or_link(directory_stat):
        raise MatchLogCorruptionError("diretorio de auditoria precisa ser regular")
    return absolute


def _identity(file_stat: os.stat_result) -> tuple[int, int]:
    return file_stat.st_dev, file_stat.st_ino


def _open_verified_regular(
    path: Path,
    flags: int,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> int:
    """Open an existing audit file only after link and identity verification."""

    absolute = _absolute_lexical(path)
    _validated_directory(absolute.parent, create=False)
    try:
        before = os.lstat(absolute)
    except OSError as exc:
        raise MatchLogCorruptionError("arquivo de auditoria nao pode ser inspecionado") from exc
    if not stat.S_ISREG(before.st_mode) or _is_reparse_or_link(before) or before.st_nlink != 1:
        raise MatchLogCorruptionError("arquivo de auditoria precisa ser regular")
    if expected_identity is not None and _identity(before) != expected_identity:
        raise MatchLogCorruptionError("identidade do arquivo de auditoria mudou")

    descriptor: int | None = None
    try:
        descriptor = os.open(
            absolute,
            flags | _OPEN_BINARY | _OPEN_NOINHERIT | _OPEN_NOFOLLOW,
        )
        opened = os.fstat(descriptor)
        after = os.lstat(absolute)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_reparse_or_link(after)
            or opened.st_nlink != 1
            or after.st_nlink != 1
            or not os.path.samestat(before, opened)
            or not os.path.samestat(after, opened)
            or (expected_identity is not None and _identity(opened) != expected_identity)
        ):
            raise MatchLogCorruptionError("identidade do arquivo de auditoria mudou")
        return descriptor
    except MatchLogCorruptionError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise MatchLogCorruptionError("arquivo de auditoria nao pode ser aberto") from exc


def _create_regular_file(path: Path) -> tuple[int, int]:
    """Create a new audit file exclusively and return its immutable identity."""

    absolute = _absolute_lexical(path)
    _validated_directory(absolute.parent, create=True)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            absolute,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_BINARY | _OPEN_NOINHERIT | _OPEN_NOFOLLOW,
            0o600,
        )
        opened = os.fstat(descriptor)
        on_disk = os.lstat(absolute)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_reparse_or_link(on_disk)
            or opened.st_nlink != 1
            or on_disk.st_nlink != 1
            or not os.path.samestat(opened, on_disk)
        ):
            raise MatchLogCorruptionError("arquivo de auditoria criado nao e regular")
        return _identity(opened)
    except FileExistsError:
        raise MatchLogCorruptionError("arquivo de auditoria da sessao ja existe") from None
    except MatchLogCorruptionError:
        raise
    except OSError as exc:
        raise MatchLogCorruptionError("arquivo de auditoria nao pode ser criado") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("escrita de auditoria incompleta")
        view = view[written:]


def _log_dir() -> Path:
    """Diretório dos logs (configurável por env -> testes usam um temp)."""
    env = os.environ.get("POKER_LOG_DIR")
    return Path(env) if env else (Path(__file__).resolve().parents[2] / "logs")


def _validate_retention(keep: int) -> None:
    if type(keep) is not int or not 1 <= keep <= 1_000_000:
        raise ValueError("retention deve ser inteiro entre 1 e 1000000")


def prune_old_games(keep: int = _DEFAULT_EXPLICIT_PRUNE_KEEP, log_dir: Path | None = None) -> int:
    """Apaga os logs de partida mais ANTIGOS, mantendo só os `keep` mais recentes.

    Só mexe nos logs GRAVADOS (o dir configurável); nunca toca nas partidas
    empacotadas com a solução (ex.: as mãos do Pluribus, que ficam em `_bundled_dir`).
    Devolve quantos arquivos foram removidos. A poda é best-effort, mas toda falha de
    I/O é registrada para não produzir uma falsa impressão de retenção aplicada.
    """
    _validate_retention(keep)
    d = log_dir or _log_dir()
    if not d.exists():
        return 0
    try:
        d = _validated_directory(d, create=False)
    except MatchLogCorruptionError as exc:
        LOGGER.warning("diretorio de auditoria recusado para poda: %s", exc)
        return 0
    dated_files: list[tuple[float, Path]] = []
    for path in d.glob("*.jsonl"):
        try:
            descriptor = _open_verified_regular(path, os.O_RDONLY)
            try:
                dated_files.append((os.fstat(descriptor).st_mtime, path))
            finally:
                os.close(descriptor)
        except (OSError, MatchLogCorruptionError) as exc:
            LOGGER.warning("não foi possível inspecionar log para poda: %s (%s)", path, exc)
    files = [path for _, path in sorted(dated_files, reverse=True)]
    removed = 0
    for f in files[keep:]:  # do 11º mais recente em diante
        try:
            f.unlink()
            removed += 1
        except OSError as exc:
            LOGGER.warning("não foi possível remover log antigo: %s (%s)", f, exc)
    return removed


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


class MatchLogger:
    """Acumula a mão atual e grava no disco; poda somente quando explicitamente pedida."""

    def __init__(
        self,
        session_id: str,
        meta: dict,
        log_dir: Path | None = None,
        *,
        retention: int | None = None,
    ) -> None:
        if _SAFE_SESSION_ID.fullmatch(session_id) is None:
            raise ValueError("session_id contém caracteres inválidos")
        if retention is not None:
            _validate_retention(retention)
        reserved_meta = {"type", "id", "created"} & set(meta)
        if reserved_meta:
            raise ValueError(
                f"metadados não podem sobrescrever campos reservados: {sorted(reserved_meta)}"
            )
        _validate_log_json_value(meta)
        self._dir = log_dir or _log_dir()
        self._dir = _validated_directory(self._dir, create=True)
        self.path = self._dir / f"{session_id}.jsonl"
        self._file_identity = _create_regular_file(self.path)
        self._cur: dict | None = None
        self._lock = threading.RLock()
        self._append({"type": "meta", "id": session_id, "created": _now(), **meta})
        if retention is not None:
            prune_old_games(keep=retention, log_dir=self._dir)

    def _append(self, obj: dict) -> None:
        _validate_log_json_value(obj)
        try:
            payload = (json.dumps(obj, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        except ValueError as exc:
            raise MatchLogCorruptionError("registro de auditoria contém número não finito") from exc
        if len(payload) > _MAX_LOG_LINE_BYTES:
            raise MatchLogCorruptionError("registro de auditoria excede o limite")
        with self._lock:
            descriptor = _open_verified_regular(
                self.path,
                os.O_WRONLY | os.O_APPEND,
                expected_identity=self._file_identity,
            )
            try:
                if os.fstat(descriptor).st_size + len(payload) > _MAX_LOG_FILE_BYTES:
                    raise MatchLogCorruptionError(
                        "arquivo de auditoria atingiu a cota antes da escrita"
                    )
                _write_all(descriptor, payload)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def checkpoint(self) -> MatchLogCheckpoint:
        """Capture the exact durable boundary used by a GameSession transaction."""

        with self._lock:
            descriptor = _open_verified_regular(
                self.path,
                os.O_RDONLY,
                expected_identity=self._file_identity,
            )
            try:
                file_size = os.fstat(descriptor).st_size
            finally:
                os.close(descriptor)
            return MatchLogCheckpoint(file_size=file_size, current_hand=deepcopy(self._cur))

    def rollback(self, checkpoint: MatchLogCheckpoint) -> None:
        """Restore the hand buffer and truncate any append from a failed command."""

        with self._lock:
            self._cur = deepcopy(checkpoint.current_hand)
            descriptor = _open_verified_regular(
                self.path,
                os.O_RDWR,
                expected_identity=self._file_identity,
            )
            try:
                if os.fstat(descriptor).st_size != checkpoint.file_size:
                    os.ftruncate(descriptor, checkpoint.file_size)
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def begin_hand(self, hand: int, button: int, seats: list[dict]) -> None:
        if self._cur is not None:
            raise MatchLogCorruptionError(
                "uma nova mão não pode substituir um registro de auditoria ainda aberto"
            )
        _validate_log_json_value(seats)
        roster = _hand_roster(seats)
        if type(hand) is not int or hand <= 0:
            raise MatchLogCorruptionError("número da mão deve ser inteiro positivo")
        if type(button) is not int or button < 0 or (roster and button not in roster):
            raise MatchLogCorruptionError("button não corresponde ao roster da mão")
        self._cur = {
            "type": "hand",
            "hand": hand,
            "ts": _now(),
            "button": button,
            "seats": deepcopy(seats),  # [{seat, player_id, name, level, start}]
            "actions": [],
        }

    def action(
        self,
        seat: int,
        player_id: str,
        name: str,
        level: str,
        action_type: str,
        amount: int,
        street: str,
        board: list[str],
        insight: dict | None,
    ) -> None:
        if self._cur is None:
            raise MatchLogCorruptionError("ação recebida sem uma mão de auditoria aberta")
        roster = _hand_roster(self._cur.get("seats"))
        expected = roster.get(seat) if type(seat) is int else None
        if (
            expected is None
            or expected.get("player_id") != player_id
            or expected.get("name") != name
            or expected.get("level") != level
        ):
            raise MatchLogCorruptionError("ação não corresponde ao roster da mão")
        if action_type not in _LOG_ACTIONS or street not in _BOARD_SIZE_BY_STREET:
            raise MatchLogCorruptionError("ação ou street de auditoria inválida")
        if type(amount) is not int or amount < 0:
            raise MatchLogCorruptionError("valor da ação deve ser inteiro não negativo")
        _validate_board(board, street=street)
        if insight is not None and not isinstance(insight, dict):
            raise MatchLogCorruptionError("insight de auditoria deve ser objeto ou nulo")
        _validate_log_json_value(insight)
        self._cur["actions"].append(
            {
                "seat": seat,
                "player_id": player_id,
                "name": name,
                "level": level,
                "street": street,
                "action": action_type,
                "amount": amount,
                "board": list(board),
                "insight": insight,
            }
        )

    def finish_hand(
        self, board: list[str], pot: int, winners: list[dict], result: list[dict]
    ) -> None:
        if self._cur is None:
            raise MatchLogCorruptionError("finalização recebida sem uma mão de auditoria aberta")
        _validate_board(board)
        if type(pot) is not int or pot < 0:
            raise MatchLogCorruptionError("pote final deve ser inteiro não negativo")
        _validate_log_json_value(winners)
        _validate_log_json_value(result)
        roster = _hand_roster(self._cur.get("seats"))
        for winner in winners:
            _validate_roster_reference(winner, roster, label="vencedor")
        for row in result:
            _validate_roster_reference(row, roster, label="resultado")
        winner_ids = [winner.get("player_id") for winner in winners]
        result_ids = [row.get("player_id") for row in result]
        if len(winner_ids) != len(set(winner_ids)):
            raise MatchLogCorruptionError("finalização repete vencedor")
        if len(result_ids) != len(set(result_ids)) or set(result_ids) != {
            row["player_id"] for row in roster.values()
        }:
            raise MatchLogCorruptionError("resultado não cobre exatamente o roster da mão")
        if any(
            type(row.get("end")) is not int or row["end"] < 0 or type(row.get("delta")) is not int
            for row in result
        ):
            raise MatchLogCorruptionError("stack/delta finais da auditoria são inválidos")
        self._cur.update({"board": list(board), "pot": pot, "winners": winners, "result": result})
        self._append(self._cur)
        self._cur = None


# ---------------- leitura (para a página de auditoria) ----------------
def _bundled_dir() -> Path:
    """Partidas EMPACOTADAS com a solução (ex.: as mãos publicadas do Pluribus,
    uoftcprg/phh-dataset, CC BY 4.0) — aparecem na auditoria como replay."""
    return Path(__file__).resolve().parents[1] / "data"


def _iter_records(path: Path) -> Iterator[dict]:
    """Yield bounded JSON objects; corruption is never silently discarded."""

    try:
        descriptor = _open_verified_regular(path, os.O_RDONLY)
        if os.fstat(descriptor).st_size > _MAX_LOG_FILE_BYTES:
            os.close(descriptor)
            raise MatchLogCorruptionError("arquivo de auditoria excede o limite")
        with os.fdopen(descriptor, "rb") as handle:
            line_number = 0
            while True:
                payload = handle.readline(_MAX_LOG_LINE_BYTES + 1)
                if not payload:
                    break
                line_number += 1
                if len(payload) > _MAX_LOG_LINE_BYTES:
                    raise MatchLogCorruptionError(
                        f"linha {line_number} excede o limite de auditoria"
                    )
                if not payload.strip():
                    raise MatchLogCorruptionError(
                        f"linha {line_number} vazia no arquivo de auditoria"
                    )
                if payload.startswith(b"\xef\xbb\xbf"):
                    raise MatchLogCorruptionError(
                        f"linha {line_number} contém BOM UTF-8 não permitido"
                    )
                try:
                    record = json.loads(
                        payload,
                        object_pairs_hook=_reject_duplicate_log_keys,
                        parse_constant=_reject_nonfinite_log_number,
                        parse_float=_parse_finite_log_float,
                        parse_int=_parse_bounded_log_int,
                    )
                except MatchLogCorruptionError:
                    raise
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OverflowError) as exc:
                    raise MatchLogCorruptionError(
                        f"linha {line_number} não contém JSON UTF-8 válido"
                    ) from exc
                if not isinstance(record, dict):
                    raise MatchLogCorruptionError(f"linha {line_number} precisa ser um objeto JSON")
                if record.get("type") not in {"meta", "hand"}:
                    raise MatchLogCorruptionError(
                        f"linha {line_number} possui tipo de registro inválido"
                    )
                yield record
    except MatchLogCorruptionError:
        raise
    except OSError as exc:
        raise MatchLogCorruptionError("arquivo de auditoria não pôde ser lido") from exc


def _summary_of(path: Path) -> dict | None:
    meta: dict | None = None
    hands = 0
    last: str | None = None
    for record in _iter_records(path):
        if record["type"] == "meta":
            if meta is not None or hands:
                raise MatchLogCorruptionError("metadados duplicados ou fora da primeira linha")
            meta = record
        else:
            if meta is None:
                raise MatchLogCorruptionError("mão encontrada antes dos metadados")
            hands += 1
            last = str(record.get("ts") or last or "")
    if not meta:
        raise MatchLogCorruptionError("arquivo de auditoria não contém metadados")
    game_id = meta.get("id")
    if not isinstance(game_id, str) or _SAFE_SESSION_ID.fullmatch(game_id) is None:
        raise MatchLogCorruptionError("metadados não contêm um id de partida válido")
    if game_id != path.stem:
        raise MatchLogCorruptionError("id dos metadados diverge do nome canônico do arquivo")
    return {
        "id": game_id,
        "created": str(meta.get("created") or ""),
        "mode": str(meta.get("mode") or ""),
        "levels": meta.get("levels") if isinstance(meta.get("levels"), list) else [],
        "hands": hands,
        "last": last or str(meta.get("created") or ""),
    }


@lru_cache(maxsize=2048)
def _summary_cached(
    path_text: str,
    device: int,
    inode: int,
    size: int,
    mtime_ns: int,
    ctime_ns: int,
) -> dict | None:
    del device, inode, size, mtime_ns, ctime_ns  # identity is intentionally part of the key
    return _summary_of(Path(path_text))


def _cached_summary(path: Path) -> dict | None:
    try:
        descriptor = _open_verified_regular(path, os.O_RDONLY)
        try:
            file_stat = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except (OSError, MatchLogCorruptionError) as exc:
        raise MatchLogCorruptionError("metadados do log não puderam ser lidos") from exc
    summary = _summary_cached(
        str(_absolute_lexical(path)),
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )
    return deepcopy(summary)


def _collect_game_summaries(log_dir: Path | None = None) -> tuple[list[dict], int]:
    d = log_dir or _log_dir()
    games: list[dict] = []
    unreadable = 0
    if d.exists():
        d = _validated_directory(d, create=False)
        for path in d.glob("*.jsonl"):
            try:
                summary = _cached_summary(path)
            except MatchLogCorruptionError as exc:
                LOGGER.error("log de auditoria ignorado por corrupção: %s (%s)", path, exc)
                unreadable += 1
                continue
            if summary:
                games.append(summary)
    games.sort(key=lambda game: game["last"], reverse=True)
    bundled = _bundled_dir()
    if bundled.exists():
        bundled = _validated_directory(bundled, create=False)
        for path in sorted(bundled.glob("*.jsonl")):
            try:
                summary = _cached_summary(path)
            except MatchLogCorruptionError as exc:
                LOGGER.error("log empacotado ignorado por corrupção: %s (%s)", path, exc)
                unreadable += 1
                continue
            if summary:
                games.append(summary)
    return games, unreadable


def _all_game_summaries(log_dir: Path | None = None) -> list[dict]:
    return _collect_game_summaries(log_dir)[0]


def audit_log_health(log_dir: Path | None = None) -> dict[str, int]:
    """Return observable completeness state without exposing filesystem paths."""

    games, unreadable = _collect_game_summaries(log_dir)
    return {"readable_logs": len(games), "unreadable_logs": unreadable}


def list_games(log_dir: Path | None = None) -> list[dict]:
    """Resumo de cada partida (gravadas + empacotadas), mais recente primeiro."""
    return _all_game_summaries(log_dir)


def _page(offset: int, limit: int, total: int, returned: int) -> dict:
    if type(offset) is not int or offset < 0:
        raise ValueError("offset deve ser inteiro não negativo")
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("limit deve ser inteiro entre 1 e 200")
    next_offset = offset + returned if offset + returned < total else None
    return {
        "offset": offset,
        "limit": limit,
        "returned": returned,
        "total": total,
        "next_offset": next_offset,
    }


def list_games_page(*, offset: int = 0, limit: int = 50, log_dir: Path | None = None) -> dict:
    _page(offset, limit, 0, 0)  # validate before scanning the filesystem
    games, unreadable = _collect_game_summaries(log_dir)
    selected = games[offset : offset + limit]
    return {
        "games": selected,
        "page": _page(offset, limit, len(games), len(selected)),
        "unreadable_logs": unreadable,
    }


def _game_path(session_id: str, log_dir: Path | None) -> Path | None:
    if _SAFE_SESSION_ID.fullmatch(session_id) is None:
        return None
    path = (log_dir or _log_dir()) / f"{session_id}.jsonl"
    if path.exists() or path.is_symlink():
        descriptor = _open_verified_regular(path, os.O_RDONLY)
        os.close(descriptor)
        return _absolute_lexical(path)
    bundled = _bundled_dir() / f"{session_id}.jsonl"
    if not bundled.exists() and not bundled.is_symlink():
        return None
    descriptor = _open_verified_regular(bundled, os.O_RDONLY)
    os.close(descriptor)
    return _absolute_lexical(bundled)


def _read_game_records(path: Path, *, offset: int, limit: int | None) -> dict | None:
    meta: dict | None = None
    hands: list[dict] = []
    total = 0
    for record in _iter_records(path):
        if record["type"] == "meta":
            if meta is not None or total:
                raise MatchLogCorruptionError("metadados duplicados ou fora da primeira linha")
            meta = record
            continue
        if meta is None:
            raise MatchLogCorruptionError("mão encontrada antes dos metadados")
        if total >= offset and (limit is None or len(hands) < limit):
            hands.append(record)
        total += 1
    if meta is None:
        raise MatchLogCorruptionError("arquivo de auditoria não contém metadados")
    game_id = meta.get("id")
    if not isinstance(game_id, str) or game_id != path.stem:
        raise MatchLogCorruptionError("id dos metadados diverge do nome canônico do arquivo")
    result = {"meta": meta, "hands": hands}
    if limit is not None:
        result["page"] = _page(offset, limit, total, len(hands))
    return result


def read_game(session_id: str, log_dir: Path | None = None) -> dict | None:
    """Partida completa (meta + todas as mãos) para auditoria/replay."""
    path = _game_path(session_id, log_dir)
    return _read_game_records(path, offset=0, limit=None) if path is not None else None


def read_game_page(
    session_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
    log_dir: Path | None = None,
) -> dict | None:
    _page(offset, limit, 0, 0)  # validate before touching the filesystem
    path = _game_path(session_id, log_dir)
    return _read_game_records(path, offset=offset, limit=limit) if path is not None else None

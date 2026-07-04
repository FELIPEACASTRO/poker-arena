"""Gravação e leitura da trilha de AUDITORIA das partidas.

Guarda TUDO de cada mão em disco (JSONL, 1 mão por linha): quem jogou, a ação, o
RACIOCÍNIO da IA naquele instante (glass-box), as cartas, o board por rua, os
vencedores e o resultado em fichas. Permite auditar/replay qualquer jogo depois.

Formato (logs/{session_id}.jsonl):
  linha 1: {"type":"meta", id, created, mode, blinds, seats...}
  linhas N: {"type":"hand", hand, ts, button, seats, actions[], board, pot, winners, result[]}
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


_MAX_GAMES = 10  # mantém só as N partidas mais recentes no histórico (evita lixo)


def _log_dir() -> Path:
    """Diretório dos logs (configurável por env -> testes usam um temp)."""
    env = os.environ.get("POKER_LOG_DIR")
    return Path(env) if env else (Path(__file__).resolve().parents[2] / "logs")


def prune_old_games(keep: int = _MAX_GAMES, log_dir: Path | None = None) -> int:
    """Apaga os logs de partida mais ANTIGOS, mantendo só os `keep` mais recentes.

    Só mexe nos logs GRAVADOS (o dir configurável); nunca toca nas partidas
    empacotadas com a solução (ex.: as mãos do Pluribus, que ficam em `_bundled_dir`).
    Devolve quantos arquivos foram removidos. Falhas de I/O são ignoradas (best-effort).
    """
    d = log_dir or _log_dir()
    if not d.exists():
        return 0
    files = sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    removed = 0
    for f in files[keep:]:  # do 11º mais recente em diante
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class MatchLogger:
    """Acumula a mão atual e grava no disco quando ela termina."""

    def __init__(self, session_id: str, meta: dict, log_dir: Path | None = None) -> None:
        self._dir = log_dir or _log_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self.path = self._dir / f"{session_id}.jsonl"
        self._cur: dict | None = None
        self._append({"type": "meta", "id": session_id, "created": _now(), **meta})
        prune_old_games(log_dir=self._dir)  # ao abrir uma nova partida, limpa as antigas

    def _append(self, obj: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def begin_hand(self, hand: int, button: int, seats: list[dict]) -> None:
        self._cur = {
            "type": "hand",
            "hand": hand,
            "ts": _now(),
            "button": button,
            "seats": seats,  # [{seat, name, level, start}]
            "actions": [],
        }

    def action(
        self,
        seat: int,
        name: str,
        level: str,
        action_type: str,
        amount: int,
        street: str,
        board: list[str],
        insight: dict | None,
    ) -> None:
        if self._cur is None:
            return
        self._cur["actions"].append(
            {
                "seat": seat,
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
            return
        self._cur.update({"board": list(board), "pot": pot, "winners": winners, "result": result})
        self._append(self._cur)
        self._cur = None


# ---------------- leitura (para a página de auditoria) ----------------
def _bundled_dir() -> Path:
    """Partidas EMPACOTADAS com a solução (ex.: as mãos publicadas do Pluribus,
    uoftcprg/phh-dataset, CC BY 4.0) — aparecem na auditoria como replay."""
    return Path(__file__).resolve().parents[1] / "data"


def _read_lines(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _summary_of(path: Path) -> dict | None:
    rows = _read_lines(path)
    meta = next((r for r in rows if r.get("type") == "meta"), None)
    if not meta:
        return None
    hands = [r for r in rows if r.get("type") == "hand"]
    return {
        "id": meta["id"],
        "created": meta.get("created"),
        "mode": meta.get("mode"),
        "levels": meta.get("levels", []),
        "hands": len(hands),
        "last": hands[-1]["ts"] if hands else meta.get("created"),
    }


def list_games(log_dir: Path | None = None) -> list[dict]:
    """Resumo de cada partida (gravadas + empacotadas), mais recente primeiro."""
    d = log_dir or _log_dir()
    games = []
    if d.exists():
        for f in d.glob("*.jsonl"):
            s = _summary_of(f)
            if s:
                games.append(s)
    games.sort(key=lambda g: g["last"] or "", reverse=True)
    bundled = _bundled_dir()
    if bundled.exists():  # empacotadas vão pro fim (histórico do usuário primeiro)
        for f in sorted(bundled.glob("*.jsonl")):
            s = _summary_of(f)
            if s:
                games.append(s)
    return games


def read_game(session_id: str, log_dir: Path | None = None) -> dict | None:
    """Partida completa (meta + todas as mãos) para auditoria/replay."""
    d = log_dir or _log_dir()
    path = d / f"{session_id}.jsonl"
    if not path.exists():  # não gravada? tenta as empacotadas (ex.: 'pluribus')
        path = _bundled_dir() / f"{session_id}.jsonl"
        if not path.exists():
            return None
    rows = _read_lines(path)
    meta = next((r for r in rows if r.get("type") == "meta"), None)
    if not meta:
        return None
    hands = [r for r in rows if r.get("type") == "hand"]
    return {"meta": meta, "hands": hands}

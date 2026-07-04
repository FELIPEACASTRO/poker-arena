"""Poda do histórico: manter só as N partidas mais recentes (evita lixo no disco)."""

import os
from pathlib import Path

from poker_arena.application.match_log import MatchLogger, prune_old_games


def _game_file(log_dir, name, mtime):
    """Cria um .jsonl de partida com mtime EXPLÍCITO (teste determinístico)."""
    p = Path(log_dir) / f"{name}.jsonl"
    p.write_text('{"type": "meta", "id": "' + name + '"}\n', encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


def test_prune_keeps_the_newest(tmp_path):
    for i in range(15):  # mtimes crescentes: g14 é o mais novo
        _game_file(tmp_path, f"g{i:02d}", mtime=1_000 + i)
    assert prune_old_games(keep=10, log_dir=tmp_path) == 5
    names = sorted(f.stem for f in tmp_path.glob("*.jsonl"))
    assert names == [f"g{i:02d}" for i in range(5, 15)]  # só os 10 mais recentes


def test_prune_noop_when_under_limit(tmp_path):
    for i in range(4):
        _game_file(tmp_path, f"g{i}", mtime=1_000 + i)
    assert prune_old_games(keep=10, log_dir=tmp_path) == 0
    assert len(list(tmp_path.glob("*.jsonl"))) == 4


def test_prune_idempotent_and_respects_keep(tmp_path):
    for i in range(12):
        _game_file(tmp_path, f"g{i:02d}", mtime=1_000 + i)
    assert prune_old_games(keep=10, log_dir=tmp_path) == 2  # tira as 2 mais antigas
    assert prune_old_games(keep=10, log_dir=tmp_path) == 0  # já enxuto -> nada
    assert prune_old_games(keep=3, log_dir=tmp_path) == 7   # keep menor tira o excedente


def test_matchlogger_autoprunes_on_new_game(tmp_path):
    # abrir 12 partidas via MatchLogger deixa no MÁXIMO 10 (a __init__ poda sozinha)
    for i in range(12):
        lg = MatchLogger(f"s{i:02d}", {"mode": "watch", "levels": []}, log_dir=tmp_path)
        lg.begin_hand(1, 0, [{"seat": 0, "name": "A", "level": "random", "start": 1000}])
        lg.finish_hand([], 0, [], [{"seat": 0, "name": "A", "end": 1000, "delta": 0}])
    assert len(list(tmp_path.glob("*.jsonl"))) <= 10

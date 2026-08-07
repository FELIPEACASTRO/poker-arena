"""Poda do histórico: manter só as N partidas mais recentes (evita lixo no disco)."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from poker_arena.application import BotSpec, SessionConfig, build_session
from poker_arena.application.game_session import _insight_dict
from poker_arena.application.match_log import (
    MatchLogCorruptionError,
    MatchLogger,
    _is_reparse_or_link,
    list_games_page,
    prune_old_games,
    read_game,
    read_game_page,
)
from poker_arena.bots.insight import BotInsight


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
    assert prune_old_games(keep=3, log_dir=tmp_path) == 7  # keep menor tira o excedente


def test_matchlogger_does_not_prune_history_without_explicit_retention(tmp_path):
    for i in range(12):
        lg = MatchLogger(f"s{i:02d}", {"mode": "watch", "levels": []}, log_dir=tmp_path)
        lg.begin_hand(
            1,
            0,
            [{"seat": 0, "player_id": "p0", "name": "A", "level": "random", "start": 1000}],
        )
        lg.finish_hand(
            [],
            0,
            [],
            [{"seat": 0, "player_id": "p0", "name": "A", "end": 1000, "delta": 0}],
        )
    assert len(list(tmp_path.glob("*.jsonl"))) == 12


@pytest.mark.parametrize("keep", [None, True, 0, -1, 1_000_001])
def test_prune_rejects_invalid_retention_without_deleting(tmp_path, keep):
    _game_file(tmp_path, "preserve", mtime=1_000)

    with pytest.raises(ValueError):
        prune_old_games(keep=keep, log_dir=tmp_path)

    assert (tmp_path / "preserve.jsonl").is_file()


@pytest.mark.parametrize("retention", [True, 0, -1, 1_000_001])
def test_matchlogger_rejects_invalid_retention_before_writing(tmp_path, retention):
    with pytest.raises(ValueError):
        MatchLogger("invalid-retention", {}, log_dir=tmp_path, retention=retention)

    assert not list(tmp_path.glob("*.jsonl"))


def test_match_log_records_every_players_hole_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("POKER_LOG_DIR", str(tmp_path))
    session = build_session(
        SessionConfig(bots=[BotSpec("B", "random")]),
        session_id="hole-audit",
        seed=1,
    )
    session.apply_human_action("fold")

    game = read_game("hole-audit", log_dir=tmp_path)
    assert game is not None
    seats = game["hands"][0]["seats"]
    assert all(len(seat["hole"]) == 2 for seat in seats)


def test_read_game_rejects_parent_directory_traversal(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text('{"type":"meta","id":"outside"}\n', encoding="utf-8")

    assert read_game(r"..\outside", log_dir=log_dir) is None


def test_matchlogger_rejects_traversal_in_session_id(tmp_path):
    log_dir = tmp_path / "logs"
    with pytest.raises(ValueError):
        MatchLogger(r"..\outside", {"mode": "watch"}, log_dir=log_dir)
    assert not (tmp_path / "outside.jsonl").exists()


def test_matchlogger_creates_session_file_exclusively(tmp_path):
    MatchLogger("same-session", {"mode": "watch"}, log_dir=tmp_path)

    with pytest.raises(MatchLogCorruptionError, match="ja existe"):
        MatchLogger("same-session", {"mode": "watch"}, log_dir=tmp_path)


def test_logger_rejects_out_of_order_events_instead_of_silently_omitting_them(tmp_path):
    logger = MatchLogger("ordered-events", {"mode": "watch"}, log_dir=tmp_path)

    with pytest.raises(MatchLogCorruptionError, match="ação recebida sem"):
        logger.action(0, "p0", "A", "random", "check", 0, "preflop", [], None)
    with pytest.raises(MatchLogCorruptionError, match="finalização recebida sem"):
        logger.finish_hand([], 0, [], [])

    logger.begin_hand(1, 0, [])
    with pytest.raises(MatchLogCorruptionError, match="não pode substituir"):
        logger.begin_hand(2, 1, [])


def test_logger_binds_actions_and_results_to_the_current_hand_roster(tmp_path):
    logger = MatchLogger("bound-roster", {"mode": "watch"}, log_dir=tmp_path)
    seat = {"seat": 0, "player_id": "p0", "name": "A", "level": "random", "start": 1000}
    with pytest.raises(MatchLogCorruptionError, match="número da mão"):
        logger.begin_hand(True, 0, [seat])
    with pytest.raises(MatchLogCorruptionError, match="button"):
        logger.begin_hand(1, 99, [seat])
    logger.begin_hand(1, 0, [seat])

    with pytest.raises(MatchLogCorruptionError, match="ação não corresponde"):
        logger.action(0, "other", "A", "random", "check", 0, "preflop", [], None)
    with pytest.raises(MatchLogCorruptionError, match="inteiro não negativo"):
        logger.action(0, "p0", "A", "random", "check", True, "preflop", [], None)
    with pytest.raises(MatchLogCorruptionError, match="street e board"):
        logger.action(0, "p0", "A", "random", "check", 0, "river", [], None)
    with pytest.raises(MatchLogCorruptionError, match="resultado não corresponde"):
        logger.finish_hand(
            [],
            0,
            [],
            [{"seat": 0, "player_id": "other", "name": "A", "end": 1000, "delta": 0}],
        )
    winner = {"seat": 0, "player_id": "p0", "name": "A"}
    with pytest.raises(MatchLogCorruptionError, match="repete vencedor"):
        logger.finish_hand(
            [],
            0,
            [winner, winner],
            [{"seat": 0, "player_id": "p0", "name": "A", "end": 1000, "delta": 0}],
        )
    with pytest.raises(MatchLogCorruptionError, match="pote final"):
        logger.finish_hand(
            [],
            -1,
            [],
            [{"seat": 0, "player_id": "p0", "name": "A", "end": 1000, "delta": 0}],
        )
    with pytest.raises(MatchLogCorruptionError, match="stack/delta finais"):
        logger.finish_hand(
            [],
            0,
            [],
            [{"seat": 0, "player_id": "p0", "name": "A", "end": "x", "delta": None}],
        )

    logger.action(0, "p0", "A", "random", "check", 0, "preflop", [], None)
    logger.finish_hand(
        [],
        0,
        [],
        [{"seat": 0, "player_id": "p0", "name": "A", "end": 1000, "delta": 0}],
    )

    bool_seat_logger = MatchLogger("bool-seat", {"mode": "watch"}, log_dir=tmp_path)
    seat_one = {"seat": 1, "player_id": "p1", "name": "B", "level": "random", "start": 1000}
    bool_seat_logger.begin_hand(1, 1, [seat_one])
    with pytest.raises(MatchLogCorruptionError, match="ação não corresponde"):
        bool_seat_logger.action(True, "p1", "B", "random", "check", 0, "preflop", [], None)


def test_matchlogger_rejects_reserved_metadata_identity_fields(tmp_path):
    with pytest.raises(ValueError, match="campos reservados"):
        MatchLogger("canonical", {"id": "other"}, log_dir=tmp_path)


def test_matchlogger_never_writes_an_integer_its_reader_would_reject(tmp_path):
    with pytest.raises(MatchLogCorruptionError, match="inteiro fora do limite"):
        MatchLogger("huge-int", {"large": 10**19}, log_dir=tmp_path)

    assert not (tmp_path / "huge-int.jsonl").exists()


def test_matchlogger_detects_file_replacement_before_next_append(tmp_path):
    logger = MatchLogger("replace-me", {"mode": "watch"}, log_dir=tmp_path)
    logger.path.unlink()
    logger.path.write_text('{"type":"meta","id":"attacker"}\n', encoding="utf-8")
    logger.begin_hand(1, 0, [])

    with pytest.raises(MatchLogCorruptionError, match="identidade"):
        logger.finish_hand([], 0, [], [])

    assert '"attacker"' in logger.path.read_text(encoding="utf-8")


def test_windows_reparse_attribute_is_recognized_without_platform_privilege():
    class ReparseStat:
        st_mode = 0o100600
        st_file_attributes = 0x400

    assert _is_reparse_or_link(ReparseStat())


def test_matchlogger_rejects_reparse_log_directory_without_platform_privilege(
    tmp_path, monkeypatch
):
    import poker_arena.application.match_log as module

    original_lstat = module.os.lstat

    def mark_log_dir_as_reparse(path):
        result = original_lstat(path)
        if Path(path) == tmp_path:
            return SimpleNamespace(
                st_mode=result.st_mode,
                st_file_attributes=0x400,
            )
        return result

    monkeypatch.setattr(module.os, "lstat", mark_log_dir_as_reparse)

    with pytest.raises(MatchLogCorruptionError, match="reparse"):
        MatchLogger("reparse-dir", {"mode": "watch"}, log_dir=tmp_path)

    assert not (tmp_path / "reparse-dir.jsonl").exists()


def test_matchlogger_rejects_non_regular_session_target(tmp_path):
    (tmp_path / "not-a-file.jsonl").mkdir()

    with pytest.raises(MatchLogCorruptionError, match="arquivo de auditoria"):
        MatchLogger("not-a-file", {"mode": "watch"}, log_dir=tmp_path)

    assert (tmp_path / "not-a-file.jsonl").is_dir()


def test_read_game_rejects_hard_linked_audit_file(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text('{"type":"meta","id":"hard-linked"}\n', encoding="utf-8")
    os.link(outside, log_dir / "hard-linked.jsonl")

    with pytest.raises(MatchLogCorruptionError, match="regular"):
        read_game("hard-linked", log_dir=log_dir)

    assert outside.read_text(encoding="utf-8").endswith("\n")


def test_logged_insight_preserves_expert_and_adaptive_evidence():
    insight = BotInsight(
        kind="expert",
        label="policy",
        confidence=0.8,
        probs=(0.1, 0.2, 0.3, 0.2, 0.2),
        fold_to_bet=0.7,
        bias=0.12,
    )
    logged = _insight_dict(insight)
    assert logged == {
        "kind": "expert",
        "label": "policy",
        "confidence": 0.8,
        "probs": [0.1, 0.2, 0.3, 0.2, 0.2],
        "fold_to_bet": 0.7,
        "bias": 0.12,
    }


def test_paginated_replay_reports_total_and_next_offset(tmp_path):
    path = tmp_path / "paged.jsonl"
    rows = [{"type": "meta", "id": "paged", "created": "2026-01-01"}]
    rows.extend(
        {"type": "hand", "hand": index, "ts": f"2026-01-01T00:00:0{index}"} for index in range(1, 6)
    )
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    page = read_game_page("paged", offset=1, limit=2, log_dir=tmp_path)

    assert page is not None
    assert [hand["hand"] for hand in page["hands"]] == [2, 3]
    assert page["page"] == {
        "offset": 1,
        "limit": 2,
        "returned": 2,
        "total": 5,
        "next_offset": 3,
    }


def test_corrupt_json_object_is_explicit_and_does_not_hide_healthy_game(tmp_path, caplog):
    _game_file(tmp_path, "healthy", mtime=2_000)
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text("[]\n", encoding="utf-8")

    with pytest.raises(MatchLogCorruptionError, match="objeto JSON"):
        read_game_page("corrupt", log_dir=tmp_path)

    listing = list_games_page(offset=0, limit=50, log_dir=tmp_path)
    assert "healthy" in {game["id"] for game in listing["games"]}
    assert "corrupt" not in {game["id"] for game in listing["games"]}
    assert listing["unreadable_logs"] == 1
    assert "corrupção" in caplog.text


@pytest.mark.parametrize(
    "payload, message",
    [
        ("", "não contém metadados"),
        ('{"type":"meta","id":"first","id":"second"}\n', "chave JSON duplicada"),
        ('{"type":"meta","id":"bad-number","score":NaN}\n', "número não finito"),
        ('{"type":"meta","id":"silent-corruption"}\n\n', "linha 2 vazia"),
        ('\ufeff{"type":"meta","id":"silent-corruption"}\n', "BOM UTF-8"),
        ('{"type":"meta","id":"silent-corruption","score":1e400}\n', "número não finito"),
        (
            '{"type":"meta","id":"silent-corruption","score":' + "9" * 5000 + "}\n",
            "inteiro fora do limite",
        ),
    ],
)
def test_empty_or_duplicate_key_log_is_never_silently_omitted(tmp_path, payload, message):
    path = tmp_path / "silent-corruption.jsonl"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(MatchLogCorruptionError, match=message):
        read_game("silent-corruption", log_dir=tmp_path)

    listing = list_games_page(log_dir=tmp_path)
    assert listing["unreadable_logs"] == 1
    assert "silent-corruption" not in {game["id"] for game in listing["games"]}


def test_log_metadata_identity_must_match_the_addressed_filename(tmp_path):
    (tmp_path / "alias.jsonl").write_text('{"type":"meta","id":"other"}\n', encoding="utf-8")

    with pytest.raises(MatchLogCorruptionError, match="nome canônico"):
        read_game("alias", log_dir=tmp_path)

    listing = list_games_page(log_dir=tmp_path)
    assert listing["unreadable_logs"] == 1


def test_writer_rejects_nonfinite_json_before_persisting_hand(tmp_path):
    logger = MatchLogger("finite-only", {"mode": "watch"}, log_dir=tmp_path)
    logger.begin_hand(
        1,
        0,
        [{"seat": 0, "player_id": "p0", "name": "A", "level": "random", "start": 1000}],
    )
    size_before = logger.path.stat().st_size

    with pytest.raises(MatchLogCorruptionError, match="número não finito"):
        logger.finish_hand(
            [],
            0,
            [],
            [
                {
                    "seat": 0,
                    "player_id": "p0",
                    "name": "A",
                    "end": 1000,
                    "delta": 0,
                    "payload": float("nan"),
                }
            ],
        )

    assert logger.path.stat().st_size == size_before


def test_writer_refuses_append_before_file_crosses_reader_quota(tmp_path, monkeypatch):
    import poker_arena.application.match_log as module

    monkeypatch.setattr(module, "_MAX_LOG_FILE_BYTES", 240)
    logger = MatchLogger("bounded", {"mode": "watch"}, log_dir=tmp_path)
    size_before = logger.path.stat().st_size
    logger.begin_hand(
        1,
        0,
        [{"seat": 0, "player_id": "p0", "name": "A", "level": "random", "start": 1000}],
    )

    with pytest.raises(MatchLogCorruptionError, match="cota antes da escrita"):
        logger.finish_hand(
            [],
            0,
            [],
            [
                {
                    "seat": 0,
                    "player_id": "p0",
                    "name": "A",
                    "end": 1000,
                    "delta": 0,
                    "payload": "x" * 300,
                }
            ],
        )

    assert logger.path.stat().st_size == size_before


def test_summary_cache_invalidates_when_append_changes_file(tmp_path, monkeypatch):
    import poker_arena.application.match_log as module

    path = _game_file(tmp_path, "cached-summary", mtime=2_000)
    original = module._summary_of
    calls = 0

    def counted(candidate):
        nonlocal calls
        if candidate == path:
            calls += 1
        return original(candidate)

    monkeypatch.setattr(module, "_summary_of", counted)
    first = list_games_page(offset=0, limit=50, log_dir=tmp_path)
    second = list_games_page(offset=0, limit=50, log_dir=tmp_path)
    assert first == second
    assert calls == 1

    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"hand","hand":1,"ts":"2026-01-01"}\n')
    refreshed = list_games_page(offset=0, limit=50, log_dir=tmp_path)
    refreshed_game = next(game for game in refreshed["games"] if game["id"] == "cached-summary")
    assert refreshed_game["hands"] == 1
    assert calls == 2


def test_prune_failure_is_observable_without_failing_availability(tmp_path, monkeypatch, caplog):
    _game_file(tmp_path, "new", mtime=2_000)
    old = _game_file(tmp_path, "old", mtime=1_000)
    original_unlink = Path.unlink

    def fail_old(self, *args, **kwargs):
        if self == old:
            raise OSError("locked")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_old)
    assert prune_old_games(keep=1, log_dir=tmp_path) == 0
    assert old.exists()
    assert "não foi possível remover log antigo" in caplog.text

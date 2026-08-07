"""Converte mãos PHH (uoftcprg/phh-dataset, CC BY 4.0) pro formato da Auditoria.

Uso:
    uv run python scripts/convert_pluribus.py <pasta_com_phh> <saida.jsonl> <upstream_git_commit>

O PHH é TOML (1 mão por arquivo) com ações em tokens:
    d dh pN XxYy   -> distribui hole cards ao jogador N (1-indexado)
    d db Xx...     -> distribui board (flop 3, turn 1, river 1)
    pN f | cc | cbr T | sm  -> fold | check/call | bet/raise PARA T | show

Reconstrói o pote/ruas simulando as apostas street a street (cbr é o total
comprometido na rua; cc paga a diferença limitada ao stack) e valida contra os
finishing_stacks do arquivo — a conversão só é aceita se a conta fechar.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

from pokerkit import HandHistory

STREETS = ["preflop", "flop", "turn", "river"]
_VALID_CARDS = frozenset(r + s for r in "23456789TJQKA" for s in "shdc")


def _cards(s: str) -> list[str]:
    if len(s) % 2:
        raise ValueError(f"sequência de cartas com comprimento ímpar: {s!r}")
    cards = [s[i : i + 2] for i in range(0, len(s), 2)]
    if any(card not in _VALID_CARDS for card in cards):
        raise ValueError(f"carta inválida: {s!r}")
    return cards


def _settlement_from_finishing(
    *,
    starts: list[int],
    finishing: list[int],
    committed: list[int],
    folded: list[bool],
    names: list[str],
    hand_no: int,
) -> tuple[int, list[dict], list[dict]]:
    """Separate refunds/awards after ``convert_hand`` verifies the PokerKit replay."""

    n = len(starts)
    refunds = [0] * n
    highest = max(committed, default=0)
    leaders = [seat for seat, value in enumerate(committed) if value == highest]
    if len(leaders) == 1:
        second = max(
            (value for seat, value in enumerate(committed) if seat != leaders[0]), default=0
        )
        refunds[leaders[0]] = max(0, highest - second)

    gross_returns = [finishing[i] - starts[i] + committed[i] for i in range(n)]
    awards = [gross_returns[i] - refunds[i] for i in range(n)]
    pot = sum(committed) - sum(refunds)
    if any(value < 0 for value in gross_returns + awards):
        raise ValueError(f"mão {hand_no}: retorno/premiação negativo é impossível")
    if sum(gross_returns) != sum(committed) or sum(awards) != pot:
        raise ValueError(f"mão {hand_no}: liquidação diverge dos finishing_stacks")
    if any(folded[seat] and awards[seat] > 0 for seat in range(n)):
        raise ValueError(f"mão {hand_no}: jogador foldado recebeu pote contestável")

    winners = [
        {"seat": seat, "name": names[seat], "award": awards[seat]}
        for seat in range(n)
        if awards[seat] > 0
    ]
    uncalled_refunds = [
        {"seat": seat, "name": names[seat], "amount": refunds[seat]}
        for seat in range(n)
        if refunds[seat] > 0
    ]
    return pot, winners, uncalled_refunds


def convert_hand(raw: dict, hand_no: int) -> dict:
    names: list[str] = raw["players"]
    n = len(names)
    starts: list[int] = list(raw["starting_stacks"])
    blinds: list[int] = list(raw["blinds_or_straddles"])
    finishing: list[int] = list(raw["finishing_stacks"])
    if n < 2 or len(set(names)) != n:
        raise ValueError(f"mão {hand_no}: jogadores ausentes ou duplicados")
    if len(starts) != n or len(finishing) != n or len(blinds) > n:
        raise ValueError(f"mão {hand_no}: vetores de jogadores/stacks incompatíveis")
    if any(
        isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in starts + finishing + blinds
    ):
        raise ValueError(f"mão {hand_no}: stacks/blinds devem ser inteiros não negativos")
    levels = ["pluribus" if nm == "Pluribus" else "pro" for nm in names]

    committed = [0] * n  # total na mão
    cur = list(blinds[:n]) + [0] * max(0, n - len(blinds))  # nesta rua (começa nas blinds)
    for i in range(n):
        committed[i] = cur[i]
        if committed[i] > starts[i]:
            raise ValueError(f"mão {hand_no}: blind excede stack no assento {i}")
    street_max = max(cur)
    street_idx = 0
    board: list[str] = []
    actions: list[dict] = []
    folded = [False] * n
    dealt: set[str] = set()

    for tok in raw["actions"]:
        parts = tok.split()
        if len(parts) < 2:
            raise ValueError(f"token malformado: {tok!r}")
        if parts[0] == "d":
            if parts[1] == "db":  # nova rua: board cresce e as apostas zeram
                if len(parts) != 3 or street_idx >= 3:
                    raise ValueError(f"token de board malformado/fora de ordem: {tok!r}")
                new_cards = _cards(parts[2])
                expected = 3 if street_idx == 0 else 1
                if len(new_cards) != expected:
                    raise ValueError(
                        f"board na rua {street_idx + 1} deve adicionar {expected} carta(s)"
                    )
                if dealt.intersection(new_cards) or len(set(new_cards)) != len(new_cards):
                    raise ValueError(f"board contém carta duplicada: {tok!r}")
                dealt.update(new_cards)
                board.extend(new_cards)
                street_idx += 1
                cur = [0] * n
                street_max = 0
            elif parts[1] == "dh":
                if len(parts) != 4 or not parts[2].startswith("p"):
                    raise ValueError(f"token de hole malformado: {tok!r}")
                hole_cards = _cards(parts[3])
                if len(hole_cards) != 2:
                    raise ValueError(f"hole deve conter exatamente 2 cartas: {tok!r}")
                if dealt.intersection(hole_cards) or len(set(hole_cards)) != 2:
                    raise ValueError(f"carta duplicada na distribuição: {tok!r}")
                dealt.update(hole_cards)
            else:
                raise ValueError(f"token de distribuição desconhecido: {tok!r}")
            continue  # distribuição não vira linha de ação na auditoria
        seat = int(parts[0][1:]) - 1  # p1 -> 0
        if not 0 <= seat < n:
            raise ValueError(f"assento fora do intervalo: {tok!r}")
        verb = parts[1]
        if verb == "sm":
            continue  # showdown reveal — o resultado já cobre
        if folded[seat]:
            raise ValueError(f"jogador já foldado voltou a agir: {tok!r}")
        street = STREETS[min(street_idx, 3)]
        if verb == "f":
            folded[seat] = True
            act, amount = "fold", 0
        elif verb == "cc":
            owe = street_max - cur[seat]
            pay = min(owe, starts[seat] - committed[seat])
            cur[seat] += pay
            committed[seat] += pay
            act, amount = ("check", 0) if pay == 0 else ("call", 0)
        elif verb == "cbr":
            if len(parts) != 3:
                raise ValueError(f"token cbr malformado: {tok!r}")
            to = int(parts[2])
            add = to - cur[seat]
            available = starts[seat] - committed[seat]
            if add <= 0 or to <= street_max or add > available:
                raise ValueError(
                    f"cbr inválido em {tok!r}: atual={cur[seat]}, maior={street_max}, "
                    f"disponível={available}"
                )
            cur[seat] = to
            committed[seat] += add
            street_max = max(street_max, to)
            all_in = committed[seat] >= starts[seat]
            act, amount = ("all_in" if all_in else "raise"), to
        else:
            raise ValueError(f"token desconhecido: {tok!r}")
        actions.append(
            {
                "seat": seat,
                "name": names[seat],
                "level": levels[seat],
                "street": street,
                "action": act,
                "amount": amount,
                "board": list(board),
                "insight": None,
            }
        )

    # Oracle independente: o parser/replay PHH oficial do PokerKit precisa chegar
    # ao mesmo estado terminal. Assim ``finishing_stacks`` não é tratado como
    # prova circular nem pode fabricar uma divisão de potes irrealizável.
    try:
        replay = list(HandHistory(**raw))
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(f"mão {hand_no}: replay PokerKit rejeitou o PHH") from exc
    if not replay or replay[-1].status or list(replay[-1].stacks) != finishing:
        raise ValueError(f"mão {hand_no}: replay PokerKit diverge dos finishing_stacks")

    # validação adicional: conservação de fichas contra o estado verificado
    deltas = [finishing[i] - starts[i] for i in range(n)]
    if sum(deltas) != 0:
        raise ValueError(f"mão {hand_no}: fichas não conservam ({deltas})")
    pot, winners, uncalled_refunds = _settlement_from_finishing(
        starts=starts,
        finishing=finishing,
        committed=committed,
        folded=folded,
        names=names,
        hand_no=hand_no,
    )
    result = [
        {"seat": i, "name": names[i], "end": finishing[i], "delta": deltas[i]} for i in range(n)
    ]
    return {
        "type": "hand",
        "hand": hand_no,
        "ts": "2019-07-11T00:00:00Z",
        "ts_semantics": "data de publicação do paper; horário da mão indisponível",
        "button": n - 1,  # PHH: p1 = small blind -> botão é o último
        "seats": [
            {"seat": i, "name": names[i], "level": levels[i], "start": starts[i]} for i in range(n)
        ],
        "actions": actions,
        "board": board,
        "pot": pot,
        "winners": winners,
        "uncalled_refunds": uncalled_refunds,
        "result": result,
    }


def main() -> None:
    if len(sys.argv) != 4 or re.fullmatch(r"[0-9a-f]{40}", sys.argv[3]) is None:
        sys.exit(
            "uso: convert_pluribus.py <pasta_com_phh> <saida.jsonl> <upstream_git_commit_sha1>"
        )
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    upstream_git_commit = sys.argv[3]
    out.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(src.rglob("*.phh"), key=lambda path: path.relative_to(src).as_posix())
    if not files:
        sys.exit(f"nenhum .phh em {src}")
    source_digest = hashlib.sha256()
    for source_file in files:
        relative = source_file.relative_to(src).as_posix().encode("utf-8")
        payload = source_file.read_bytes()
        source_digest.update(len(relative).to_bytes(4, "big"))
        source_digest.update(relative)
        source_digest.update(hashlib.sha256(payload).digest())
    converter_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    lines = [
        json.dumps(
            {
                "type": "meta",
                "id": "pluribus",
                "created": "2019-07-11T00:00:00Z",
                "created_semantics": "data de publicação do paper; horário das mãos indisponível",
                "mode": "pluribus",
                "levels": ["pluribus", "pro"],
                "source": "uoftcprg/phh-dataset (CC BY 4.0) — Pluribus vs pros, Science 2019",
                "source_url": "https://github.com/uoftcprg/phh-dataset",
                "upstream_git_commit": upstream_git_commit,
                "license": "CC BY 4.0",
                "converter": "backend/scripts/convert_pluribus.py",
                "converter_sha256": converter_sha256,
                "upstream_snapshot_sha256": source_digest.hexdigest(),
                "upstream_file_count": len(files),
            },
            ensure_ascii=False,
        )
    ]
    for k, f in enumerate(files, start=1):
        payload = f.read_bytes()
        raw = tomllib.loads(payload.decode("utf-8"))
        converted = convert_hand(raw, k)
        converted["source_file"] = f.relative_to(src).as_posix()
        converted["source_sha256"] = hashlib.sha256(payload).hexdigest()
        converted["blinds_or_straddles"] = raw["blinds_or_straddles"]
        converted["antes"] = raw["antes"]
        lines.append(json.dumps(converted, ensure_ascii=False))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK: {len(files)} mãos -> {out}")


if __name__ == "__main__":
    main()

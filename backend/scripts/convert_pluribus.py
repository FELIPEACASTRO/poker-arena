"""Converte mãos PHH (uoftcprg/phh-dataset, CC BY 4.0) pro formato da Auditoria.

Uso:
    uv run python scripts/convert_pluribus.py <pasta_com_phh> [saida.jsonl]

O PHH é TOML (1 mão por arquivo) com ações em tokens:
    d dh pN XxYy   -> distribui hole cards ao jogador N (1-indexado)
    d db Xx...     -> distribui board (flop 3, turn 1, river 1)
    pN f | cc | cbr T | sm  -> fold | check/call | bet/raise PARA T | show

Reconstrói o pote/ruas simulando as apostas street a street (cbr é o total
comprometido na rua; cc paga a diferença limitada ao stack) e valida contra os
finishing_stacks do arquivo — a conversão só é aceita se a conta fechar.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

STREETS = ["preflop", "flop", "turn", "river"]
_VALID_CARDS = frozenset(r + s for r in "23456789TJQKA" for s in "shdc")


def _cards(s: str) -> list[str]:
    if len(s) % 2:
        raise ValueError(f"sequência de cartas com comprimento ímpar: {s!r}")
    cards = [s[i : i + 2] for i in range(0, len(s), 2)]
    if any(card not in _VALID_CARDS for card in cards):
        raise ValueError(f"carta inválida: {s!r}")
    return cards


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

    pot = sum(committed)
    # validação: conservação de fichas contra os finishing_stacks oficiais
    deltas = [finishing[i] - starts[i] for i in range(n)]
    if sum(deltas) != 0:
        raise ValueError(f"mão {hand_no}: fichas não conservam ({deltas})")
    losers_paid = -sum(d for d in deltas if d < 0)
    if losers_paid > pot:
        raise ValueError(f"mão {hand_no}: pote simulado ({pot}) < perdas ({losers_paid})")

    winners = [{"seat": i, "name": names[i]} for i in range(n) if deltas[i] > 0]
    result = [
        {"seat": i, "name": names[i], "end": finishing[i], "delta": deltas[i]} for i in range(n)
    ]
    return {
        "type": "hand",
        "hand": hand_no,
        "ts": "2019-07-11T00:00:00",  # sessões publicadas com o paper (Science, 2019)
        "button": n - 1,  # PHH: p1 = small blind -> botão é o último
        "seats": [
            {"seat": i, "name": names[i], "level": levels[i], "start": starts[i]} for i in range(n)
        ],
        "actions": actions,
        "board": board,
        "pot": pot,
        "winners": winners,
        "result": result,
    }


def main() -> None:
    src = Path(sys.argv[1])
    out = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else (Path(__file__).resolve().parents[1] / "poker_arena" / "data" / "pluribus.jsonl")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(src.glob("*.phh"))
    if not files:
        sys.exit(f"nenhum .phh em {src}")
    lines = [
        json.dumps(
            {
                "type": "meta",
                "id": "pluribus",
                "created": "2019-07-11T00:00:00",
                "mode": "pluribus",
                "levels": ["pluribus", "pro"],
                "source": "uoftcprg/phh-dataset (CC BY 4.0) — Pluribus vs pros, Science 2019",
                "license": "CC BY 4.0",
                "converter": "backend/scripts/convert_pluribus.py",
            },
            ensure_ascii=False,
        )
    ]
    for k, f in enumerate(files, start=1):
        raw = tomllib.loads(f.read_text(encoding="utf-8"))
        lines.append(json.dumps(convert_hand(raw, k), ensure_ascii=False))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK: {len(files)} mãos -> {out}")


if __name__ == "__main__":
    main()

"""Estatísticas AO VIVO do modo laboratório (jogo automático, só bots).

Acumula em memória, a partir dos mesmos eventos do MatchLogger, métricas que
revelam a PERSONALIDADE de cada paradigma de IA emergindo do jogo real:
  - placar: fichas, lucro, mãos ganhas;
  - VPIP (% de mãos que entra) -> solto x apertado;
  - agressão (% de ações que são aposta/aumento) -> agressivo x passivo;
  - corrida das fichas (stack de cada bot ao fim de cada mão) -> o gráfico;
  - estatísticas da sessão (mãos, showdowns, maior pote).

Tudo dado real, sem mock.
"""

from __future__ import annotations

_AGGR = {"raise", "all_in"}  # ações agressivas
_VPIP = {"call", "raise", "all_in"}  # entrou voluntariamente no pote


class WatchStats:
    def __init__(self) -> None:
        self.info: dict[int, dict] = {}  # seat -> {seat, name, level}
        self.per: dict[int, dict] = {}  # seat -> contadores
        self.timeline: list[dict] = []  # [{stacks: {seat: stack}}]
        self.hands = 0
        self.showdowns = 0
        self.biggest_pot = 0
        self.biggest_pot_winner: str | None = None
        self._start_set = False
        self._vpip_hand: set[int] = set()

    def _ensure(self, seat: int, name: str, level: str) -> None:
        if seat not in self.per:
            self.info[seat] = {"seat": seat, "name": name, "level": level}
            self.per[seat] = {
                "hands_dealt": 0,
                "hands_won": 0,
                "vpip": 0,
                "aggressive": 0,
                "actions": 0,
                "stack": 0,
                "start": 0,
            }

    def begin_hand(self, seats: list[dict]) -> None:
        self._vpip_hand.clear()
        for s in seats:
            self._ensure(s["seat"], s["name"], s["level"])
            p = self.per[s["seat"]]
            p["hands_dealt"] += 1
            p["stack"] = s["start"]
            if not self._start_set:
                p["start"] = s["start"]
        self._start_set = True

    def action(self, seat: int, action_type: str, street: str) -> None:
        p = self.per.get(seat)
        if p is None:
            return
        p["actions"] += 1
        if action_type in _AGGR:
            p["aggressive"] += 1
        if street == "preflop" and action_type in _VPIP:
            self._vpip_hand.add(seat)

    def finish_hand(
        self, winners: list[dict], pot: int, result: list[dict], showdown: bool
    ) -> None:
        self.hands += 1
        if showdown:
            self.showdowns += 1
        if pot > self.biggest_pot:
            self.biggest_pot = pot
            self.biggest_pot_winner = winners[0]["name"] if winners else None
        for seat in self._vpip_hand:
            self.per[seat]["vpip"] += 1
        for w in winners:
            if w["seat"] in self.per:
                self.per[w["seat"]]["hands_won"] += 1
        for r in result:
            if r["seat"] in self.per:
                self.per[r["seat"]]["stack"] = r["end"]
        self.timeline.append({"stacks": {r["seat"]: r["end"] for r in result}})

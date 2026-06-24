"""Estatísticas AO VIVO do modo laboratório (jogo automático, só bots).

Acumula em memória, a partir dos mesmos eventos do MatchLogger, métricas que
revelam a PERSONALIDADE de cada paradigma de IA emergindo do jogo real:
  - placar: fichas, lucro, mãos ganhas;
  - VPIP (% de mãos que entra) -> solto x apertado;
  - agressão (% de ações que são aposta/aumento) -> agressivo x passivo;
  - corrida das fichas (stack de cada bot ao fim de cada mão) -> o gráfico;
  - estatísticas da sessão (mãos, showdowns, maior pote).

Indexado por NOME (não por cadeira): assim continua correto quando jogadores
entram ou saem da mesa e os índices de cadeira mudam. Tudo dado real, sem mock.
"""

from __future__ import annotations

_AGGR = {"raise", "all_in"}  # ações agressivas
_VPIP = {"call", "raise", "all_in"}  # entrou voluntariamente no pote


class WatchStats:
    def __init__(self) -> None:
        self.info: dict[str, dict] = {}  # name -> {name, level, seat}
        self.per: dict[str, dict] = {}  # name -> contadores
        self.timeline: list[dict] = []  # [{name: stack}]
        self.hands = 0
        self.showdowns = 0
        self.biggest_pot = 0
        self.biggest_pot_winner: str | None = None
        self._start_set = False
        self._vpip_hand: set[str] = set()

    def _ensure(self, name: str, level: str, seat: int) -> None:
        if name not in self.per:
            self.per[name] = {
                "hands_dealt": 0,
                "hands_won": 0,
                "vpip": 0,
                "aggressive": 0,
                "actions": 0,
                "stack": 0,
                "start": 0,
            }
        self.info[name] = {"name": name, "level": level, "seat": seat}  # cadeira mais recente

    def begin_hand(self, seats: list[dict]) -> None:
        self._vpip_hand.clear()
        for s in seats:
            self._ensure(s["name"], s["level"], s["seat"])
            p = self.per[s["name"]]
            p["hands_dealt"] += 1
            p["stack"] = s["start"]
            if not self._start_set:
                p["start"] = s["start"]
        self._start_set = True

    def action(self, name: str, action_type: str, street: str) -> None:
        p = self.per.get(name)
        if p is None:
            return
        p["actions"] += 1
        if action_type in _AGGR:
            p["aggressive"] += 1
        if street == "preflop" and action_type in _VPIP:
            self._vpip_hand.add(name)

    def finish_hand(
        self, winners: list[dict], pot: int, result: list[dict], showdown: bool
    ) -> None:
        self.hands += 1
        if showdown:
            self.showdowns += 1
        if pot > self.biggest_pot:
            self.biggest_pot = pot
            self.biggest_pot_winner = winners[0]["name"] if winners else None
        for name in self._vpip_hand:
            if name in self.per:
                self.per[name]["vpip"] += 1
        for w in winners:
            if w["name"] in self.per:
                self.per[w["name"]]["hands_won"] += 1
        for r in result:
            if r["name"] in self.per:
                self.per[r["name"]]["stack"] = r["end"]
        self.timeline.append({"stacks": {r["name"]: r["end"] for r in result}})

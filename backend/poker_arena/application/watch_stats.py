"""Estatísticas AO VIVO do modo laboratório (jogo automático, só bots).

Acumula em memória, a partir dos mesmos eventos do MatchLogger, as métricas de
HUD clássicas que revelam a PERSONALIDADE de cada paradigma de IA:
  - placar: fichas, lucro, mãos ganhas;
  - VPIP  (% de mãos que entra voluntariamente)      -> solto x apertado;
  - PFR   (% de mãos que ABRE aumentando no pré-flop) -> o gap VPIP-PFR separa
    o agressivo (raise) do passivo (só paga);
  - agressão (% de ações que são aposta/aumento)      -> agressivo x passivo;
  - WTSD  (% das mãos em que viu o flop e chegou ao showdown) -> "paga-tudo";
  - W$SD  (% dos showdowns que venceu)                -> qualidade no showdown;
  - VPIP/PFR por REGIÃO da mesa (cedo/meio/tarde/blinds) -> disciplina posicional;
  - corrida das fichas (stack ao fim de cada mão) e stats da sessão.

Definições (padrão PokerTracker/Hold'em Manager):
  VPIP: pôs fichas voluntariamente no pré-flop (call/raise/all-in; blinds NÃO contam).
  PFR : aumentou (raise/all-in agressivo) no pré-flop.
  WTSD: numerador = chegou ao showdown; denominador = mãos em que VIU O FLOP.
  W$SD: numerador = venceu no showdown; denominador = showdowns disputados.

Indexado por NOME (não por cadeira): continua correto quando jogadores entram ou
saem da mesa. Tudo dado real, sem mock.
"""

from __future__ import annotations

_AGGR = {"raise", "all_in"}  # ações agressivas
_VPIP = {"call", "raise", "all_in"}  # entrou voluntariamente no pote
_POSTFLOP = {"flop", "turn", "river"}

# regiões da mesa (agrega posições p/ amostras estatisticamente úteis)
POS_BUCKETS = ("early", "middle", "late", "blinds")
_BUCKET_OF = {
    "UTG": "early", "UTG+1": "early",
    "MP1": "middle", "MP2": "middle",
    "DJ": "late", "HJ": "late", "BTN": "late",
    "SB": "blinds", "BB": "blinds",
}


def bucket_of(position: str) -> str:
    """Região da mesa de uma posição (posição desconhecida cai em 'middle')."""
    return _BUCKET_OF.get(position, "middle")


def _new_per() -> dict:
    return {
        "hands_dealt": 0,
        "hands_won": 0,
        "vpip": 0,
        "pfr": 0,
        "aggressive": 0,
        "actions": 0,
        "saw_flop": 0,
        "wtsd": 0,  # showdowns disputados (viu o flop e mostrou)
        "wsd": 0,  # showdowns vencidos
        "stack": 0,
        "start": 0,
        # por região: bucket -> [mãos, vpip, pfr]
        "pos": {b: [0, 0, 0] for b in POS_BUCKETS},
    }


class WatchStats:
    def __init__(self) -> None:
        self.info: dict[str, dict] = {}  # name -> {name, level, seat}
        self.per: dict[str, dict] = {}  # name -> contadores
        self.timeline: list[dict] = []  # [{stacks: {name: stack}}]
        self.hands = 0
        self.showdowns = 0
        self.biggest_pot = 0
        self.biggest_pot_winner: str | None = None
        self._start_set = False
        self._vpip_hand: set[str] = set()
        self._pfr_hand: set[str] = set()
        self._saw_flop_hand: set[str] = set()
        self._bucket_hand: dict[str, str] = {}  # name -> região nesta mão

    def _ensure(self, name: str, level: str, seat: int) -> None:
        if name not in self.per:
            self.per[name] = _new_per()
        self.info[name] = {"name": name, "level": level, "seat": seat}  # cadeira mais recente

    def begin_hand(self, seats: list[dict]) -> None:
        self._vpip_hand.clear()
        self._pfr_hand.clear()
        self._saw_flop_hand.clear()
        self._bucket_hand.clear()
        for s in seats:
            self._ensure(s["name"], s["level"], s["seat"])
            p = self.per[s["name"]]
            p["hands_dealt"] += 1
            p["stack"] = s["start"]
            if not self._start_set:
                p["start"] = s["start"]
            bucket = bucket_of(s.get("position", ""))
            self._bucket_hand[s["name"]] = bucket
            p["pos"][bucket][0] += 1
        self._start_set = True

    def action(self, name: str, action_type: str, street: str) -> None:
        p = self.per.get(name)
        if p is None:
            return
        p["actions"] += 1
        if action_type in _AGGR:
            p["aggressive"] += 1
        if street == "preflop":
            if action_type in _VPIP:
                self._vpip_hand.add(name)
            if action_type in _AGGR:
                self._pfr_hand.add(name)
        elif street in _POSTFLOP:
            self._saw_flop_hand.add(name)

    def finish_hand(
        self,
        winners: list[dict],
        pot: int,
        result: list[dict],
        showdown: bool,
        contenders: list[str] | None = None,
    ) -> None:
        self.hands += 1
        if showdown:
            self.showdowns += 1
        if pot > self.biggest_pot:
            self.biggest_pot = pot
            self.biggest_pot_winner = winners[0]["name"] if winners else None
        # quem foi all-in cedo pode não ter agido pós-flop, mas disputou o showdown
        if showdown and contenders:
            self._saw_flop_hand.update(n for n in contenders if n in self.per)
        for name in self._vpip_hand:
            if name in self.per:
                self.per[name]["vpip"] += 1
                bucket = self._bucket_hand.get(name)
                if bucket:
                    self.per[name]["pos"][bucket][1] += 1
        for name in self._pfr_hand:
            if name in self.per:
                self.per[name]["pfr"] += 1
                bucket = self._bucket_hand.get(name)
                if bucket:
                    self.per[name]["pos"][bucket][2] += 1
        for name in self._saw_flop_hand:
            if name in self.per:
                self.per[name]["saw_flop"] += 1
        win_names = {w["name"] for w in winners}
        if showdown and contenders:
            for name in contenders:
                if name in self.per:
                    self.per[name]["wtsd"] += 1
                    if name in win_names:
                        self.per[name]["wsd"] += 1
        for w in winners:
            if w["name"] in self.per:
                self.per[w["name"]]["hands_won"] += 1
        for r in result:
            if r["name"] in self.per:
                self.per[r["name"]]["stack"] = r["end"]
        self.timeline.append({"stacks": {r["name"]: r["end"] for r in result}})

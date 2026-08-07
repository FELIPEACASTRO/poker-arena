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

Indexado por identidade imutável de jogador (não por nome nem cadeira): continua
correto quando cadeiras são reindexadas ou um nome é reutilizado. Tudo dado real,
sem mock. A série ao vivo é uma janela limitada; o log de auditoria guarda o
histórico completo.
"""

from __future__ import annotations

from collections import deque

_AGGR = {"raise", "all_in"}  # ações agressivas
_VPIP = {"call", "raise", "all_in"}  # entrou voluntariamente no pote
_POSTFLOP = {"flop", "turn", "river"}
LIVE_TIMELINE_LIMIT = 500

# regiões da mesa (agrega posições p/ amostras estatisticamente úteis)
POS_BUCKETS = ("early", "middle", "late", "blinds")
_BUCKET_OF = {
    "UTG": "early",
    "UTG+1": "early",
    "MP": "middle",
    "LJ": "middle",
    "HJ": "late",
    "CO": "late",
    "BTN": "late",
    "SB": "blinds",
    "BB": "blinds",
}


def bucket_of(position: str) -> str:
    """Região da mesa de uma posição (posição desconhecida cai em 'middle')."""
    return _BUCKET_OF.get(position, "middle")


def _player_key(item: dict) -> str:
    """Return the stable ID, with a name fallback for legacy/unit-test events."""
    return str(item.get("player_id") or item["name"])


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
        self.info: dict[str, dict] = {}  # player_id -> {player_id, name, level, seat}
        self.per: dict[str, dict] = {}  # player_id -> contadores
        self.timeline: deque[dict] = deque(maxlen=LIVE_TIMELINE_LIMIT)
        self.hands = 0
        self.showdowns = 0
        self.biggest_pot = 0
        self.biggest_pot_winner: str | None = None
        self._start_set = False
        self._vpip_hand: set[str] = set()
        self._pfr_hand: set[str] = set()
        self._saw_flop_hand: set[str] = set()
        self._bucket_hand: dict[str, str] = {}  # player_id -> região nesta mão

    def _ensure(self, player_id: str, name: str, level: str, seat: int) -> None:
        if player_id not in self.per:
            self.per[player_id] = _new_per()
        self.info[player_id] = {
            "player_id": player_id,
            "name": name,
            "level": level,
            "seat": seat,
        }  # cadeira mais recente

    def begin_hand(self, seats: list[dict]) -> None:
        self._vpip_hand.clear()
        self._pfr_hand.clear()
        self._saw_flop_hand.clear()
        self._bucket_hand.clear()
        for s in seats:
            player_id = _player_key(s)
            is_new = player_id not in self.per
            self._ensure(player_id, s["name"], s["level"], s["seat"])
            p = self.per[player_id]
            p["hands_dealt"] += 1
            p["stack"] = s["start"]
            if is_new:
                p["start"] = s["start"]
            bucket = bucket_of(s.get("position", ""))
            self._bucket_hand[player_id] = bucket
            p["pos"][bucket][0] += 1
        self._start_set = True

    def action(
        self,
        player_id: str,
        action_type: str,
        street: str,
        *,
        aggressive: bool | None = None,
    ) -> None:
        p = self.per.get(player_id)
        if p is None:
            return
        is_aggressive = action_type in _AGGR if aggressive is None else aggressive
        p["actions"] += 1
        if is_aggressive:
            p["aggressive"] += 1
        if street == "preflop":
            if action_type in _VPIP:
                self._vpip_hand.add(player_id)
            if is_aggressive:
                self._pfr_hand.add(player_id)
        elif street in _POSTFLOP:
            self._saw_flop_hand.add(player_id)

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
            self._saw_flop_hand.update(player_id for player_id in contenders if player_id in self.per)
        for player_id in self._vpip_hand:
            if player_id in self.per:
                self.per[player_id]["vpip"] += 1
                bucket = self._bucket_hand.get(player_id)
                if bucket:
                    self.per[player_id]["pos"][bucket][1] += 1
        for player_id in self._pfr_hand:
            if player_id in self.per:
                self.per[player_id]["pfr"] += 1
                bucket = self._bucket_hand.get(player_id)
                if bucket:
                    self.per[player_id]["pos"][bucket][2] += 1
        for player_id in self._saw_flop_hand:
            if player_id in self.per:
                self.per[player_id]["saw_flop"] += 1
        winner_ids = {_player_key(w) for w in winners}
        if showdown and contenders:
            for player_id in contenders:
                if player_id in self.per:
                    self.per[player_id]["wtsd"] += 1
                    if player_id in winner_ids:
                        self.per[player_id]["wsd"] += 1
        for w in winners:
            player_id = _player_key(w)
            if player_id in self.per:
                self.per[player_id]["hands_won"] += 1
        for r in result:
            player_id = _player_key(r)
            if player_id in self.per:
                self.per[player_id]["stack"] = r["end"]
        self.timeline.append({"stacks": {_player_key(r): r["end"] for r in result}})

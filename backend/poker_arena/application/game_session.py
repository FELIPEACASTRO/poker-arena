"""GameSession — orquestra motor + bots (padrão Facade).

Dois modos:
- **jogar** (`mode="play"`): humano numa cadeira; pausa em `human_turn` esperando
  a ação; os bots jogam sozinhos.
- **assistir** (`mode="watch"`): todos são bots; pausa em `bot_turn` a cada jogada,
  avançada via `step()` (pra dar pra acompanhar lance a lance, com cartas abertas).

Separa comandos (escrita) de queries (leitura) — CQRS-lite. Depende só do domínio.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from ..bots.adaptive_bot import AdaptiveBot
from ..bots.base import Bot, Explainable
from ..bots.insight import BotInsight
from ..bots.observation import observation_for
from ..bots.opponent_model import OpponentModel
from ..engine.actions import Action, ActionType
from ..engine.cards import Card
from ..engine.game import Hand
from ..engine.player import Player, PlayerStatus
from ..engine.table import Table
from .bot_factory import create_bot
from .match_log import MatchLogger
from .views import (
    ActionView,
    BotStatView,
    ChipSeriesView,
    InsightView,
    LegalView,
    OpponentReadView,
    PosStatView,
    RosterSeatView,
    SeatView,
    TableStateView,
    WatchStatsView,
)
from .watch_stats import WatchStats

_log = logging.getLogger(__name__)
_MAX_LOG = 12
_ACTIVE = ("human_turn", "bot_turn")
_TYPES: dict[str, ActionType] = {
    "fold": ActionType.FOLD,
    "check": ActionType.CHECK,
    "call": ActionType.CALL,
    "raise": ActionType.RAISE,
    "all_in": ActionType.ALL_IN,
}


class InvalidActionError(ValueError):
    """Ação inválida para o estado atual da sessão."""


@dataclass(frozen=True)
class BotSpec:
    name: str
    level: str


@dataclass
class SessionConfig:
    human_name: str = "VOCE"
    bots: list[BotSpec] = field(default_factory=list)
    starting_stack: int = 1000
    small_blind: int = 10
    big_blind: int = 20
    rebuy: bool = True  # cash game: quem zera recompra -> a mesa segue cheia
    mode: str = "play"  # "play" (humano joga) | "watch" (só bots, você assiste)
    hand_limit: int | None = None  # para após N mãos (None = sem limite)


def _cards(cards: list[Card]) -> list[str]:
    return [str(c) for c in cards]


_STREET = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}


def _insight_dict(ins: BotInsight | None) -> dict | None:
    if ins is None:
        return None
    return {"kind": ins.kind, "label": ins.label, "confidence": round(ins.confidence, 3)}


MAX_SEATS = 9  # mesa até 9 jogadores (9-max)
_NAME_POOL = (
    "Ana", "Beto", "Cleo", "Duda", "Edu", "Fil", "Gabi", "Hugo",
    "Ivo", "Jana", "Kiko", "Lia", "Mia", "Nina", "Theo", "Vera",
)


class GameSession:
    def __init__(
        self,
        session_id: str,
        table: Table,
        human: Player | None,
        human_seat: int | None,
        bot_by_player: dict[int, Bot],
        level_by_player: dict[int, str],
        starting_stack: int,
        rebuy: bool = True,
        opponent_model: OpponentModel | None = None,
        hand_limit: int | None = None,
        match_logger: MatchLogger | None = None,
    ) -> None:
        self.id = session_id
        self._table = table
        self._human = human
        self._human_seat = human_seat
        self._bot_by_player = bot_by_player
        self._level_by_player = level_by_player
        self._starting_stack = starting_stack
        self._rebuy = rebuy
        self._hand_limit = hand_limit
        self._opp_model = opponent_model
        self._logger = match_logger
        self._hand_starts: dict[int, int] = {}
        # estatísticas ao vivo só no modo laboratório (sem humano)
        self._stats = WatchStats() if human_seat is None else None
        self._last_reasoning = None  # raciocínio didático da última jogada (laboratório)
        self._last: list[ActionView] = []
        self._winners: list[int] | None = None
        self._insight_by_seat: dict[int, BotInsight] = {}
        self._phase = "human_turn"
        self._begin_hand()

    def _begin_hand(self) -> None:
        if self._rebuy:  # cash game: recompra quem zerou antes de distribuir
            for p in self._table.players:
                if p.stack <= 0:
                    p.stack = self._starting_stack
        self._hand_starts = {id(p): p.stack for p in self._table.players}  # antes das blinds
        self._hand: Hand = self._table.start_hand()
        self._last = []
        self._winners = None
        self._insight_by_seat = {}
        self._last_reasoning = None
        if self._logger is not None or self._stats is not None:
            from .positions import position

            n = len(self._hand.players)
            seats = [
                {
                    "seat": i,
                    "name": p.name,
                    "level": self._level_of(p),
                    "start": self._hand_starts[id(p)],
                    "position": position(i, self._hand.button, n),
                }
                for i, p in enumerate(self._hand.players)
            ]
            if self._logger is not None:
                self._logger.begin_hand(self._table.hand_count + 1, self._hand.button, seats)
            if self._stats is not None:
                self._stats.begin_hand(seats)
        self._advance()

    def _level_of(self, p: Player) -> str:
        if self._human is not None and p is self._human:
            return "human"
        return self._level_by_player[id(p)]

    # ---------- comandos (CQRS: escrita) ----------
    def apply_human_action(self, action_type: str, amount: int = 0) -> None:
        if self._phase != "human_turn":
            raise InvalidActionError("não é a vez do humano")
        at = _TYPES.get(action_type)
        if at is None:
            raise InvalidActionError(f"ação desconhecida: {action_type!r}")
        action = Action(at, amount=amount)
        if self._opp_model is not None:  # auto-learning: aprende o estilo do humano
            self._opp_model.observe(action_type, to_call=self._hand.amount_to_call())
        self._log_action(self._hand.to_act, action, None)
        self._record(self._hand.to_act, action)
        self._hand.apply(action)  # o motor valida a legalidade
        self._advance()

    def step(self) -> None:
        """Avança uma jogada de bot (modo assistir)."""
        if self._phase != "bot_turn":
            raise InvalidActionError("não há jogada de bot pendente")
        self._play_bot(self._hand.to_act)
        self._advance()

    def next_hand(self) -> None:
        if self._phase != "hand_over":
            raise InvalidActionError("a mão atual ainda não terminou")
        self._begin_hand()

    # ---------- gestão da mesa (entrar/sair de jogadores) ----------
    def add_bot(self, level: str, name: str | None = None, buy_in: int | None = None) -> None:
        """Senta um novo bot na mesa — entra na próxima mão."""
        from .bot_factory import available_levels

        if level not in available_levels():
            raise InvalidActionError(f"nível inválido: {level!r}")
        if len(self._table.players) >= MAX_SEATS:
            raise InvalidActionError(f"a mesa está cheia (máx. {MAX_SEATS} cadeiras)")
        nm = self._unique_name(name)
        stack = buy_in if (buy_in and buy_in > 0) else self._starting_stack
        p = Player(nm, stack)
        if level == "adaptive":  # precisa da memória compartilhada
            self._bot_by_player[id(p)] = AdaptiveBot(self._opp_model, name=nm)
        else:
            self._bot_by_player[id(p)] = create_bot(level)
        self._level_by_player[id(p)] = level
        self._table.players.append(p)
        # se o jogo tinha acabado e agora há gente pra jogar, reabre pra próxima mão
        if self._phase == "game_over" and len(self._table.players_with_chips()) >= 2:
            self._phase = "hand_over"

    def remove_player(self, seat: int) -> None:
        """Remove um jogador da mesa — sai a partir da próxima mão.

        Não mexe nos mapas de bot: se ele estiver na mão em andamento, ela
        termina normalmente; a saída só vale para as próximas mãos.
        """
        players = self._table.players
        if seat < 0 or seat >= len(players):
            raise InvalidActionError("cadeira inválida")
        target = players[seat]
        if self._human is not None and target is self._human:
            raise InvalidActionError("você não pode se remover da mesa")
        if len(players) <= 2:
            raise InvalidActionError("a mesa precisa de pelo menos 2 jogadores")
        players.pop(seat)

    def _unique_name(self, name: str | None) -> str:
        taken = {p.name for p in self._table.players}
        if name and name.strip():
            base = name.strip()
            if base not in taken:
                return base
            i = 2
            while f"{base} {i}" in taken:
                i += 1
            return f"{base} {i}"
        for nm in _NAME_POOL:
            if nm not in taken:
                return nm
        i = 1
        while f"Jogador {i}" in taken:
            i += 1
        return f"Jogador {i}"

    # ---------- queries (CQRS: leitura) ----------
    def view(self) -> TableStateView:
        hand = self._hand
        return TableStateView(
            table_id=self.id,
            hand_number=self._table.hand_count + 1,
            phase=self._phase,
            board=_cards(hand.board),
            pot=hand.pot,
            seats=self._seats(),
            legal=self._legal() if self._phase == "human_turn" else None,
            last_actions=list(self._last),
            winners=self._winners,
            roster=self._roster(),
            opponent_read=self._opp_read(),
            analysis=self._analysis(),
            watch_stats=self._watch_stats_view(),
            reasoning=self._last_reasoning,
        )

    def _roster(self) -> list[RosterSeatView]:
        """Elenco atual da mesa (table.players) — base pra entrar/sair de jogadores."""
        out = []
        for i, p in enumerate(self._table.players):
            is_human = self._human is not None and p is self._human
            out.append(
                RosterSeatView(
                    seat=i,
                    name=p.name,
                    level="human" if is_human else self._level_by_player.get(id(p), "?"),
                    stack=p.stack,
                    is_human=is_human,
                )
            )
        return out

    def _watch_stats_view(self) -> WatchStatsView | None:
        """Painéis do modo laboratório — só quando há estatísticas (sem humano)."""
        st = self._stats
        if st is None or st.hands == 0:
            return None
        # só os jogadores que estão na mesa AGORA (quem saiu some dos painéis)
        current = {p.name for p in self._table.players}
        names = [n for n in st.per if n in current]

        def _bot_stat(n: str) -> BotStatView:
            p = st.per[n]
            dealt = p["hands_dealt"]
            return BotStatView(
                seat=st.info[n]["seat"],
                name=n,
                level=st.info[n]["level"],
                stack=p["stack"],
                delta=p["stack"] - p["start"],
                hands_won=p["hands_won"],
                hands_dealt=dealt,
                vpip=(p["vpip"] / dealt) if dealt else 0.0,
                aggression=(p["aggressive"] / p["actions"]) if p["actions"] else 0.0,
                pfr=(p["pfr"] / dealt) if dealt else 0.0,
                wtsd=(p["wtsd"] / p["saw_flop"]) if p["saw_flop"] else 0.0,
                wsd=(p["wsd"] / p["wtsd"]) if p["wtsd"] else 0.0,
                positions=[
                    PosStatView(
                        bucket=b,
                        hands=hands,
                        vpip=(vp / hands) if hands else 0.0,
                        pfr=(pf / hands) if hands else 0.0,
                    )
                    for b, (hands, vp, pf) in p["pos"].items()
                ],
            )

        bots = [_bot_stat(n) for n in names]
        bots.sort(key=lambda b: b.stack, reverse=True)
        series = [
            ChipSeriesView(
                seat=st.info[n]["seat"],
                name=n,
                level=st.info[n]["level"],
                # None nas mãos antes do jogador entrar (linha começa onde ele entra)
                points=[t["stacks"].get(n) for t in st.timeline],
            )
            for n in names
        ]
        return WatchStatsView(
            bots=bots,
            series=series,
            hands=st.hands,
            showdowns=st.showdowns,
            biggest_pot=st.biggest_pot,
            biggest_pot_winner=st.biggest_pot_winner,
        )

    def _analysis(self):
        """Análise completa da jogada do humano (todos os painéis), só no turno dele."""
        if (
            self._phase != "human_turn"
            or self._human_seat is None
            or self._opp_model is None
        ):
            return None
        from .analysis import analyze
        from .bot_factory import available_levels

        try:
            return analyze(self._hand, self._human_seat, self._opp_model, available_levels())
        except Exception:
            _log.exception("falha ao calcular a análise da jogada do humano")
            return None

    def _opp_read(self) -> OpponentReadView | None:
        if self._opp_model is None:
            return None
        r = self._opp_model.read()
        return OpponentReadView(
            r.fold_to_bet,
            r.aggression,
            r.samples,
            tilt=self._opp_model.tilt,
            tilt_delta=round(self._opp_model.tilt_delta, 2),
        )

    def total_chips(self) -> int:
        """Invariante de conservação (todas as fichas, inclusive no pote)."""
        in_pot = self._hand.pot if self._phase in _ACTIVE else 0
        return sum(p.stack for p in self._table.players) + in_pot

    # ---------- orquestração interna ----------
    def _advance(self) -> None:
        hand = self._hand
        while True:
            while not hand.round_complete():
                seat = hand.to_act
                if self._human_seat is not None and seat == self._human_seat:
                    self._phase = "human_turn"
                    return
                if self._human_seat is None:  # modo assistir: pausa a cada bot
                    self._phase = "bot_turn"
                    return
                self._play_bot(seat)  # modo jogar: bots jogam sozinhos
            contesting = [p for p in hand.players if p.status != PlayerStatus.FOLDED]
            if len(contesting) <= 1 or len(hand.board) >= 5:
                self._finish_hand()
                return
            hand.advance_street()

    def _play_bot(self, seat: int) -> None:
        hand = self._hand
        bot = self._bot_by_player[id(hand.players[seat])]
        obs = observation_for(hand)
        action = bot.act(obs)
        ins: BotInsight | None = None
        if isinstance(bot, Explainable):  # glass-box: guarda o porquê da jogada
            ins = bot.insight()
            if ins is not None:
                self._insight_by_seat[seat] = ins
        if self._human_seat is None:  # laboratório: raciocínio didático desta jogada
            self._last_reasoning = self._build_reasoning(seat, obs, action, ins)
        self._log_action(seat, action, ins)
        self._record(seat, action)
        hand.apply(action)

    def _build_reasoning(self, seat: int, obs, action: Action, ins: BotInsight | None):
        p = self._hand.players[seat]
        try:
            from .reasoning import explain

            return explain(p.name, self._level_of(p), obs, action, ins)
        except Exception:
            _log.exception("falha ao montar o raciocínio didático do bot")
            return None

    def _log_action(self, seat: int, action: Action, ins: BotInsight | None) -> None:
        p = self._hand.players[seat]
        street = _STREET.get(len(self._hand.board), str(len(self._hand.board)))
        if self._stats is not None:
            self._stats.action(p.name, action.type.value, street)
        if self._logger is not None:
            self._logger.action(
                seat,
                p.name,
                self._level_of(p),
                action.type.value,
                action.amount,
                street,
                _cards(self._hand.board),
                _insight_dict(ins),
            )

    def _finish_hand(self) -> None:
        pot = self._hand.pot  # antes de distribuir
        winners = self._hand.resolve()
        self._winners = [self._hand.players.index(w) for w in winners]
        if self._logger is not None or self._stats is not None:
            contesting = [p for p in self._hand.players if p.status != PlayerStatus.FOLDED]
            showdown = len(self._hand.board) >= 5 and len(contesting) >= 2
            winners_info = [
                {"seat": self._hand.players.index(w), "name": w.name} for w in winners
            ]
            result = [
                {
                    "seat": i,
                    "name": p.name,
                    "end": p.stack,
                    "delta": p.stack - self._hand_starts.get(id(p), p.stack),
                }
                for i, p in enumerate(self._hand.players)
            ]
            if self._logger is not None:
                self._logger.finish_hand(_cards(self._hand.board), pot, winners_info, result)
            if self._stats is not None:
                self._stats.finish_hand(
                    winners_info, pot, result, showdown, contenders=[p.name for p in contesting]
                )
        # detector de tilt: informa ao modelo do oponente o resultado do humano em bb
        if self._opp_model is not None and self._human is not None:
            delta = self._human.stack - self._hand_starts.get(id(self._human), self._human.stack)
            self._opp_model.note_hand_result(delta / max(self._table.bb, 1))
        self._table.end_hand()
        human_broke = self._human is not None and self._human.stack <= 0
        tournament_over = not self._rebuy and (self._table.is_over() or human_broke)
        limit_reached = (
            self._hand_limit is not None and self._table.hand_count >= self._hand_limit
        )
        if tournament_over or limit_reached:
            # fim de jogo: campeão = quem tem mais fichas
            top = max(p.stack for p in self._hand.players)
            self._winners = [i for i, p in enumerate(self._hand.players) if p.stack == top]
            self._phase = "game_over"
        else:
            self._phase = "hand_over"

    def _record(self, seat: int, action: Action) -> None:
        self._last.append(
            ActionView(seat=seat, type=action.type.value, amount=action.amount)
        )
        self._last = self._last[-_MAX_LOG:]

    def _legal(self) -> LegalView:
        hand = self._hand
        me = hand.players[hand.to_act]
        return LegalView(
            actions=sorted(a.value for a in hand.legal_actions()),
            to_call=hand.amount_to_call(),
            min_raise_to=hand.min_raise_to(),
            max_raise_to=me.current_bet + me.stack,
        )

    def _seats(self) -> list[SeatView]:
        from .positions import position

        hand = self._hand
        watch = self._human_seat is None
        showdown = self._phase in ("hand_over", "game_over")
        n = len(hand.players)
        seats: list[SeatView] = []
        for i, p in enumerate(hand.players):
            is_human = self._human is not None and p is self._human
            show = is_human or watch or (showdown and p.status != PlayerStatus.FOLDED)
            kind = "human" if is_human else "bot:" + self._level_by_player[id(p)]
            seats.append(
                SeatView(
                    seat=i,
                    name=p.name,
                    kind=kind,
                    stack=p.stack,
                    current_bet=p.current_bet,
                    status=p.status.value,
                    is_button=(i == hand.button),
                    is_turn=(self._phase in _ACTIVE and i == hand.to_act),
                    cards=_cards(p.hole) if (show and p.hole) else None,
                    position=position(i, hand.button, n),
                    insight=self._insight_view(self._insight_by_seat.get(i)),
                )
            )
        return seats

    @staticmethod
    def _insight_view(ins: BotInsight | None) -> InsightView | None:
        if ins is None:
            return None
        return InsightView(
            kind=ins.kind,
            label=ins.label,
            confidence=ins.confidence,
            probs=list(ins.probs) if ins.probs is not None else None,
            fold_to_bet=ins.fold_to_bet,
            bias=ins.bias,
        )


def build_session(
    config: SessionConfig,
    *,
    session_id: str | None = None,
    seed: int | None = None,
) -> GameSession:
    """Monta jogadores, bots, mesa e a sessão (composição da aplicação)."""
    sid = session_id or uuid.uuid4().hex[:8]
    players: list[Player] = []
    bot_by_player: dict[int, Bot] = {}
    level_by_player: dict[int, str] = {}

    human: Player | None = None
    human_seat: int | None = None
    if config.mode == "play":
        human = Player(config.human_name, config.starting_stack)
        players.append(human)
        human_seat = 0

    opp_model = OpponentModel()  # memória compartilhada: aprende o estilo do humano
    for i, spec in enumerate(config.bots):
        p = Player(spec.name, config.starting_stack)
        players.append(p)
        bot_seed = None if seed is None else seed + i + 1
        if spec.level == "adaptive":  # precisa da memória -> não passa pela factory
            bot_by_player[id(p)] = AdaptiveBot(opp_model, name=spec.name, seed=bot_seed)
        else:
            bot_by_player[id(p)] = create_bot(spec.level, seed=bot_seed)
        level_by_player[id(p)] = spec.level

    table = Table(players, config.small_blind, config.big_blind, seed=seed)
    logger = MatchLogger(
        sid,
        {
            "mode": config.mode,
            "levels": [spec.level for spec in config.bots],
            "starting_stack": config.starting_stack,
            "sb": config.small_blind,
            "bb": config.big_blind,
            "human": config.human_name if config.mode == "play" else None,
        },
    )
    return GameSession(
        sid,
        table,
        human,
        human_seat,
        bot_by_player,
        level_by_player,
        starting_stack=config.starting_stack,
        rebuy=config.rebuy,
        opponent_model=opp_model,
        hand_limit=config.hand_limit,
        match_logger=logger,
    )

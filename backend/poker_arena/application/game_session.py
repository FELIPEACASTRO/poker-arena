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
import random
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from functools import wraps
from types import ModuleType
from typing import Any, TypeVar, cast

from ..bots.adaptive_bot import AdaptiveBot
from ..bots.base import Bot, Explainable
from ..bots.insight import BotInsight
from ..bots.observation import Observation, observation_for
from ..bots.opponent_model import OpponentModel
from ..engine.actions import Action, ActionType
from ..engine.cards import Card
from ..engine.game import Hand
from ..engine.player import Player, PlayerStatus
from ..engine.table import Table
from .bot_factory import create_bot
from .match_log import MatchLogCheckpoint, MatchLogger
from .views import (
    ActionView,
    BotStatView,
    ChipSeriesView,
    InsightView,
    LegalView,
    OpponentReadView,
    PosStatView,
    ReasoningView,
    RosterSeatView,
    SeatView,
    TableStateView,
    WatchStatsView,
)
from .watch_stats import WatchStats

_log = logging.getLogger(__name__)
_MAX_LOG = 12
_MAX_IDEMPOTENCY_KEYS = 256
_MAX_IDEMPOTENCY_TOMBSTONES = 4096
_ACTIVE = ("human_turn", "bot_turn")
_TYPES: dict[str, ActionType] = {
    "fold": ActionType.FOLD,
    "check": ActionType.CHECK,
    "call": ActionType.CALL,
    "raise": ActionType.RAISE,
    "all_in": ActionType.ALL_IN,
}

_F = TypeVar("_F", bound=Callable[..., Any])


def _synchronized(method: _F) -> _F:
    """Serializa comandos e snapshots que pertencem à mesma sessão."""

    @wraps(method)
    def wrapped(self: GameSession, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(_F, wrapped)


class InvalidActionError(ValueError):
    """Ação inválida para o estado atual da sessão."""


class VersionConflictError(InvalidActionError):
    """The command was created against a stale session version."""


class IdempotencyConflictError(InvalidActionError):
    """An idempotency key was reused for a different command."""


class IdempotencyExpiredError(IdempotencyConflictError):
    """The effect is known, but its replay snapshot has expired."""


class SessionIntegrityError(RuntimeError):
    """A transaction could not restore its durable audit boundary safely."""


@dataclass(frozen=True)
class CommandResult:
    view: TableStateView
    version: int
    replayed: bool


@dataclass(frozen=True)
class _CachedCommand:
    fingerprint: str
    version: int
    view: TableStateView


@dataclass(frozen=True)
class _BotCheckpoint:
    bot: object
    original_keys: frozenset[str]
    values: dict[str, Any]
    opponent_model_refs: frozenset[str]


@dataclass(frozen=True)
class _SessionCheckpoint:
    table: Table
    hand: Hand
    human: Player | None
    bot_by_player: dict[int, Bot]
    level_by_player: dict[int, str]
    player_id_by_player: dict[int, str]
    hand_starts: dict[int, int]
    version: int
    phase: str
    last: list[ActionView]
    winners: list[int] | None
    insight_by_seat: dict[int, BotInsight]
    last_reasoning: ReasoningView | None
    showdown_revealed: bool
    stats: WatchStats | None
    opponent_model_state: dict[str, Any]
    bot_states: tuple[_BotCheckpoint, ...]
    logger_checkpoint: MatchLogCheckpoint | None
    integrity_failure: str | None


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
    out: dict[str, object] = {
        "kind": ins.kind,
        "label": ins.label,
        "confidence": round(ins.confidence, 3),
    }
    if ins.probs is not None:
        out["probs"] = list(ins.probs)
    if ins.fold_to_bet is not None:
        out["fold_to_bet"] = ins.fold_to_bet
    if ins.bias is not None:
        out["bias"] = ins.bias
    return out


MAX_SEATS = 9  # mesa até 9 jogadores (9-max)
_NAME_POOL = (
    "Ana",
    "Beto",
    "Cleo",
    "Duda",
    "Edu",
    "Fil",
    "Gabi",
    "Hugo",
    "Ivo",
    "Jana",
    "Kiko",
    "Lia",
    "Mia",
    "Nina",
    "Theo",
    "Vera",
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
        self._lock = threading.RLock()
        self._version = 0
        self._commands: OrderedDict[str, _CachedCommand] = OrderedDict()
        self._command_tombstones: OrderedDict[str, str] = OrderedDict()
        self._integrity_failure: str | None = None
        self.id = session_id
        self._table = table
        self._human = human
        self._human_seat = human_seat
        self._bot_by_player = bot_by_player
        self._level_by_player = level_by_player
        self._player_id_by_player = {id(player): uuid.uuid4().hex for player in table.players}
        self._starting_stack = starting_stack
        self._rebuy = rebuy
        self._hand_limit = hand_limit
        self._opp_model = opponent_model or OpponentModel()
        self._logger = match_logger
        self._hand_starts: dict[int, int] = {}
        # estatísticas ao vivo só no modo laboratório (sem humano)
        self._stats = WatchStats() if human_seat is None else None
        self._last_reasoning: ReasoningView | None = None
        self._showdown_revealed = False
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
        self._showdown_revealed = False
        if self._logger is not None or self._stats is not None:
            from .positions import position

            n = len(self._hand.players)
            seats = [
                {
                    "seat": i,
                    "player_id": self._player_id(p),
                    "name": p.name,
                    "level": self._level_of(p),
                    "start": self._hand_starts[id(p)],
                    "position": position(i, self._hand.button, n),
                    "hole": _cards(p.hole),
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

    def _player_id(self, player: Player) -> str:
        return self._player_id_by_player[id(player)]

    # ---------- comandos (CQRS: escrita) ----------
    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def snapshot(self) -> CommandResult:
        """Return the table view and its version from one atomic read."""
        with self._lock:
            return CommandResult(
                view=deepcopy(self.view()),
                version=self._version,
                replayed=False,
            )

    def _capture_bot_states(self) -> tuple[_BotCheckpoint, ...]:
        checkpoints: list[_BotCheckpoint] = []
        seen: set[int] = set()
        for bot in self._bot_by_player.values():
            if id(bot) in seen:
                continue
            seen.add(id(bot))
            if not hasattr(bot, "__dict__"):
                continue
            state = vars(bot)
            values: dict[str, Any] = {}
            opponent_refs: set[str] = set()
            for key, value in state.items():
                if value is self._opp_model:
                    opponent_refs.add(key)
                    continue
                if isinstance(value, (random.SystemRandom, ModuleType)):
                    continue
                if key == "_session" and value.__class__.__module__.startswith("onnxruntime"):
                    # ONNX sessions are immutable runtime handles. Inference policy,
                    # RNG and the bot's last observable decision are captured separately.
                    continue
                try:
                    values[key] = deepcopy(value)
                except Exception as exc:
                    raise SessionIntegrityError(
                        f"bot field {key!r} cannot be transactionally checkpointed"
                    ) from exc
            checkpoints.append(
                _BotCheckpoint(
                    bot=bot,
                    original_keys=frozenset(state),
                    values=values,
                    opponent_model_refs=frozenset(opponent_refs),
                )
            )
        return tuple(checkpoints)

    def _checkpoint(self) -> _SessionCheckpoint:
        memo: dict[int, object] = {}
        # SystemRandom is stateless and intentionally cannot be deep-copied. Sharing
        # the entropy source is safe; seeded random.Random instances are copied exactly.
        for rng in (self._table._rng, self._hand.deck._rng):
            if isinstance(rng, random.SystemRandom):
                memo[id(rng)] = rng
        table, hand, human = deepcopy((self._table, self._hand, self._human), memo)

        cloned_player: dict[int, Player] = {}
        for original, clone in zip(self._table.players, table.players, strict=True):
            cloned_player[id(original)] = clone
        for original, clone in zip(self._hand.players, hand.players, strict=True):
            cloned_player[id(original)] = clone
        if self._human is not None and human is not None:
            cloned_player[id(self._human)] = human

        def remap_key(player_key: int) -> int:
            clone = cloned_player.get(player_key)
            return id(clone) if clone is not None else player_key

        logger_checkpoint = self._logger.checkpoint() if self._logger is not None else None
        return _SessionCheckpoint(
            table=table,
            hand=hand,
            human=human,
            bot_by_player={remap_key(key): value for key, value in self._bot_by_player.items()},
            level_by_player={
                remap_key(key): value for key, value in self._level_by_player.items()
            },
            player_id_by_player={
                remap_key(key): value for key, value in self._player_id_by_player.items()
            },
            hand_starts={remap_key(key): value for key, value in self._hand_starts.items()},
            version=self._version,
            phase=self._phase,
            last=deepcopy(self._last),
            winners=deepcopy(self._winners),
            insight_by_seat=deepcopy(self._insight_by_seat),
            last_reasoning=deepcopy(self._last_reasoning),
            showdown_revealed=self._showdown_revealed,
            stats=deepcopy(self._stats),
            opponent_model_state=deepcopy(vars(self._opp_model)),
            bot_states=self._capture_bot_states(),
            logger_checkpoint=logger_checkpoint,
            integrity_failure=self._integrity_failure,
        )

    def _restore(self, checkpoint: _SessionCheckpoint) -> None:
        self._table = checkpoint.table
        self._hand = checkpoint.hand
        self._human = checkpoint.human
        self._bot_by_player = checkpoint.bot_by_player
        self._level_by_player = checkpoint.level_by_player
        self._player_id_by_player = checkpoint.player_id_by_player
        self._hand_starts = checkpoint.hand_starts
        self._version = checkpoint.version
        self._phase = checkpoint.phase
        self._last = checkpoint.last
        self._winners = checkpoint.winners
        self._insight_by_seat = checkpoint.insight_by_seat
        self._last_reasoning = checkpoint.last_reasoning
        self._showdown_revealed = checkpoint.showdown_revealed
        self._stats = checkpoint.stats
        vars(self._opp_model).clear()
        vars(self._opp_model).update(deepcopy(checkpoint.opponent_model_state))
        for bot_checkpoint in checkpoint.bot_states:
            if not hasattr(bot_checkpoint.bot, "__dict__"):
                continue
            state = vars(bot_checkpoint.bot)
            for key in set(state) - set(bot_checkpoint.original_keys):
                del state[key]
            for key, value in bot_checkpoint.values.items():
                state[key] = deepcopy(value)
            for key in bot_checkpoint.opponent_model_refs:
                state[key] = self._opp_model
        self._integrity_failure = checkpoint.integrity_failure
        if self._logger is not None and checkpoint.logger_checkpoint is not None:
            self._logger.rollback(checkpoint.logger_checkpoint)

    def execute_once(
        self,
        *,
        command_id: str,
        fingerprint: str,
        expected_version: int | None,
        operation: Callable[[], Any],
        store_result: bool = True,
    ) -> CommandResult:
        """Run a command with optimistic versioning and bounded replay storage.

        The idempotency key is checked first, so a legitimate retry receives
        the exact original snapshot even after the session has advanced.
        """
        if not command_id.strip():
            raise ValueError("command_id cannot be empty")
        if not fingerprint:
            raise ValueError("fingerprint cannot be empty")
        with self._lock:
            if self._integrity_failure is not None:
                raise SessionIntegrityError(self._integrity_failure)
            if store_result:
                cached = self._commands.get(command_id)
                if cached is not None:
                    if cached.fingerprint != fingerprint:
                        raise IdempotencyConflictError(
                            "command_id was already used with another payload"
                        )
                    self._commands.move_to_end(command_id)
                    return CommandResult(
                        view=deepcopy(cached.view),
                        version=cached.version,
                        replayed=True,
                    )
                expired_fingerprint = self._command_tombstones.get(command_id)
                if expired_fingerprint is not None:
                    self._command_tombstones.move_to_end(command_id)
                    if expired_fingerprint != fingerprint:
                        raise IdempotencyConflictError(
                            "command_id was already used with another payload"
                        )
                    raise IdempotencyExpiredError(
                        "command_id result expired; the operation was not executed again"
                    )
            if expected_version is not None and expected_version != self._version:
                raise VersionConflictError(
                    f"expected version {expected_version}, current {self._version}"
                )

            checkpoint = self._checkpoint()
            try:
                operation()
                snapshot = deepcopy(self.view())
            except Exception:
                try:
                    self._restore(checkpoint)
                except Exception as rollback_error:
                    self._integrity_failure = (
                        "session blocked because audit rollback could not be completed"
                    )
                    raise SessionIntegrityError(self._integrity_failure) from rollback_error
                raise
            if store_result:
                self._commands[command_id] = _CachedCommand(
                    fingerprint=fingerprint,
                    version=self._version,
                    view=snapshot,
                )
                while len(self._commands) > _MAX_IDEMPOTENCY_KEYS:
                    expired_id, expired = self._commands.popitem(last=False)
                    self._command_tombstones[expired_id] = expired.fingerprint
                while len(self._command_tombstones) > _MAX_IDEMPOTENCY_TOMBSTONES:
                    self._command_tombstones.popitem(last=False)
            return CommandResult(
                view=deepcopy(snapshot),
                version=self._version,
                replayed=False,
            )

    @_synchronized
    def apply_human_action(self, action_type: str, amount: int = 0) -> None:
        if self._phase != "human_turn":
            raise InvalidActionError("não é a vez do humano")
        at = _TYPES.get(action_type)
        if at is None:
            raise InvalidActionError(f"ação desconhecida: {action_type!r}")
        action = Action(at, amount=amount)
        seat = self._hand.to_act
        player = self._hand.players[seat]
        to_call = self._hand.amount_to_call()
        aggressive = at == ActionType.RAISE or (
            at == ActionType.ALL_IN and player.current_bet + player.stack > self._hand.current_bet
        )
        self._hand.apply(action)  # valida antes de publicar efeitos observáveis
        if self._opp_model is not None:  # auto-learning: aprende o estilo do humano
            self._opp_model.observe(action_type, to_call=to_call, aggressive=aggressive)
        self._log_action(seat, action, None, aggressive=aggressive)
        self._record(seat, action)
        self._advance()
        self._version += 1

    @_synchronized
    def step(self) -> None:
        """Avança uma jogada de bot (modo assistir)."""
        if self._phase != "bot_turn":
            raise InvalidActionError("não há jogada de bot pendente")
        self._play_bot(self._hand.to_act)
        self._advance()
        self._version += 1

    @_synchronized
    def next_hand(self) -> None:
        if self._phase != "hand_over":
            raise InvalidActionError("a mão atual ainda não terminou")
        self._begin_hand()
        self._version += 1

    # ---------- gestão da mesa (entrar/sair de jogadores) ----------
    @_synchronized
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
        self._player_id_by_player[id(p)] = uuid.uuid4().hex
        self._table.players.append(p)
        # se o jogo tinha acabado e agora há gente pra jogar, reabre pra próxima mão
        if self._phase == "game_over" and len(self._table.players_with_chips()) >= 2:
            self._phase = "hand_over"
        self._version += 1

    @_synchronized
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
        button_index = self._table.button % len(players)
        button_player = players[button_index]
        if target is button_player:
            successor = next(
                (
                    players[(seat + step) % len(players)]
                    for step in range(1, len(players))
                    if players[(seat + step) % len(players)].stack > 0
                ),
                None,
            )
        else:
            successor = None
        players.pop(seat)
        if target is button_player and successor is not None:
            successor_index = players.index(successor)
            if self._phase in _ACTIVE:
                # end_hand() will still advance once after the current hand.
                self._table.button = (successor_index - 1) % len(players)
            else:
                # The previous hand already advanced; start_hand() uses this index.
                self._table.button = successor_index
        elif button_player in players:
            self._table.button = players.index(button_player)
        else:
            self._table.button %= len(players)
        self._version += 1

    def _unique_name(self, name: str | None) -> str:
        taken = {p.name.casefold() for p in self._table.players}
        if name and name.strip():
            base = name.strip()
            if base.casefold() not in taken:
                return base
            i = 2
            while f"{base} {i}".casefold() in taken:
                i += 1
            return f"{base} {i}"
        for nm in _NAME_POOL:
            if nm.casefold() not in taken:
                return nm
        i = 1
        while f"Jogador {i}".casefold() in taken:
            i += 1
        return f"Jogador {i}"

    # ---------- queries (CQRS: leitura) ----------
    @_synchronized
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
                    player_id=self._player_id(p),
                    name=p.name,
                    level="human" if is_human else self._level_by_player.get(id(p), "?"),
                    stack=p.stack,
                    is_human=is_human,
                )
            )
        return out

    def _watch_stats_view(self) -> WatchStatsView | None:
        """Painéis do modo laboratório. Aparecem ASSIM QUE a mesa é montada (já com
        todos no stack inicial), não só depois da 1ª mão — senão ficam ~20s em branco
        no começo (a 1ª mão demora por causa da pausa entre jogadas). As estatísticas
        (VPIP/agressão/corrida das fichas) preenchem conforme o jogo anda."""
        st = self._stats
        if st is None or not st.per:  # só quando a 1ª mão já foi distribuída (roster pronto)
            return None
        # só os jogadores que estão na mesa AGORA (quem saiu some dos painéis)
        current = {self._player_id(p) for p in self._table.players}
        player_ids = [player_id for player_id in st.per if player_id in current]

        def _bot_stat(player_id: str) -> BotStatView:
            p = st.per[player_id]
            info = st.info[player_id]
            dealt = p["hands_dealt"]
            return BotStatView(
                seat=info["seat"],
                player_id=player_id,
                name=info["name"],
                level=info["level"],
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

        bots = [_bot_stat(player_id) for player_id in player_ids]
        bots.sort(key=lambda b: b.stack, reverse=True)
        series = [
            ChipSeriesView(
                seat=st.info[player_id]["seat"],
                player_id=player_id,
                name=st.info[player_id]["name"],
                level=st.info[player_id]["level"],
                # None nas mãos antes do jogador entrar (linha começa onde ele entra)
                points=[t["stacks"].get(player_id) for t in st.timeline],
            )
            for player_id in player_ids
        ]
        return WatchStatsView(
            bots=bots,
            series=series,
            hands=st.hands,
            showdowns=st.showdowns,
            biggest_pot=st.biggest_pot,
            biggest_pot_winner=st.biggest_pot_winner,
            series_total_points=st.hands,
            series_start_hand=(st.hands - len(st.timeline) + 1) if st.timeline else 0,
            series_truncated=st.hands > len(st.timeline),
        )

    def _analysis(self):
        """Análise completa da jogada do humano (todos os painéis), só no turno dele."""
        if self._phase != "human_turn" or self._human_seat is None or self._opp_model is None:
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

    @_synchronized
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
        player = hand.players[seat]
        aggressive = action.type == ActionType.RAISE or (
            action.type == ActionType.ALL_IN
            and player.current_bet + player.stack > hand.current_bet
        )
        hand.apply(action)
        self._log_action(seat, action, ins, aggressive=aggressive)
        self._record(seat, action)

    def _build_reasoning(
        self, seat: int, obs: Observation, action: Action, ins: BotInsight | None
    ) -> ReasoningView | None:
        p = self._hand.players[seat]
        try:
            from .reasoning import explain

            return explain(p.name, self._level_of(p), obs, action, ins)
        except Exception:
            _log.exception("falha ao montar o raciocínio didático do bot")
            return None

    def _log_action(
        self,
        seat: int,
        action: Action,
        ins: BotInsight | None,
        *,
        aggressive: bool | None = None,
    ) -> None:
        p = self._hand.players[seat]
        street = _STREET.get(len(self._hand.board), str(len(self._hand.board)))
        if self._stats is not None:
            self._stats.action(
                self._player_id(p), action.type.value, street, aggressive=aggressive
            )
        if self._logger is not None:
            self._logger.action(
                seat,
                self._player_id(p),
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
        contesting = [p for p in self._hand.players if p.status != PlayerStatus.FOLDED]
        showdown = len(self._hand.board) >= 5 and len(contesting) >= 2
        self._showdown_revealed = showdown
        if self._logger is not None or self._stats is not None:
            winners_info = [
                {
                    "seat": self._hand.players.index(w),
                    "player_id": self._player_id(w),
                    "name": w.name,
                }
                for w in winners
            ]
            result = [
                {
                    "seat": i,
                    "player_id": self._player_id(p),
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
                    winners_info,
                    pot,
                    result,
                    showdown,
                    contenders=[self._player_id(p) for p in contesting],
                )
        # detector de tilt: informa ao modelo do oponente o resultado do humano em bb
        if self._opp_model is not None and self._human is not None:
            delta = self._human.stack - self._hand_starts.get(id(self._human), self._human.stack)
            self._opp_model.note_hand_result(delta / max(self._table.bb, 1))
        self._table.end_hand()
        human_broke = self._human is not None and self._human.stack <= 0
        tournament_over = not self._rebuy and (self._table.is_over() or human_broke)
        limit_reached = self._hand_limit is not None and self._table.hand_count >= self._hand_limit
        if tournament_over or limit_reached:
            # fim de jogo: campeão = quem tem mais fichas
            top = max(p.stack for p in self._hand.players)
            self._winners = [i for i, p in enumerate(self._hand.players) if p.stack == top]
            self._phase = "game_over"
        else:
            self._phase = "hand_over"

    def _record(self, seat: int, action: Action) -> None:
        self._last.append(ActionView(seat=seat, type=action.type.value, amount=action.amount))
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
        showdown = self._showdown_revealed
        n = len(hand.players)
        seats: list[SeatView] = []
        for i, p in enumerate(hand.players):
            is_human = self._human is not None and p is self._human
            show = is_human or watch or (showdown and p.status != PlayerStatus.FOLDED)
            kind = "human" if is_human else "bot:" + self._level_by_player[id(p)]
            seats.append(
                SeatView(
                    seat=i,
                    player_id=self._player_id(p),
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
    if config.mode not in {"play", "watch"}:
        raise ValueError("mode must be 'play' or 'watch'")
    total_seats = len(config.bots) + (1 if config.mode == "play" else 0)
    if not 2 <= total_seats <= MAX_SEATS:
        raise ValueError(f"a mesa deve ter entre 2 e {MAX_SEATS} jogadores")
    names = [spec.name.strip().casefold() for spec in config.bots]
    if config.mode == "play":
        names.append(config.human_name.strip().casefold())
    if len(names) != len(set(names)):
        raise ValueError("nomes de jogadores devem ser unicos")

    sid = session_id or uuid.uuid4().hex
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

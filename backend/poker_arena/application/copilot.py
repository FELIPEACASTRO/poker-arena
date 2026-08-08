"""Copiloto de análise e revisão — recomenda para um SPOT que você descreve.

O "copiloto" que se pediu: você diz suas cartas, o board, o pote, quanto custa
pagar, seu stack e a posição — e ele devolve a leitura explícita (equity modelada, pot
odds, EV, MDF, outs/projetos, a nut, textura, blockers, realização da equity), o
veredito de CADA jogada possível (boa/arriscada/ruim + por quê) e o conselho das 5
IAs. Tudo calculado de verdade, offline, sem tocar em site nenhum — é o mesmo motor
do painel "Sua jogada", aplicado a qualquer situação atual, hipotética ou histórica.

O componente não lê nem controla sites de poker. Seu uso autorizado é estudo e simulação
local; o histórico PHH é pós-mão e assistência em tempo real proibida por terceiros não é
um uso suportado.

Como você não vê as cartas dos oponentes, a equity usa ranges uniformes desconhecidos:
é exata somente no river heads-up e estimada por Monte Carlo nos demais estados. O
intervalo reportado cobre erro amostral, não erro de modelagem dos ranges.
"""

from __future__ import annotations

import logging
import random
import re

from ..bots.monte_carlo_bot import estimate_equity_with_uncertainty
from ..bots.observation import Observation, PublicPlayer
from ..engine.actions import Action, ActionType
from ..engine.cards import Card
from ..engine.evaluator import card_from_str
from ..position_rules import position_is_compatible
from .analysis import (
    _blockers,
    _council_bot,
    _hand_name,
    _nut,
    _outs_and_draws,
    _texture,
)
from .positions import position as position_label
from .reasoning import _ORDER, _gto_numbers, _option, _preflop_label
from .views import (
    CopilotView,
    CouncilEntryView,
    HandReviewDecisionView,
    HandReviewView,
    OptionView,
)

LOGGER = logging.getLogger(__name__)

_ACT_PT = {
    ActionType.FOLD: "Desistir",
    ActionType.CHECK: "Passar",
    ActionType.CALL: "Pagar",
    ActionType.RAISE: "Aumentar",
    ActionType.ALL_IN: "All-in",
}


class InvalidSpotError(ValueError):
    """Entrada de spot inválida (cartas repetidas, quantidade errada, etc.)."""


# Heurística local de "lateness" (0 = cedo, 1 = botão). A direção posicional é
# poker convencional; estes pesos, a taxa de 12% e os cortes não são GTO nem oficiais.
_POS_LATENESS = {
    "UTG": 0.0,
    "UTG+1": 0.12,
    "MP": 0.28,
    "LJ": 0.45,
    "HJ": 0.65,
    "CO": 0.82,
    "BTN": 1.0,
    "SB": 0.10,
    "BB": 0.25,
}
_CARD_TOKEN_RE = re.compile(r"[2-9TJQKA][SHDC]", re.IGNORECASE)


def _position_factor(position: str | None) -> float:
    """Fator de 'lateness' da posição (0.5 neutro se desconhecida)."""
    if not position:
        return 0.5
    return _POS_LATENESS.get(position.strip().upper().split()[0], 0.5)


def _parse_cards(items: list[str]) -> list[Card]:
    out: list[Card] = []
    for s in items:
        s = s.strip()
        if _CARD_TOKEN_RE.fullmatch(s) is None:
            raise InvalidSpotError(f"carta inválida: {s!r} (use ex.: As, Kd, Th, 7c)")
        try:
            out.append(card_from_str(s[0].upper() + s[1].lower()))
        except Exception as e:
            raise InvalidSpotError(f"carta inválida: {s!r} (use ex.: As, Kd, Th, 7c)") from e
    return out


def _legal_actions(
    to_call: int,
    my_stack: int,
    full_raise_cost: int,
    *,
    raise_reopened: bool = True,
    has_contesting_opponent: bool = True,
) -> frozenset[ActionType]:
    acts: set[ActionType] = set()
    if to_call > 0:
        acts.add(ActionType.FOLD)
        if my_stack > to_call:
            acts.add(ActionType.CALL)
    else:
        acts.add(ActionType.CHECK)
    # Se o aumento cheio consumir exatamente todo o stack, a ação canônica é ALL_IN.
    # RAISE fica para o caso em que ainda sobram fichas, evitando opções duplicadas.
    if has_contesting_opponent and raise_reopened and my_stack > full_raise_cost:
        acts.add(ActionType.RAISE)
    # Sem adversario com fichas, um all-in so existe como call curto. Uma aposta
    # agressiva nao pode criar fichas contestaveis contra jogadores ja all-in.
    if my_stack > 0 and (my_stack <= to_call or (has_contesting_opponent and raise_reopened)):
        acts.add(ActionType.ALL_IN)
    return frozenset(acts)


def review_spot(
    hole_cards: list[str],
    board_cards: list[str],
    pot: int,
    to_call: int,
    my_stack: int,
    num_opponents: int,
    in_position: bool,
    available_levels: list[str],
    *,
    position: str | None = None,
    big_blind: int = 20,
    samples: int = 5_000,
    max_samples: int = 20_000,
    effective_stack: int | None = None,
    hero_current_bet: int = 0,
    current_bet: int | None = None,
    min_raise_increment: int | None = None,
    table_size: int | None = None,
    raise_reopened: bool = True,
) -> CopilotView:
    """Analisa um spot descrito pelo usuário e devolve a leitura do copiloto.

    Se `position` for informada, aplica um ajuste heurístico mais apertado nas posições
    iniciais. Os pesos não são uma estratégia oficial/solvida. `in_position` alimenta
    somente a explicação qualitativa de realização; sem `position` não há ajuste
    quantitativo posicional oculto na recomendação.
    """
    hole = _parse_cards(hole_cards)
    board = _parse_cards(board_cards)
    if len(hole) != 2:
        raise InvalidSpotError("informe exatamente 2 cartas suas (ex.: As Kh)")
    if len(board) not in (0, 3, 4, 5):
        raise InvalidSpotError(
            "o board deve ter 0 (pré-flop), 3 (flop), 4 (turn) ou 5 (river) cartas"
        )
    all_cards = hole + board
    if len({str(c) for c in all_cards}) != len(all_cards):
        raise InvalidSpotError("há cartas repetidas entre a sua mão e o board")
    if pot < 0 or to_call < 0 or my_stack <= 0 or num_opponents < 1:
        raise InvalidSpotError("valores inválidos (pote/preço ≥ 0, stack > 0, ≥ 1 oponente)")

    if max_samples < samples:
        raise InvalidSpotError("max_samples precisa ser maior ou igual a samples")
    if effective_stack is not None and effective_stack < 0:
        raise InvalidSpotError("stack efetivo não pode ser negativo")
    if table_size is not None and not 2 <= table_size <= 9:
        raise InvalidSpotError("tamanho original da mesa precisa estar entre 2 e 9")
    if table_size is not None and table_size < num_opponents + 1:
        raise InvalidSpotError("mesa original não pode ter menos jogadores que os ainda ativos")
    if position and table_size is not None and not position_is_compatible(position, table_size):
        raise InvalidSpotError(
            f"posição {position!r} impossível para mesa original de {table_size} jogadores"
        )
    if hero_current_bet < 0:
        raise InvalidSpotError("aposta atual do herói não pode ser negativa")
    betting_target = to_call if current_bet is None else current_bet
    if betting_target < hero_current_bet or betting_target - hero_current_bet != to_call:
        raise InvalidSpotError("aposta atual e contribuição do herói divergem de to_call")
    raise_increment = min_raise_increment or max(to_call, big_blind)
    if raise_increment <= 0:
        raise InvalidSpotError("incremento mínimo precisa ser positivo")
    min_raise_to = betting_target + raise_increment
    full_raise_cost = min_raise_to - hero_current_bet

    n_opp = num_opponents
    factor = _position_factor(position)
    preflop_tax = 0.0
    if len(board) == 0 and position:
        preflop_tax = (1 - factor) * 0.12 * min(num_opponents, 5) / 5

    legal = _legal_actions(
        to_call,
        my_stack,
        full_raise_cost,
        raise_reopened=raise_reopened,
        has_contesting_opponent=effective_stack is None or effective_stack > 0,
    )

    # Seed fixo: o mesmo spot dá a mesma leitura. Se o IC cruza um limiar de ação,
    # aumenta a amostra uma vez; a incerteza residual continua explícita na resposta.
    estimate = estimate_equity_with_uncertainty(
        hole,
        board,
        n_opp,
        samples,
        random.Random(20260704),  # noqa: S311 - reproducible scientific review
    )
    call_cost = min(to_call, my_stack)
    pot_odds = call_cost / (pot + call_cost) if call_cost > 0 else 0.0
    decision_thresholds: list[float] = []
    aggressive_all_in = ActionType.ALL_IN in legal and my_stack > to_call
    if ActionType.RAISE in legal or aggressive_all_in:
        decision_thresholds.append(_VALUE + preflop_tax)
    if ActionType.CALL in legal or (to_call > 0 and ActionType.ALL_IN in legal):
        decision_thresholds.append(pot_odds + preflop_tax)
    if (
        estimate.method == "monte-carlo-uniform-range"
        and samples < max_samples
        and any(
            estimate.ci95_lower < threshold <= estimate.ci95_upper
            for threshold in decision_thresholds
        )
    ):
        estimate = estimate_equity_with_uncertainty(
            hole,
            board,
            n_opp,
            max_samples,
            random.Random(20260704),  # noqa: S311 - same reproducible stream at higher precision
        )
    equity = estimate.equity
    eq = round(equity * 100)
    po = round(pot_odds * 100)
    ev_call = equity * (pot + call_cost) - call_cost

    # Observação sintética (herói no assento 0). Quando o tamanho original é conhecido,
    # mantém cadeiras dobradas para que a feature posicional do Expert preserve o botão.
    observation_n = table_size or (n_opp + 1)
    button_seat = next(
        (
            candidate
            for candidate in range(observation_n)
            if position and position_label(0, candidate, observation_n) == position
        ),
        None,
    )
    players = (
        PublicPlayer(
            0,
            "Você",
            my_stack,
            hero_current_bet,
            hero_current_bet,
            "active",
            button_seat == 0,
        ),
        *(
            PublicPlayer(
                seat,
                f"Vilão {seat}",
                my_stack if seat <= n_opp else 0,
                betting_target if seat == 1 else 0,
                betting_target if seat == 1 else 0,
                "active" if seat <= n_opp else "folded",
                seat == button_seat,
            )
            for seat in range(1, observation_n)
        ),
    )
    obs = Observation(
        seat=0,
        hole=tuple(hole),
        board=tuple(board),
        pot=pot,
        to_call=to_call,
        current_bet=betting_target,
        min_raise_to=min_raise_to,
        legal_actions=legal,
        players=players,
        num_active=n_opp + 1,
    )

    # veredito de cada jogada possível (reaproveita o motor didático do laboratório)
    options: list[OptionView] = [
        _option(
            act,
            obs,
            eq,
            po,
            chosen=False,
            amount=obs.min_raise_to,
            equity_rate=equity,
            pot_odds_rate=pot_odds,
            decision_margin=preflop_tax,
        )
        for act in _ORDER
        if act in legal
    ]

    # conselho dos níveis disponíveis neste mesmo spot
    council: list[CouncilEntryView] = []
    from ..bots.opponent_model import OpponentModel  # leitura neutra (revisão, sem histórico)

    opp_model = OpponentModel()
    for lvl in ("expert", "adaptive", "montecarlo", "heuristic", "random"):
        if lvl == "expert" and ("expert" not in available_levels or button_seat is None):
            continue
        try:
            bot = _council_bot(lvl, opp_model)
            act = bot.act(obs)
            ins = bot.insight() if hasattr(bot, "insight") else None
            council.append(
                CouncilEntryView(
                    level=lvl,
                    action=_ACT_PT.get(act.type, act.type.value),
                    amount=act.amount,
                    confidence=(
                        round(ins.confidence, 3) if ins and ins.confidence is not None else None
                    ),
                )
            )
        except Exception:  # noqa: BLE001 - isolate one optional council member
            LOGGER.exception("falha ao calcular o conselho do nível %s", lvl)
            continue

    # Recomendação heurística determinística: equity uniforme + preço + ajuste posicional.
    # Não segue o voto do Expert experimental — ele é apenas uma entrada do conselho.
    rec_type, rec_amount = _recommend(obs, equity, pot_odds, legal, preflop_tax)
    recommendation_stable = not any(
        estimate.ci95_lower < threshold <= estimate.ci95_upper for threshold in decision_thresholds
    )
    mdf_pct, _alpha = _gto_numbers(obs, Action(rec_type, amount=rec_amount))
    # marca a opção recomendada como "chosen"
    options = [
        OptionView(o.action, o.label, o.verdict, o.reason, chosen=(o.action == rec_type.value))
        for o in options
    ]
    rec_label = _label_for(rec_type, obs, rec_amount)
    realization, realization_why = (
        ("alta", "você fecha a ação (em posição): decide vendo o que os outros fizeram")
        if in_position
        else ("baixa", "você age primeiro (fora de posição): decide no escuro")
    )

    hand_label = _hand_name(hole, board) or _preflop_label(hole)
    outs, draws = _outs_and_draws(hole, board)

    return CopilotView(
        hand_label=hand_label,
        equity_pct=eq,
        equity_method=estimate.method,
        equity_trials=estimate.trials,
        equity_standard_error_pct=round(estimate.standard_error * 100, 3),
        equity_ci95_lower_pct=round(estimate.ci95_lower * 100, 2),
        equity_ci95_upper_pct=round(estimate.ci95_upper * 100, 2),
        pot=pot,
        to_call=to_call,
        call_cost=call_cost,
        pot_odds_pct=po,
        ev_call=round(ev_call, 1),
        mdf_pct=mdf_pct,
        outs=outs,
        draws=draws,
        nut=_nut(board),
        texture=_texture(board),
        blockers=_blockers(hole, board),
        spr=(
            round(
                (my_stack if effective_stack is None else min(my_stack, effective_stack)) / pot,
                1,
            )
            if pot
            else None
        ),
        realization=realization,
        realization_why=realization_why,
        options=options,
        council=council,
        recommendation=rec_type.value,
        recommendation_label=rec_label,
        recommendation_amount=(rec_amount if rec_type == ActionType.RAISE else None),
        recommendation_stable=recommendation_stable,
        decision_note=(
            "O IC95% da equity cruza um limiar da heurística; trate a ação como incerta. "
            "O EV assume checkdown, ranges uniformes e que o pote informado é só a "
            "parcela elegível ao herói; side pots não são inferidos."
            if not recommendation_stable
            else "A incerteza amostral não cruza os limiares da heurística. "
            "O EV assume checkdown, ranges uniformes e que o pote informado é só a "
            "parcela elegível ao herói; side pots não são inferidos."
        ),
        headline=_headline(
            rec_type,
            eq,
            po,
            call_cost,
            ev_call,
            all_in_is_call=(rec_type == ActionType.ALL_IN and my_stack <= to_call),
        ),
        position=(position or None),
        num_players=num_opponents + 1,
    )


_VALUE = 0.66  # equity acima disso = mão de valor (vale apostar/aumentar)


def _recommend(
    obs: Observation,
    equity: float,
    pot_odds: float,
    legal: frozenset[ActionType],
    preflop_tax: float = 0.0,
) -> tuple[ActionType, int]:
    """Heurística determinística de equity/preço + ajuste posicional local:
    equity vs preço vs limiar de valor. Nunca desiste de um pagamento lucrativo. Em
    posição cedo (tax>0), exige mais equity pra entrar/aumentar antes do flop."""
    value = _VALUE + preflop_tax  # em posição cedo, precisa de mão mais forte
    me = next(player for player in obs.players if player.seat == obs.seat)
    all_in_is_full_raise = me.current_bet + me.stack >= obs.min_raise_to
    if obs.to_call == 0:  # sem aposta: apostar por valor com mão forte, senão passar
        if equity >= value and ActionType.RAISE in legal:
            return ActionType.RAISE, obs.min_raise_to
        if equity >= value and ActionType.ALL_IN in legal and all_in_is_full_raise:
            return ActionType.ALL_IN, 0
        return ActionType.CHECK, 0
    # enfrentando aposta:
    if equity >= value and ActionType.RAISE in legal:
        return ActionType.RAISE, obs.min_raise_to  # mão forte -> aumenta por valor
    if equity >= value and ActionType.ALL_IN in legal and all_in_is_full_raise:
        return ActionType.ALL_IN, 0
    if equity >= pot_odds + preflop_tax:  # usa precisão integral, sem arredondar a decisão
        if ActionType.CALL in legal:
            return ActionType.CALL, 0
        if ActionType.ALL_IN in legal:  # stack curto: pagar equivale a all-in
            return ActionType.ALL_IN, 0
    return ActionType.FOLD, 0


def _label_for(t: ActionType, obs: Observation, amount: int) -> str:
    if t == ActionType.CALL:
        return f"Pagar {obs.to_call}"
    if t == ActionType.RAISE:
        return f"Aumentar p/ {amount}"
    if t == ActionType.ALL_IN:
        me = next(player for player in obs.players if player.seat == obs.seat)
        if obs.to_call > 0 and me.stack <= obs.to_call:
            return f"All-in para pagar {me.stack}"
    return _ACT_PT.get(t, t.value)


_STREETS = ["pré-flop", "flop", "turn", "river"]


def _cards_of(s: str) -> list[str]:
    return [s[i : i + 2] for i in range(0, len(s), 2)]


_PHH_CARD_RE = re.compile(r"[2-9TJQKA][shdc]")
_PHH_SEAT_RE = re.compile(r"p([1-9][0-9]*)")
_PHH_AMOUNT_RE = re.compile(r"(?:0|[1-9][0-9]*)")


def _invalid_phh_token(token: str, detail: str) -> InvalidSpotError:
    """Build a stable, user-facing error for malformed PHH action tokens."""
    return InvalidSpotError(f"token PHH invalido {token!r}: {detail}")


def _parse_phh_cards(token: str, compact: str, expected: int) -> list[str]:
    cards = _cards_of(compact)
    if len(compact) != expected * 2 or len(cards) != expected:
        raise _invalid_phh_token(token, f"esperava {expected} carta(s)")
    if any(_PHH_CARD_RE.fullmatch(card) is None for card in cards):
        raise _invalid_phh_token(token, "carta invalida")
    if len(set(cards)) != len(cards):
        raise _invalid_phh_token(token, "carta repetida")
    return cards


def _parse_phh_seat(token: str, value: str, player_count: int) -> int:
    match = _PHH_SEAT_RE.fullmatch(value)
    if match is None:
        raise _invalid_phh_token(token, "assento invalido")
    seat = int(match.group(1)) - 1
    if not 0 <= seat < player_count:
        raise _invalid_phh_token(token, "assento fora da mesa")
    return seat


def review_hand(phh_text: str, hero: int, available_levels: list[str]) -> HandReviewView:
    """Revisa o subconjunto PHH-NLHE inteiro suportado: reproduz as apostas e, em CADA decisão
    do herói, chama o copiloto e compara com o que ele realmente fez.

    O PHH é o texto que o próprio jogo exporta ao FIM da mão — revisar isso é estudo
    pós-jogo (como um PGN de xadrez), executado localmente. Não lê tela ao vivo."""
    import tomllib

    try:
        raw = tomllib.loads(phh_text)
    except Exception as e:
        raise InvalidSpotError(
            "não consegui ler o histórico — cole no formato PHH (ex.: as mãos do "
            f"dataset do Pluribus). Detalhe: {e}"
        ) from e
    if "actions" not in raw or "starting_stacks" not in raw:
        raise InvalidSpotError(
            "o histórico precisa ter 'actions' e 'starting_stacks' (formato PHH)"
        )
    variant = raw.get("variant")
    if variant != "NT":
        raise InvalidSpotError("este revisor aceita somente o subconjunto NLHE variant='NT'")
    required_nt = {"antes", "blinds_or_straddles", "min_bet", "starting_stacks", "actions"}
    missing_nt = sorted(required_nt - raw.keys())
    if missing_nt:
        raise InvalidSpotError(
            "histórico PHH NT incompleto: campos obrigatórios ausentes: " + ", ".join(missing_nt)
        )

    actions = raw["actions"]
    if not isinstance(actions, list) or not all(isinstance(tok, str) for tok in actions):
        raise InvalidSpotError("'actions' precisa ser uma lista de tokens PHH em texto")
    raw_starts = raw["starting_stacks"]
    if not isinstance(raw_starts, list) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in raw_starts
    ):
        raise InvalidSpotError("'starting_stacks' precisa conter somente inteiros")
    starts = list(raw_starts)
    n = len(starts)
    if not 2 <= n <= 9 or any(not 1 <= stack <= 1_000_000_000 for stack in starts):
        raise InvalidSpotError("o histórico precisa ter de 2 a 9 stacks inteiros positivos")
    if not (0 <= hero < n):
        raise InvalidSpotError(f"jogador do herói inválido (escolha 1..{n})")
    names = raw.get("players") or [f"Jogador {i + 1}" for i in range(n)]
    if (
        not isinstance(names, list)
        or len(names) != n
        or any(
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 64
            or any(ord(char) < 32 for char in name)
            for name in names
        )
    ):
        raise InvalidSpotError("'players' precisa ter o mesmo tamanho dos stacks")
    raw_blinds = raw["blinds_or_straddles"]
    if (
        not isinstance(raw_blinds, list)
        or len(raw_blinds) != n
        or any(
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000_000
            for value in raw_blinds
        )
    ):
        raise InvalidSpotError("blinds/straddles inválidos")
    # PHH atribui blinds/antes em ordem reversa no heads-up: [SB, BB] resulta
    # em p1=BB e p2=BTN/SB. Em mesas 3+, a ordem permanece p1=SB, p2=BB, ...
    blinds = list(reversed(raw_blinds)) if n == 2 else list(raw_blinds)
    raw_antes = raw["antes"]
    if (
        not isinstance(raw_antes, list)
        or len(raw_antes) != n
        or any(
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000_000
            for value in raw_antes
        )
    ):
        raise InvalidSpotError("antes inválidos")
    antes = list(reversed(raw_antes)) if n == 2 else list(raw_antes)
    # Obrigações PHH são nominais. Um jogador curto posta somente o saldo disponível:
    # primeiro o ante, depois blind/straddle; ``min_bet`` continua nominal para raises.
    posted_antes = [min(antes[i], starts[i]) for i in range(n)]
    posted_blinds = [min(blinds[i], starts[i] - posted_antes[i]) for i in range(n)]
    raw_min_bet = raw["min_bet"]
    if (
        isinstance(raw_min_bet, bool)
        or not isinstance(raw_min_bet, int)
        or not 1 <= raw_min_bet <= 1_000_000_000
    ):
        raise InvalidSpotError("min_bet inválido")
    min_bet = raw_min_bet

    holes: dict[int, list[str]] = {}
    cur = list(posted_blinds)  # aposta efetiva da rua; antes não contam para o call
    committed = [posted_antes[i] + cur[i] for i in range(n)]
    street_max = max(cur) if cur else 0
    board: list[str] = []
    folded = [False] * n
    street = 0
    decisions: list[HandReviewDecisionView] = []
    known_cards: set[str] = set()
    acted: set[int] = set()
    last_full_raise = min_bet
    last_bet_faced = [0] * n
    dealt_hole_seats: set[int] = set()
    shown_seats: set[int] = set()
    player_action_seen = False

    def next_actor(after: int) -> int | None:
        for offset in range(1, n + 1):
            candidate = (after + offset) % n
            if not folded[candidate] and committed[candidate] < starts[candidate]:
                return candidate
        return None

    def betting_complete() -> bool:
        contesting = [seat for seat in range(n) if not folded[seat]]
        if len(contesting) <= 1:
            return True
        active = [seat for seat in contesting if committed[seat] < starts[seat]]
        if not active:
            return True
        if len(active) == 1:
            return cur[active[0]] >= max(cur[seat] for seat in contesting)
        return all(seat in acted and cur[seat] == street_max for seat in active)

    def hero_is_in_position() -> bool:
        """Último jogador apto a agir na ordem da rua corrente."""

        anchor = (0 if n == 2 else (forced[-1] if forced else n - 1)) if street == 0 else n - 1
        action_order = [
            (anchor + offset) % n
            for offset in range(1, n + 1)
            if not folded[(anchor + offset) % n]
            and committed[(anchor + offset) % n] < starts[(anchor + offset) % n]
        ]
        return bool(action_order) and action_order[-1] == hero

    forced = [seat for seat, amount in enumerate(blinds) if amount > 0]
    expected_actor = (
        next_actor(0)
        if n == 2  # p2=BTN/SB abre pré-flop no heads-up canônico
        else next_actor(forced[-1] if forced else n - 1)
    )

    for tok in actions:
        parts = tok.split()
        if not parts:
            raise _invalid_phh_token(tok, "token vazio")
        if parts[0] == "d":
            if len(parts) < 2:
                raise _invalid_phh_token(tok, "comando do dealer incompleto")
            if parts[1] == "dh":
                if len(parts) != 4:
                    raise _invalid_phh_token(tok, "deal de hole cards malformado")
                dealt_seat = _parse_phh_seat(tok, parts[2], n)
                if player_action_seen:
                    raise _invalid_phh_token(
                        tok, "hole cards distribuidas depois do inicio das acoes"
                    )
                if dealt_seat in dealt_hole_seats:
                    raise _invalid_phh_token(tok, "hole cards distribuidas duas vezes")
                if dealt_seat != len(dealt_hole_seats):
                    raise _invalid_phh_token(
                        tok, f"deal fora da ordem; esperado p{len(dealt_hole_seats) + 1}"
                    )
                if parts[3] != "????":
                    if "?" in parts[3]:
                        raise _invalid_phh_token(tok, "hole cards parcialmente ocultas")
                    _parse_phh_cards(tok, parts[3], 2)
            elif parts[1] == "db":
                if len(parts) != 3 or len(board) not in {0, 3, 4}:
                    raise _invalid_phh_token(tok, "deal do board fora de sequencia")
                _parse_phh_cards(tok, parts[2], 3 if not board else 1)
            else:
                raise _invalid_phh_token(tok, "comando do dealer desconhecido")
        else:
            if len(parts) < 2:
                raise _invalid_phh_token(tok, "acao incompleta")
            _parse_phh_seat(tok, parts[0], n)
            verb_to_validate = parts[1]
            if verb_to_validate in {"f", "cc"}:
                if len(parts) != 2:
                    raise _invalid_phh_token(tok, "acao tem argumentos inesperados")
            elif verb_to_validate == "cbr":
                if len(parts) != 3 or _PHH_AMOUNT_RE.fullmatch(parts[2]) is None:
                    raise _invalid_phh_token(tok, "valor de aposta invalido")
                if int(parts[2]) <= 0:
                    raise _invalid_phh_token(tok, "valor de aposta deve ser positivo")
            elif verb_to_validate == "sm":
                if len(parts) not in {2, 3}:
                    raise _invalid_phh_token(tok, "showdown malformado")
                if len(parts) == 3:
                    _parse_phh_cards(tok, parts[2], 2)
            else:
                raise _invalid_phh_token(tok, "acao desconhecida")
        if parts[0] == "d":  # cartas distribuídas pelo dealer
            if parts[1] == "dh" and "?" not in parts[3]:  # hole (ignora obfuscadas)
                dealt_seat = _parse_phh_seat(tok, parts[2], n)
                dealt = _parse_phh_cards(tok, parts[3], 2)
                if any(card in known_cards for card in dealt):
                    raise _invalid_phh_token(tok, "carta ja distribuida")
                holes[dealt_seat] = dealt
                known_cards.update(dealt)
                dealt_hole_seats.add(dealt_seat)
            elif parts[1] == "dh":
                dealt_hole_seats.add(_parse_phh_seat(tok, parts[2], n))
            elif parts[1] == "db":  # board -> nova rua
                if sum(not value for value in folded) <= 1:
                    raise _invalid_phh_token(
                        tok, "board distribuido depois de a mao terminar por fold"
                    )
                if expected_actor is not None and not betting_complete():
                    raise _invalid_phh_token(tok, "board distribuído antes de fechar apostas")
                dealt = _parse_phh_cards(tok, parts[2], 3 if not board else 1)
                if any(card in known_cards for card in dealt):
                    raise _invalid_phh_token(tok, "carta ja distribuida")
                board += dealt
                known_cards.update(dealt)
                street += 1
                cur = [0] * n
                street_max = 0
                acted.clear()
                last_full_raise = min_bet
                last_bet_faced = [0] * n
                expected_actor = next_actor(n - 1)  # PHH canônico: botão é o último
            continue
        seat = _parse_phh_seat(tok, parts[0], n)
        verb = parts[1]
        if dealt_hole_seats != set(range(n)):
            raise _invalid_phh_token(tok, "acao antes de distribuir hole cards a todos os assentos")
        player_action_seen = True
        if verb == "sm":  # showdown reveal
            if folded[seat]:
                raise _invalid_phh_token(tok, "jogador que desistiu não pode mostrar no showdown")
            if seat in shown_seats:
                raise _invalid_phh_token(tok, "jogador mostrou a mão duas vezes")
            contesting = [candidate for candidate in range(n) if not folded[candidate]]
            terminal_showdown = betting_complete() and (
                len(board) == 5
                or len(contesting) <= 1
                or all(committed[candidate] >= starts[candidate] for candidate in contesting)
            )
            if not terminal_showdown:
                raise _invalid_phh_token(tok, "showdown antes do estado terminal")
            if len(parts) == 3:
                shown = _parse_phh_cards(tok, parts[2], 2)
                prior = holes.get(seat)
                if prior is not None and prior != shown:
                    raise _invalid_phh_token(tok, "showdown diverge das hole cards")
                if prior is None:
                    if any(card in known_cards for card in shown):
                        raise _invalid_phh_token(tok, "carta ja distribuida")
                    holes[seat] = shown
                    known_cards.update(shown)
            shown_seats.add(seat)
            continue
        if folded[seat]:
            raise _invalid_phh_token(tok, "jogador ja desistiu")
        if committed[seat] >= starts[seat]:
            raise _invalid_phh_token(tok, "jogador sem fichas tentou agir")
        if expected_actor is None or seat != expected_actor:
            expected = "nenhum" if expected_actor is None else f"p{expected_actor + 1}"
            raise _invalid_phh_token(tok, f"fora da ordem; esperado {expected}")
        action_reopened = seat not in acted or street_max - last_bet_faced[seat] >= last_full_raise

        # É uma decisão do HERÓI? captura o spot ANTES de aplicar a ação
        if seat == hero and not folded[hero] and hero in holes:
            to_call = max(0, street_max - cur[hero])
            active_others = sum(1 for j in range(n) if not folded[j] and j != hero)
            if active_others >= 1:
                from .positions import position as _pos_label

                hero_remaining = max(starts[hero] - committed[hero], 1)
                opponent_remaining = [
                    max(starts[j] - committed[j], 0)
                    for j in range(n)
                    if j != hero and not folded[j]
                ]
                spot = review_spot(
                    holes[hero],
                    board,
                    pot=sum(min(value, starts[hero]) for value in committed),
                    to_call=to_call,
                    my_stack=hero_remaining,
                    num_opponents=active_others,
                    in_position=hero_is_in_position(),
                    available_levels=available_levels,
                    position=_pos_label(hero, n - 1, n),  # PHH: botão é o último assento
                    effective_stack=min(hero_remaining, max(opponent_remaining)),
                    big_blind=min_bet,
                    hero_current_bet=cur[hero],
                    current_bet=street_max,
                    min_raise_increment=last_full_raise,
                    table_size=n,
                    raise_reopened=action_reopened,
                )
                remaining_before = starts[seat] - committed[seat]
                actual_amount: int | None = None
                if verb == "cc":
                    effective_call = min(to_call, remaining_before)
                    actual = (
                        "check"
                        if to_call == 0
                        else "all_in"
                        if effective_call == remaining_before
                        else "call"
                    )
                elif verb == "cbr":
                    actual = "all_in" if int(parts[2]) - cur[seat] == remaining_before else "raise"
                    if actual == "raise":
                        actual_amount = int(parts[2])
                else:
                    actual = "fold" if verb == "f" else verb
                decisions.append(
                    HandReviewDecisionView(
                        street=_STREETS[min(street, 3)],
                        board=list(board),
                        hole=holes[hero],
                        pot=spot.pot,
                        to_call=spot.to_call,
                        equity_pct=spot.equity_pct,
                        recommendation=spot.recommendation,
                        recommendation_label=spot.recommendation_label,
                        recommendation_amount=spot.recommendation_amount,
                        headline=spot.headline,
                        your_action=actual,
                        your_amount=actual_amount,
                        matched=(
                            actual == spot.recommendation
                            and (actual != "raise" or actual_amount == spot.recommendation_amount)
                        ),
                    )
                )

        # aplica a ação ao estado
        if verb == "f":
            folded[seat] = True
            acted.add(seat)
        elif verb == "cc":
            owe = min(max(0, street_max - cur[seat]), starts[seat] - committed[seat])
            cur[seat] += owe
            committed[seat] += owe
            acted.add(seat)
        elif verb == "cbr":
            if not action_reopened:
                raise _invalid_phh_token(tok, "ação não foi reaberta por aumento completo")
            if not any(
                other != seat and not folded[other] and committed[other] < starts[other]
                for other in range(n)
            ):
                raise _invalid_phh_token(tok, "nenhum adversário pode contestar a aposta")
            to = int(parts[2])
            increment = to - cur[seat]
            remaining = starts[seat] - committed[seat]
            if increment <= 0 or to <= street_max or increment > remaining:
                raise _invalid_phh_token(tok, "aposta impossivel para o estado atual")
            raise_size = to if street_max == 0 else to - street_max
            is_all_in = increment == remaining
            if raise_size < last_full_raise and not is_all_in:
                raise _invalid_phh_token(tok, "aumento abaixo do mínimo sem ser all-in")
            committed[seat] += increment
            cur[seat] = to
            street_max = to
            if raise_size >= last_full_raise:
                last_full_raise = raise_size
                acted = {seat}
            else:
                acted.add(seat)  # all-in curto não reabre a ação

        last_bet_faced[seat] = street_max
        expected_actor = None if betting_complete() else next_actor(seat)

    contesting = [seat for seat in range(n) if not folded[seat]]
    if not betting_complete():
        expected = "nenhum" if expected_actor is None else f"p{expected_actor + 1}"
        raise InvalidSpotError(
            f"historico PHH truncado: apostas ainda abertas; proximo ator esperado {expected}"
        )
    if len(contesting) > 1 and len(board) != 5:
        raise InvalidSpotError(
            "historico PHH truncado: a mao nao terminou por fold e o board final nao foi distribuido"
        )
    if hero not in holes:
        raise InvalidSpotError(
            f"não achei as SUAS cartas no histórico para {names[hero]} — confira o "
            "jogador escolhido (você só pode revisar uma mão em que veja a sua mão)"
        )
    if not decisions:
        raise InvalidSpotError("nenhuma decisão sua encontrada nessa mão (você não chegou a agir)")
    return HandReviewView(
        hero=names[hero],
        decisions=decisions,
        matched=sum(1 for d in decisions if d.matched),
        total=len(decisions),
    )


def _headline(
    t: ActionType,
    eq: int,
    po: int,
    to_call: int,
    ev: float,
    *,
    all_in_is_call: bool = False,
) -> str:
    if t == ActionType.FOLD:
        if ev >= 0:
            return (
                f"Recomendo DESISTIR pelo ajuste heurístico de contexto/posição; "
                f"a equity bruta ({eq}%) cobre o preço ({po}%) e o EV de checkdown "
                f"é +{round(ev, 1)}, portanto não é uma prova de call negativo."
            )
        return (
            f"Recomendo DESISTIR: sua chance ({eq}%) não cobre o preço ({po}%) "
            "— pagar é negativo no modelo simplificado de checkdown."
        )
    if t == ActionType.CHECK:
        return f"Recomendo PASSAR: sem aposta e mão de {eq}%, veja a próxima carta de graça."
    if t == ActionType.CALL:
        return (
            f"Recomendo PAGAR: {eq}% contra {po}% — EV simplificado de checkdown "
            f"+{round(ev, 1)} fichas."
        )
    if t == ActionType.RAISE:
        return f"Recomendo AUMENTAR: mão forte ({eq}%) — cresça o pote estando na frente (valor)."
    if all_in_is_call:
        return (
            f"Recomendo ALL-IN PARA PAGAR {to_call}: é um call curto, não uma agressão; "
            f"{eq}% cobre o preço de {po}% no modelo de checkdown."
        )
    return f"Recomendo ALL-IN: mão muito forte ({eq}%)."

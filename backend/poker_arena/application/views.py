"""DTOs de saída da aplicação — dataclasses puras (sem framework).

São o contrato que a camada de API traduz para JSON (via ACL/mappers). Manter
isto independente de Pydantic é o que mantém a aplicação desacoplada da web.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .competitive_intelligence import CompetitiveProfile


@dataclass(frozen=True)
class InsightView:
    """O raciocínio REAL da última decisão do bot (glass-box)."""

    kind: str
    label: str
    confidence: float
    probs: list[float] | None = None
    fold_to_bet: float | None = None
    bias: float | None = None


@dataclass(frozen=True)
class SeatView:
    seat: int
    player_id: str  # immutable within a session, even when seats are reindexed
    name: str
    kind: str  # "human" ou "bot:<level>"
    stack: int
    current_bet: int
    status: str
    is_button: bool
    is_turn: bool
    cards: list[str] | None  # só as do humano, ou reveladas no showdown
    position: str = ""  # sigla da posição (BTN, SB, BB, UTG, ...) relativa ao botão
    insight: InsightView | None = None  # raciocínio do bot (glass-box), se houver


@dataclass(frozen=True)
class ActionView:
    seat: int
    type: str
    amount: int


@dataclass(frozen=True)
class LegalView:
    actions: list[str]
    to_call: int
    min_raise_to: int
    max_raise_to: int


@dataclass(frozen=True)
class OpponentReadView:
    """O que o bot adaptativo já aprendeu sobre o humano (auto-learning visível)."""

    fold_to_bet: float
    aggression: float
    samples: int
    # detector didático de TILT (Palomäki et al.): agressão sobe logo após perder
    # um pote grande. tilt=True quando a diferença passa do limiar com amostra mínima.
    tilt: bool = False
    tilt_delta: float = 0.0  # agressão pós-perda − agressão de base, em [-1, 1]


@dataclass(frozen=True)
class WinProbView:
    seat: int
    prob: float  # equity modelada por showdown MC contra ranges uniformes, em [0,1]


@dataclass(frozen=True)
class CouncilEntryView:
    """O que um cérebro recomendaria pra jogada atual do humano."""

    level: str
    action: str
    amount: int
    confidence: float | None = None


@dataclass(frozen=True)
class HumanAnalysisView:
    """Análise completa da jogada do humano (todos os painéis), calculada de verdade."""

    equity: float
    equity_method: str
    equity_trials: int
    equity_standard_error: float
    equity_ci95_lower: float
    equity_ci95_upper: float
    recommendation_stable: bool
    equity_note: str
    win_probs: list[WinProbView]
    hand_name: str | None
    outs: int
    draws: list[str]
    pot_odds: float
    call_cost: int  # custo efetivo do call, limitado ao stack
    ev_call: float  # EV simplificado, assumindo checkdown sem apostas futuras
    nut: str | None
    texture: str | None
    spr: float | None
    position: str
    council: list[CouncilEntryView]
    best_action: str | None
    best_amount: int | None
    confidence: float | None
    your_profile_fold: float
    your_profile_aggr: float
    your_profile_samples: int
    # GTO: MDF = frequência mínima de defesa diante da aposta atual (None sem aposta)
    mdf: float | None = None
    # Equity Realization (qualitativa): quanto da equity você tende a realizar
    realization: str | None = None  # "alta" | "média" | "baixa"
    realization_why: str | None = None
    # cartas suas que bloqueiam as mãos mais fortes possíveis do vilão
    blockers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RosterSeatView:
    """Uma cadeira do elenco atual da mesa (para entrar/sair de jogadores)."""

    seat: int  # índice na mesa (table.players)
    player_id: str
    name: str
    level: str  # "human" ou o nível do bot
    stack: int
    is_human: bool


@dataclass(frozen=True)
class OptionView:
    """Uma jogada possível avaliada de forma didática (boa/arriscada/ruim e por quê)."""

    action: str  # fold | check | call | raise | all_in
    label: str  # ex.: "Pagar 40", "Aumentar", "Desistir"
    verdict: str  # "good" | "ok" | "bad"
    reason: str  # explicação em português simples
    chosen: bool  # foi a jogada que o bot realmente escolheu


@dataclass(frozen=True)
class ReasoningView:
    """Como o bot que acabou de jogar está 'pensando' — o card didático do laboratório."""

    seat: int
    name: str
    level: str
    action: str  # tipo da jogada escolhida
    headline: str  # ex.: "Sofia vai PAGAR"
    how_it_thinks: str  # 1 frase ensinando o paradigma daquele cérebro
    signal_label: str | None  # o número que o próprio bot usou (ex.: "Equity 37%")
    signal_value: float | None  # [0,1] para a barra
    hand_label: str | None  # melhor mão atual / cartas (ex.: "Par de Reis", "A-K")
    equity_pct: int  # equity modelada por simulação, 0..100
    pot: int
    to_call: int  # quanto custa pagar
    pot_odds_pct: int  # preço relativo (pot odds), 0..100
    options: list[OptionView]  # as jogadas possíveis avaliadas
    why_chosen: str  # por que ESTE cérebro escolheu ESTA jogada
    # GTO (didático): MDF de quem enfrenta a aposta atual; α = fold equity que a
    # aposta/aumento DESTE bot precisa pra lucrar como blefe puro. None quando n/a.
    mdf_pct: int | None = None
    bluff_alpha_pct: int | None = None


@dataclass(frozen=True)
class CopilotView:
    """A leitura do COPILOTO para um spot atual, hipotético ou histórico informado.

    É o painel 'Sua jogada' aplicado a qualquer situação que você digitar — sem
    tocar em site nenhum. A análise deste fluxo é executada localmente e inclui
    recomendação heurística; o replay PHH é a modalidade pós-mão."""

    hand_label: str | None  # melhor mão atual / cartas (ex.: "Par de Reis", "A-K")
    equity_pct: int  # exata no river HU; senão Monte Carlo contra ranges uniformes
    equity_method: str  # exact-river-heads-up | monte-carlo-uniform-range
    equity_trials: int
    equity_standard_error_pct: float
    equity_ci95_lower_pct: float
    equity_ci95_upper_pct: float
    pot: int
    to_call: int
    call_cost: int  # custo efetivo; pode ser menor que to_call quando o stack não cobre
    pot_odds_pct: int
    ev_call: float  # EV simplificado de checkdown (em fichas)
    mdf_pct: int | None
    outs: int
    draws: list[str]
    nut: str | None
    texture: str | None
    blockers: list[str]
    spr: float | None
    realization: str  # alta | média | baixa
    realization_why: str
    options: list[OptionView]  # cada jogada avaliada boa/arriscada/ruim + por quê
    council: list[CouncilEntryView]  # níveis disponíveis que responderam neste spot
    recommendation: str  # a ação recomendada (ex.: "call")
    recommendation_label: str  # ex.: "Pagar 40"
    recommendation_amount: int | None  # alvo total quando a recomendação é raise
    recommendation_stable: bool  # IC95% não cruza os limiares da heurística
    decision_note: str  # limite estatístico/modelagem em linguagem explícita
    headline: str  # resumo em linguagem simples do que fazer e por quê
    position: str | None = None  # posição na mesa (SB/BB/UTG/.../BTN), se informada
    num_players: int = 0  # participantes na mesa (você + oponentes)


@dataclass(frozen=True)
class HandReviewDecisionView:
    """Uma decisão SUA numa mão importada, avaliada pelo copiloto (resumo)."""

    street: str  # pré-flop | flop | turn | river
    board: list[str]
    hole: list[str]
    pot: int
    to_call: int
    equity_pct: int
    recommendation: str  # ação recomendada (fold/check/call/raise)
    recommendation_label: str
    recommendation_amount: int | None
    headline: str
    your_action: str  # o que você REALMENTE fez, segundo o histórico
    your_amount: int | None  # alvo total quando a ação real é raise
    matched: bool  # sua jogada bateu com a recomendação do copiloto?


@dataclass(frozen=True)
class HandReviewView:
    """Revisão de uma mão inteira: cada decisão sua vs a recomendação do copiloto."""

    hero: str
    decisions: list[HandReviewDecisionView]
    matched: int  # quantas das suas jogadas bateram com a recomendação
    total: int


@dataclass(frozen=True)
class PosStatView:
    """VPIP/PFR de um bot numa REGIÃO da mesa (cedo/meio/tarde/blinds)."""

    bucket: str  # early | middle | late | blinds
    hands: int  # mãos jogadas nessa região
    vpip: float  # [0,1]
    pfr: float  # [0,1]


@dataclass(frozen=True)
class BotStatView:
    """Estatística ao vivo de um bot no modo laboratório (definições padrão de HUD)."""

    seat: int
    player_id: str
    name: str
    level: str
    position: str
    stack: int
    delta: int  # resultado líquido: stack atual - total de buy-ins/recompras
    buy_in_total: int
    hands_won: int
    hands_dealt: int
    vpip: float  # % de mãos que entrou voluntariamente (solto x apertado)
    aggression: float  # % de ações agressivas (agressivo x passivo)
    pfr: float = 0.0  # % de mãos em que aumentou no pré-flop
    wtsd: float = 0.0  # % das mãos com flop visto em que chegou ao showdown
    wsd: float = 0.0  # % dos showdowns que venceu
    positions: list[PosStatView] = field(default_factory=list)  # VPIP/PFR por região
    competitive_profile: CompetitiveProfile | None = None


@dataclass(frozen=True)
class ChipSeriesView:
    """Série do stack de um bot ao fim de cada mão (corrida das fichas)."""

    seat: int
    player_id: str
    name: str
    level: str
    points: list[int | None]  # None nas mãos antes do jogador entrar


@dataclass(frozen=True)
class WatchStatsView:
    """Painéis do modo laboratório — comparação dos paradigmas de IA ao vivo."""

    bots: list[BotStatView]  # ordenado por fichas (desc)
    series: list[ChipSeriesView]
    hands: int
    showdowns: int
    biggest_pot: int
    biggest_pot_winner: str | None
    series_total_points: int = 0
    series_start_hand: int = 0
    series_truncated: bool = False


@dataclass(frozen=True)
class TableStateView:
    table_id: str
    hand_number: int
    phase: str  # "human_turn" | "bot_turn" | "hand_over" | "game_over"
    board: list[str]
    pot: int
    seats: list[SeatView]
    legal: LegalView | None
    last_actions: list[ActionView]
    winners: list[int] | None
    roster: list[RosterSeatView] = field(default_factory=list)
    opponent_read: OpponentReadView | None = None
    analysis: HumanAnalysisView | None = None
    watch_stats: WatchStatsView | None = None
    reasoning: ReasoningView | None = None

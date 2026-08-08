"""Schemas Pydantic — o contrato HTTP/JSON (DTOs de entrada e saída).

As descrições e exemplos abaixo alimentam o Swagger (/docs) — por isso são
detalhados e didáticos: quem lê o /docs entende o jogo inteiro sem ler o código.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

MAX_SEATS = 9
MAX_CHIPS = 1_000_000_000
MAX_HAND_LIMIT = 1_000_000
PLAYER_NAME_PATTERN = r"^[^\x00-\x1f\x7f]+$"
BotLevel = Literal["random", "heuristic", "montecarlo", "adaptive", "expert"]
TableMode = Literal["play", "watch"]
ActionName = Literal["fold", "check", "call", "raise", "all_in"]
PositionName = Literal["SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO", "BTN"]
REMOTE_VLM_SESSION_PATTERN = r"^[A-Za-z0-9_-]{20,128}$"
PLAYER_ID_PATTERN = r"^[0-9a-f]{32}$"


class StrictRequest(BaseModel):
    """Base for commands: reject typos instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ============================================================
# ENTRADA (comandos que o cliente envia)
# ============================================================
class BotSpecSchema(StrictRequest):
    """Um oponente controlado pela IA, definido por um nome e um nível."""

    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=PLAYER_NAME_PATTERN,
        description="Nome exibido do bot na mesa.",
        examples=["Luna"],
    )
    level: BotLevel = Field(
        description=(
            "Nível (paradigma) de IA do bot. Valores possíveis:\n"
            "- `random` — Iniciante: joga no chute (baseline).\n"
            "- `heuristic` — Amador: decide por regras de força de mão.\n"
            "- `montecarlo` — Intermediário: estima equity por simulação.\n"
            "- `adaptive` — Adaptativo: aprende seu estilo e explora.\n"
            "- `expert` — política neural ONNX experimental; só aparece em "
            "`GET /levels` quando um artefato contratualmente compatível está disponível."
        ),
        examples=["montecarlo"],
    )


class CreateTableRequest(StrictRequest):
    """Configuração para criar uma nova mesa (partida)."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "summary": "Você joga contra 3 bots variados (cash game)",
                    "value": {
                        "human_name": "VOCE",
                        "bots": [
                            {"name": "Luna", "level": "random"},
                            {"name": "Caio", "level": "heuristic"},
                            {"name": "Sofia", "level": "montecarlo"},
                        ],
                        "starting_stack": 1000,
                        "small_blind": 10,
                        "big_blind": 20,
                        "rebuy": True,
                        "mode": "play",
                        "hand_limit": None,
                        "seed": None,
                    },
                },
                {
                    "summary": "Modo Laboratório: só bots, torneio de 50 mãos",
                    "value": {
                        "bots": [
                            {"name": "Luna", "level": "random"},
                            {"name": "Caio", "level": "heuristic"},
                            {"name": "Sofia", "level": "montecarlo"},
                            {"name": "Rex", "level": "adaptive"},
                        ],
                        "starting_stack": 1500,
                        "small_blind": 10,
                        "big_blind": 20,
                        "rebuy": False,
                        "mode": "watch",
                        "hand_limit": 50,
                        "seed": 42,
                    },
                },
            ]
        },
    )

    human_name: str = Field(
        default="VOCE",
        min_length=1,
        max_length=64,
        pattern=PLAYER_NAME_PATTERN,
        description="Nome do jogador humano. Usado só no modo `play`.",
        examples=["VOCE"],
    )
    bots: list[BotSpecSchema] = Field(
        default_factory=list,
        max_length=MAX_SEATS,
        description=(
            "Oponentes da mesa. No modo `play` cabem de 1 a 8 bots "
            "(humano + bots = no máximo 9 assentos); em `watch`, de 2 a 9 bots."
        ),
    )
    starting_stack: StrictInt = Field(
        default=1000,
        gt=0,
        le=MAX_CHIPS,
        description="Fichas iniciais de cada jogador.",
        examples=[1000],
    )
    small_blind: StrictInt = Field(
        default=10, gt=0, le=MAX_CHIPS, description="Valor do small blind.", examples=[10]
    )
    big_blind: StrictInt = Field(
        default=20, gt=0, le=MAX_CHIPS, description="Valor do big blind.", examples=[20]
    )
    rebuy: StrictBool = Field(
        default=True,
        description=(
            "`true` = cash game: quem zera as fichas recompra automaticamente, a mesa "
            "nunca esvazia (jogo infinito). `false` = torneio: eliminação até sobrar 1."
        ),
    )
    mode: TableMode = Field(
        default="play",
        description=(
            "`play` = você joga (a API pausa em `human_turn` esperando sua jogada). "
            "`watch` = Modo Laboratório: só bots, com as cartas abertas; você avança "
            "lance a lance via `POST /step`."
        ),
        examples=["play"],
    )
    hand_limit: StrictInt | None = Field(
        default=None,
        gt=0,
        le=MAX_HAND_LIMIT,
        description="Encerra a partida após N mãos (`null` = sem limite). Vence quem tiver mais fichas.",
        examples=[None],
    )
    seed: StrictInt | None = Field(
        default=None,
        description=(
            "Semente do gerador de cartas. `null` = aleatoriedade criptográfica "
            "(imprevisível, padrão). Um número fixo torna o embaralhamento reprodutível "
            "(útil para testes/demonstração)."
        ),
        examples=[None],
    )

    @model_validator(mode="after")
    def validate_table_semantics(self) -> Self:
        minimum_bots = 1 if self.mode == "play" else 2
        maximum_bots = MAX_SEATS - (1 if self.mode == "play" else 0)
        if not minimum_bots <= len(self.bots) <= maximum_bots:
            raise ValueError(f"modo {self.mode} exige entre {minimum_bots} e {maximum_bots} bots")
        if self.small_blind >= self.big_blind:
            raise ValueError("small_blind deve ser menor que big_blind")
        names = [bot.name.casefold() for bot in self.bots]
        if self.mode == "play":
            names.append(self.human_name.casefold())
        if len(names) != len(set(names)):
            raise ValueError("nomes de jogadores devem ser únicos")
        return self


class ActionRequest(StrictRequest):
    """Uma jogada do humano no seu turno (`POST /tables/{id}/actions`)."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {"summary": "Pagar", "value": {"type": "call", "amount": 0}},
                {"summary": "Aumentar para 80 (total)", "value": {"type": "raise", "amount": 80}},
                {"summary": "Desistir", "value": {"type": "fold", "amount": 0}},
            ]
        },
    )

    type: ActionName = Field(
        description=(
            "Tipo da jogada. Valores: `fold` (desistir), `check` (passar, sem dever nada), "
            "`call` (pagar a aposta atual), `raise` (aumentar) e `all_in` (ir com tudo). "
            "Só as jogadas em `legal.actions` são válidas no momento."
        ),
        examples=["call"],
    )
    amount: StrictInt = Field(
        default=0,
        ge=0,
        le=MAX_CHIPS,
        description=(
            "Usado **só** no `raise`: é o valor TOTAL da aposta (não o incremento) e precisa "
            "estar entre `legal.min_raise_to` e `legal.max_raise_to`. Ignorado nas outras jogadas."
        ),
        examples=[0],
    )

    @model_validator(mode="after")
    def validate_amount_semantics(self) -> Self:
        if self.type == "raise" and self.amount == 0:
            raise ValueError("raise exige amount positivo")
        if self.type != "raise" and self.amount != 0:
            raise ValueError("amount deve ser zero fora de raise")
        return self


class AddPlayerRequest(StrictRequest):
    """Sentar um novo bot na mesa ao vivo (`POST /tables/{id}/players`)."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [{"value": {"level": "montecarlo", "name": "Ana", "buy_in": None}}]
        },
    )

    level: BotLevel = Field(
        description="Nível de IA do novo bot (veja os valores em `BotSpecSchema.level`).",
        examples=["montecarlo"],
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=PLAYER_NAME_PATTERN,
        description="Nome do bot. Se omitido, um nome único é gerado automaticamente.",
        examples=["Ana"],
    )
    buy_in: StrictInt | None = Field(
        default=None,
        gt=0,
        le=MAX_CHIPS,
        description="Fichas com que ele entra. Se omitido, usa o `starting_stack` da mesa.",
        examples=[None],
    )


# ============================================================
# SAÍDA (estado da mesa e análises)
# ============================================================
class InsightSchema(BaseModel):
    """O raciocínio REAL da última decisão de um bot (a 'caixa de vidro' da IA)."""

    kind: str = Field(
        description="Paradigma que gerou a decisão (random/heuristic/montecarlo/adaptive/expert)."
    )
    label: str = Field(
        description="Explicação curta e legível do porquê da jogada.",
        examples=["Equity 37% (200 simulações)"],
    )
    confidence: float = Field(description="Confiança da decisão, em [0,1].", examples=[0.37])
    probs: list[float] | None = Field(
        default=None,
        description="Expert: 5 probabilidades [desistir, pagar, ½ pote, pote, all-in].",
    )
    fold_to_bet: float | None = Field(
        default=None,
        description="Adaptativo: o quanto ele acha que você desiste diante de apostas, em [0,1].",
    )
    bias: float | None = Field(default=None, description="Adaptativo: viés de agressão aprendido.")


class SeatSchema(BaseModel):
    """Uma cadeira da mão atual (jogador + estado)."""

    seat: int = Field(description="Índice da cadeira na mão atual.")
    player_id: str = Field(
        min_length=32,
        max_length=32,
        pattern=PLAYER_ID_PATTERN,
        description="Identidade imutável do jogador nesta sessão; não muda quando cadeiras são reindexadas.",
    )
    name: str = Field(description="Nome do jogador.")
    kind: str = Field(description="`human` ou `bot:<nivel>` (ex.: `bot:montecarlo`).")
    stack: int = Field(description="Fichas atuais do jogador.")
    current_bet: int = Field(description="Fichas que ele já colocou nesta rodada de apostas.")
    status: str = Field(description="`active`, `folded` (desistiu) ou `all_in`.")
    is_button: bool = Field(description="Se está com o botão do dealer (D).")
    is_turn: bool = Field(description="Se é a vez dele agir.")
    cards: list[str] | None = Field(
        description="Cartas (ex.: `['Ah','Kd']`). Só as suas; as dos bots vêm `null`, exceto no showdown ou no modo `watch`."
    )
    position: str = Field(
        default="",
        description="Sigla da posição (BTN, SB, BB, UTG, UTG+1, MP, LJ, HJ ou CO).",
    )
    insight: InsightSchema | None = Field(
        default=None, description="Raciocínio do bot na última jogada (se houver)."
    )


class ActionSchema(BaseModel):
    """Uma ação que acabou de acontecer na mesa (para a UI animar/narrar)."""

    seat: int = Field(description="Cadeira que agiu.")
    type: str = Field(description="Tipo da ação (fold/check/call/raise/all_in).")
    amount: int = Field(description="Valor envolvido (quando aplicável).")


class LegalSchema(BaseModel):
    """As jogadas válidas para o humano AGORA (presente só no turno dele)."""

    actions: list[str] = Field(
        description="Jogadas permitidas neste momento.", examples=[["fold", "call", "raise"]]
    )
    to_call: int = Field(description="Quanto falta pagar para igualar a aposta atual.")
    min_raise_to: int = Field(description="Menor valor TOTAL para um `raise`.")
    max_raise_to: int = Field(
        description="Maior valor TOTAL para um `raise` (efetivamente um all-in)."
    )


class OpponentReadSchema(BaseModel):
    """O que o bot adaptativo já aprendeu sobre o humano (auto-learning visível)."""

    fold_to_bet: float = Field(
        description="Frequência com que você desiste diante de apostas, em [0,1]."
    )
    aggression: float = Field(description="Sua agressividade observada, em [0,1].")
    samples: int = Field(description="Quantas jogadas suas já foram observadas.")
    tilt: bool = Field(
        default=False,
        description="Detector didático de tilt: sua agressão subiu além do limiar nas mãos seguintes a uma perda grande (>=15 bb).",
    )
    tilt_delta: float = Field(
        default=0.0, description="Agressão pós-perda − agressão de base, em [-1,1]."
    )


class WinProbSchema(BaseModel):
    """Equity modelada de uma cadeira via simulação contra ranges uniformes."""

    seat: int = Field(description="Cadeira.")
    prob: float = Field(description="Equity de showdown modelada, em [0,1].")


class CouncilEntrySchema(BaseModel):
    """O que um paradigma de IA recomendaria para a SUA jogada atual (o 'conselho')."""

    level: str = Field(description="Nível de IA que deu a recomendação.")
    action: str = Field(description="Ação recomendada (em português, ex.: 'Pagar').")
    amount: int = Field(description="Valor sugerido (para aumentos).")
    confidence: float | None = Field(
        default=None, description="Confiança da recomendação, em [0,1]."
    )


class HumanAnalysisSchema(BaseModel):
    """Análise completa da SUA jogada (todos os painéis), calculada de verdade no turno do humano."""

    equity: float = Field(description="Equity modelada contra ranges uniformes, em [0,1].")
    equity_method: str = Field(description="Método numérico usado para a equity.")
    equity_trials: int = Field(ge=1, description="Número de amostras de showdown.")
    equity_standard_error: float = Field(ge=0, description="Erro-padrão amostral aproximado.")
    equity_ci95_lower: float = Field(ge=0, le=1)
    equity_ci95_upper: float = Field(ge=0, le=1)
    recommendation_stable: bool = Field(
        description="Se o IC95% não cruza as pot odds usadas no sinal pagar/desistir."
    )
    equity_note: str = Field(description="Limite amostral e de modelagem da equity.")
    win_probs: list[WinProbSchema] = Field(description="Equity modelada de cada cadeira.")
    hand_name: str | None = Field(description="Nome da sua melhor mão atual (ex.: 'Par de Reis').")
    outs: int = Field(
        description=(
            "Outs estruturais brutos de sequência/flush que usam carta privada; "
            "não descontam dominação, redraws ou range adversário."
        )
    )
    draws: list[str] = Field(description="Projetos em aberto (ex.: flush draw, straight draw).")
    pot_odds: float = Field(description="Pot odds: razão entre o que você paga e o pote, em [0,1].")
    call_cost: int = Field(ge=0, description="Custo efetivo do call, limitado ao stack.")
    ev_call: float = Field(
        description="EV simplificado do call em fichas, assumindo checkdown e sem apostas futuras."
    )
    nut: str | None = Field(description="A melhor mão possível ('the nuts') para o board atual.")
    texture: str | None = Field(description="Textura do board (ex.: 'molhado', 'seco').")
    spr: float | None = Field(description="Stack-to-Pot Ratio.")
    position: str = Field(description="Sua posição relativa (ex.: 'na ponta', 'fora de posição').")
    council: list[CouncilEntrySchema] = Field(
        description="O que cada paradigma de IA faria na sua vez."
    )
    best_action: str | None = Field(description="Melhor ação segundo o Expert.")
    best_amount: int | None = Field(description="Valor da melhor ação.")
    confidence: float | None = Field(description="Confiança do Expert na recomendação, em [0,1].")
    your_profile_fold: float = Field(description="Seu fold-to-bet observado, em [0,1].")
    your_profile_aggr: float = Field(description="Sua agressão observada, em [0,1].")
    your_profile_samples: int = Field(description="Tamanho da amostra do seu perfil.")
    mdf: float | None = Field(
        default=None,
        description="MDF (frequência mínima de defesa) diante da aposta atual, em [0,1]. `null` sem aposta a pagar. Referência teórica (heads-up/river).",
    )
    realization: str | None = Field(
        default=None,
        description="Equity Realization qualitativa: `alta` (em posição), `média` ou `baixa` (fora de posição).",
    )
    realization_why: str | None = Field(
        default=None, description="Por que a realização é essa (ordem de ação pós-flop)."
    )
    blockers: list[str] = Field(
        default=[],
        description="Cartas suas que bloqueiam as mãos mais fortes possíveis do vilão (nut flush, quadra/full).",
    )


class PosStatSchema(BaseModel):
    """VPIP/PFR de um bot numa REGIÃO da mesa (amostras agregadas)."""

    bucket: str = Field(description="`early` | `middle` | `late` | `blinds`.")
    hands: int = Field(description="Mãos jogadas nessa região.")
    vpip: float = Field(description="VPIP na região, em [0,1].")
    pfr: float = Field(description="PFR na região, em [0,1].")


class CompetitiveTendencySchema(BaseModel):
    """Uma frequência contextual com numerador, denominador e incerteza explícitos."""

    key: str
    label: str
    family: str
    context: str
    successes: int = Field(ge=0)
    opportunities: int = Field(ge=0)
    observed_rate: float | None = Field(default=None, ge=0, le=1)
    posterior_mean: float = Field(ge=0, le=1)
    interval95_low: float | None = Field(default=None, ge=0, le=1)
    interval95_high: float | None = Field(default=None, ge=0, le=1)
    evidence_fraction: float = Field(
        ge=0,
        le=1,
        description=(
            "Fração operacional min(1, oportunidades/30); não é probabilidade nem "
            "confiança estatística."
        ),
    )
    evidence: str = Field(pattern="^(insufficient|emerging|stable)$")
    ready: bool


class CompetitiveRecencySchema(BaseModel):
    """Sinal EWMA descritivo; não é teste causal nem diagnóstico psicológico."""

    actions: int = Field(ge=0)
    ewma_aggression: float | None = Field(default=None, ge=0, le=1)
    long_run_aggression: float | None = Field(default=None, ge=0, le=1)
    delta: float | None = Field(default=None, ge=-1, le=1)
    direction: str = Field(pattern="^(insufficient|stable|more_aggressive|more_passive)$")
    ready: bool


class CompetitiveProfileSchema(BaseModel):
    """Perfil contextual somente da sessão local; nunca escolhe a próxima ação."""

    version: str = Field(pattern="^ci-local-v[0-9]+$")
    scope: str = Field(pattern="^local_session_only$")
    authority: str = Field(pattern="^descriptive_only_no_action_advice$")
    posterior_method: str
    interval_method: str
    minimum_opportunities: int = Field(ge=1)
    signals: list[CompetitiveTendencySchema]
    recency: CompetitiveRecencySchema


class BotStatSchema(BaseModel):
    """Estatística ao vivo de um bot no Modo Laboratório."""

    seat: int = Field(description="Cadeira mais recente do bot.")
    player_id: str = Field(
        min_length=32,
        max_length=32,
        pattern=PLAYER_ID_PATTERN,
        description="Identidade imutável do competidor na sessão.",
    )
    name: str = Field(description="Nome do bot.")
    level: str = Field(description="Nível de IA.")
    position: PositionName = Field(description="Posição exata do competidor na mão atual.")
    stack: int = Field(description="Fichas atuais.")
    delta: int = Field(
        description="Resultado líquido: stack atual menos todos os buy-ins/recompras (fichas)."
    )
    buy_in_total: int = Field(
        ge=0, description="Capital total colocado na sessão, incluindo recompras."
    )
    hands_won: int = Field(description="Mãos vencidas.")
    hands_dealt: int = Field(description="Mãos jogadas.")
    vpip: float = Field(
        description="% de mãos que entrou voluntariamente (solto x apertado), em [0,1]."
    )
    aggression: float = Field(description="% de ações agressivas (agressivo x passivo), em [0,1].")
    pfr: float = Field(
        default=0.0,
        description="Preflop Raise: % de mãos em que aumentou no pré-flop, em [0,1]. O gap VPIP−PFR separa o agressivo do passivo.",
    )
    wtsd: float = Field(
        default=0.0,
        description="Went To ShowDown: % das mãos com flop visto em que chegou ao showdown, em [0,1].",
    )
    wsd: float = Field(
        default=0.0, description="Won at ShowDown: % dos showdowns que venceu, em [0,1]."
    )
    positions: list[PosStatSchema] = Field(
        default=[], description="VPIP/PFR por região da mesa (cedo/meio/tarde/blinds)."
    )
    competitive_profile: CompetitiveProfileSchema | None = Field(
        default=None,
        description=(
            "Inteligência competitiva contextual da sessão local, com oportunidades, "
            "suavização, incerteza e abstenção. Não contém conselho de ação."
        ),
    )


class ChipSeriesSchema(BaseModel):
    """Série do stack de um bot ao fim de cada mão (a 'corrida das fichas')."""

    seat: int = Field(description="Cadeira do bot.")
    player_id: str = Field(
        min_length=32,
        max_length=32,
        pattern=PLAYER_ID_PATTERN,
        description="Identidade imutável do competidor na sessão.",
    )
    name: str = Field(description="Nome do bot.")
    level: str = Field(description="Nível de IA.")
    points: list[int | None] = Field(
        description="Stack ao fim de cada mão. `null` nas mãos antes do bot entrar."
    )


class RosterSeatSchema(BaseModel):
    """Uma cadeira do elenco atual da mesa (base para entrar/sair de jogadores)."""

    seat: int = Field(description="Índice da cadeira na mesa.")
    player_id: str = Field(
        min_length=32,
        max_length=32,
        pattern=PLAYER_ID_PATTERN,
        description="Identidade imutável do jogador nesta sessão.",
    )
    name: str = Field(description="Nome do jogador.")
    level: str = Field(description="`human` ou o nível do bot.")
    stack: int = Field(description="Fichas atuais.")
    is_human: bool = Field(description="Se é o jogador humano (não pode ser removido).")


class WatchStatsSchema(BaseModel):
    """Painéis do Modo Laboratório — comparação dos paradigmas de IA ao vivo (só no modo `watch`)."""

    bots: list[BotStatSchema] = Field(description="Placar dos bots, ordenado por fichas.")
    series: list[ChipSeriesSchema] = Field(description="Corrida das fichas (uma série por bot).")
    hands: int = Field(description="Mãos concluídas na sessão.")
    showdowns: int = Field(description="Quantas chegaram ao showdown.")
    biggest_pot: int = Field(description="Maior pote da sessão.")
    biggest_pot_winner: str | None = Field(description="Quem levou o maior pote.")
    series_total_points: int = Field(
        default=0,
        ge=0,
        description="Total de pontos históricos produzidos; pode ser maior que a janela enviada.",
    )
    series_start_hand: int = Field(
        default=0,
        ge=0,
        description="Número da primeira mão contida na janela de séries (zero quando vazia).",
    )
    series_truncated: bool = Field(
        default=False,
        description="Verdadeiro quando a resposta contém apenas a janela recente; o log de auditoria preserva o histórico completo.",
    )


class PageSchema(BaseModel):
    """Metadados de paginação por offset para históricos potencialmente longos."""

    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    returned: int = Field(ge=0)
    total: int = Field(ge=0)
    next_offset: int | None = Field(
        default=None,
        ge=0,
        description="Offset da próxima página, ou null quando o histórico terminou.",
    )


class GameSummarySchema(BaseModel):
    id: str
    created: str | None = None
    mode: str | None = None
    levels: list[str] = Field(default_factory=list)
    hands: int = Field(default=0, ge=0)
    last: str | None = None


class GameListResponse(BaseModel):
    games: list[GameSummarySchema]
    page: PageSchema
    unreadable_logs: int = Field(
        ge=0,
        description="Logs corrompidos/inacessíveis omitidos da lista; valor >0 torna a trilha incompleta.",
    )


class GameLogPageResponse(BaseModel):
    meta: dict[str, Any]
    hands: list[dict[str, Any]]
    page: PageSchema


class OptionSchema(BaseModel):
    """Uma jogada possível avaliada de forma didática (boa/arriscada/ruim e por quê)."""

    action: str = Field(description="fold | check | call | raise | all_in.")
    label: str = Field(description="Rótulo da jogada (ex.: 'Pagar 40').")
    verdict: str = Field(description="`good` (boa), `ok` (arriscada) ou `bad` (ruim).")
    reason: str = Field(description="Explicação em português simples do porquê.")
    chosen: bool = Field(description="Se foi a jogada que o bot realmente escolheu.")


class CopilotRequest(StrictRequest):
    """Um SPOT atual, hipotético ou histórico descrito para análise local/offline."""

    hole: list[str] = Field(
        min_length=2,
        max_length=2,
        description="Suas 2 cartas (ex.: ['As','Kh']).",
    )
    board: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Cartas comunitárias: 0 (pré-flop), 3 (flop), 4 (turn) ou 5 (river).",
    )
    pot: StrictInt = Field(
        ge=0,
        le=MAX_CHIPS,
        description=(
            "Parcela do pote já elegível ao herói, antes do call. Exclua excesso não pago "
            "e side pots que o stack do herói não pode disputar."
        ),
    )
    to_call: StrictInt = Field(
        ge=0,
        le=MAX_CHIPS,
        default=0,
        description="Quanto custa pagar (0 se você pode passar).",
    )
    my_stack: StrictInt = Field(gt=0, le=MAX_CHIPS, description="Suas fichas.")
    effective_stack: StrictInt = Field(
        ge=0,
        le=MAX_CHIPS,
        description=(
            "Stack efetivo restante contra o oponente relevante; 0 quando todos os rivais já estão all-in."
        ),
    )
    num_opponents: StrictInt = Field(
        ge=1,
        le=MAX_SEATS - 1,
        default=1,
        description="Quantos oponentes ativos na mão.",
    )
    in_position: StrictBool = Field(
        default=True, description="Você age por último (em posição)? Afeta a realização da equity."
    )
    position: PositionName | None = Field(
        default=None,
        description="Posição na mesa: SB/BB/UTG/UTG+1/MP/LJ/HJ/CO/BTN.",
    )
    table_size: StrictInt = Field(
        ge=2,
        le=MAX_SEATS,
        description=(
            "Jogadores originalmente distribuídos na mão; separa posição da "
            "quantidade de oponentes que ainda estão ativos."
        ),
    )
    big_blind: StrictInt = Field(
        gt=0,
        le=MAX_CHIPS,
        default=20,
        description="Big blind (só para dimensionar o aumento mínimo).",
    )
    hero_current_bet: StrictInt = Field(
        ge=0,
        le=MAX_CHIPS,
        description="Fichas que o herói já colocou na rodada de apostas atual.",
    )
    current_bet: StrictInt = Field(
        ge=0,
        le=MAX_CHIPS,
        description="Maior aposta-alvo atual; current_bet - hero_current_bet = to_call.",
    )
    min_raise_increment: StrictInt = Field(
        gt=0,
        le=MAX_CHIPS,
        description="Tamanho do último aumento completo; define o incremento mínimo legal.",
    )
    raise_reopened: StrictBool = Field(
        description="Se a ação do herói foi reaberta por um aumento completo.",
    )

    @field_validator("board")
    @classmethod
    def validate_board_length(cls, board: list[str]) -> list[str]:
        if len(board) not in {0, 3, 4, 5}:
            raise ValueError("board deve conter 0, 3, 4 ou 5 cartas")
        return board

    @model_validator(mode="after")
    def validate_position_for_table_size(self) -> Self:
        if self.table_size < self.num_opponents + 1:
            raise ValueError("table_size não pode ser menor que os participantes ainda ativos")
        if self.position is not None:
            from poker_arena.position_rules import position_is_compatible

            if not position_is_compatible(self.position, self.table_size):
                raise ValueError("position é impossível para table_size")
        if self.current_bet < self.hero_current_bet:
            raise ValueError("current_bet não pode ser menor que hero_current_bet")
        if self.current_bet - self.hero_current_bet != self.to_call:
            raise ValueError("current_bet - hero_current_bet precisa ser igual a to_call")
        return self


class CopilotResponse(BaseModel):
    """A leitura do Copiloto: o mesmo painel 'Sua jogada' para qualquer spot."""

    hand_label: str | None = Field(
        description="Melhor mão atual ou as cartas (ex.: 'Par de Reis', 'A-K')."
    )
    equity_pct: int = Field(
        description=(
            "Equity de showdown contra ranges uniformes desconhecidos, 0..100; "
            "exata no river heads-up e estimada por Monte Carlo nos demais estados."
        )
    )
    equity_method: str = Field(description="Método: exato HU river ou Monte Carlo uniforme.")
    equity_trials: int = Field(ge=1, description="Combinações enumeradas ou amostras simuladas.")
    equity_standard_error_pct: float = Field(
        ge=0, description="Erro-padrão amostral em pontos percentuais; zero no cálculo exato."
    )
    equity_ci95_lower_pct: float = Field(ge=0, le=100)
    equity_ci95_upper_pct: float = Field(ge=0, le=100)
    pot: int
    to_call: int
    call_cost: int = Field(
        ge=0, description="Custo efetivo do call, limitado ao stack quando ele não cobre to_call."
    )
    pot_odds_pct: int = Field(description="Preço relativo (pot odds), 0..100.")
    ev_call: float = Field(
        description="EV simplificado do call em fichas, assumindo checkdown e sem apostas futuras."
    )
    mdf_pct: int | None = Field(
        description="Frequência mínima de defesa diante da aposta, 0..100. `null` sem aposta."
    )
    outs: int = Field(
        description=(
            "Outs estruturais brutos de sequência/flush; são explicativos e não "
            "substituem a equity contra ranges."
        )
    )
    draws: list[str] = Field(description="Projetos ativos (flush, sequência).")
    nut: str | None = Field(description="A melhor mão possível no board (a 'nut').")
    texture: str | None = Field(description="Textura do board (seco/molhado).")
    blockers: list[str] = Field(description="Cartas suas que bloqueiam as mãos fortes do vilão.")
    spr: float | None = Field(description="Stack-to-pot ratio.")
    realization: str = Field(
        description="Realização da equity: `alta` (em posição), `média` ou `baixa` (fora)."
    )
    realization_why: str
    options: list[OptionSchema] = Field(
        description="Cada jogada avaliada boa/arriscada/ruim + por quê."
    )
    council: list[CouncilEntrySchema] = Field(
        description="O que cada nível de IA disponível faria neste spot."
    )
    recommendation: str = Field(description="Ação recomendada (fold/check/call/raise/all_in).")
    recommendation_label: str = Field(description="Rótulo da recomendação (ex.: 'Pagar 40').")
    recommendation_amount: int | None = Field(
        description="Alvo total exato quando a recomendação é raise; nulo nas demais ações."
    )
    recommendation_stable: bool = Field(
        description="Se o IC95% amostral não cruza os limiares usados pela heurística."
    )
    decision_note: str = Field(
        description=("Nota sobre incerteza, ranges, hipótese de checkdown e elegibilidade do pote.")
    )
    headline: str = Field(description="Resumo em linguagem simples do que fazer e por quê.")
    position: str | None = Field(
        default=None, description="Posição considerada (SB/BB/UTG/.../BTN)."
    )
    num_players: int = Field(default=0, description="Participantes na mesa (você + oponentes).")


class DetectedStateSchema(BaseModel):
    """O estado que a VISÃO extraiu da imagem (antes do sanity-check)."""

    hole: list[str] = Field(description="Suas 2 cartas detectadas.")
    board: list[str] = Field(description="Cartas comunitárias detectadas.")
    pot: int | None = Field(description="Pote lido (None se não leu).")
    n_cards: int = Field(description="Quantas cartas foram localizadas.")
    confidence: float = Field(description="Confiança média da leitura, 0..1.")
    n_players: int = Field(
        default=0,
        description="Participantes detectados na mesa (0 = não detectou; cai no valor informado).",
    )
    position: str = Field(
        default="",
        description="Posição do herói derivada dos assentos + botão (BTN/SB/BB/UTG/...). Vazia se não detectou.",
    )
    player_count_confidence: float | None = Field(
        default=None, ge=0, le=1, description="Confiança crítica da contagem de assentos."
    )
    position_confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Confiança crítica da posição (assentos, botão e herói).",
    )
    stacks: dict[int, int] = Field(
        default={},
        description="Fichas lidas por assento (índice do assento -> fichas), via OCR. Vazio se o OCR não estiver disponível.",
    )
    pot_source: str = Field(
        default="template",
        description=(
            "De onde veio o pote: `ocr` (RapidOCR), `template` (leitura por moldes) "
            "ou `skipped-card-gate` quando o OCR foi evitado porque as cartas já "
            "obrigavam abstinência. A origem não é garantia de exatidão."
        ),
    )


class SanitySchema(BaseModel):
    """Resultado do sanity-check de regras de poker (a rede de segurança)."""

    ok: bool = Field(description="Se o estado passou nas regras (senão, o Copiloto ABSTÉM).")
    problems: list[str] = Field(default=[], description="Violações que causam abstenção.")
    warnings: list[str] = Field(default=[], description="Avisos (não bloqueiam).")


class FromImageResponse(BaseModel):
    """Pipeline VISÃO → estado → sanity → Copiloto: o que foi detectado e a decisão."""

    engine: str = Field(
        default="F1-template",
        description=(
            "Quem leu a imagem: `F2-onnx` (somente artefato aprovado por "
            "manifesto/hash/governança), `F1-template` (baseline local) ou `F3-vlm` "
            "(proposta remota experimental). O F3 mantém confiança zero e não autoriza "
            "decisão sem futura calibração independente."
        ),
    )
    detected: DetectedStateSchema
    sanity: SanitySchema
    decision: CopilotResponse | None = Field(
        description="A decisão do Copiloto (null se o sanity-check abstém)."
    )


class RemoteVlmConsentCreateRequest(StrictRequest):
    """Explicit opt-in for one ephemeral remote-fallback capture session."""

    consent: Literal[True] = Field(description="Must be true; the API never infers remote consent.")


class RemoteVlmConsentSessionResponse(BaseModel):
    """Server-issued capability kept only in process memory."""

    session_id: str = Field(
        min_length=20,
        max_length=128,
        pattern=REMOTE_VLM_SESSION_PATTERN,
        description="Opaque nonce; never persist it or place it in a URL.",
    )
    expires_in_seconds: int = Field(
        ge=1,
        le=3600,
        description="Maximum remaining lifetime of the server authorization.",
    )


class RemoteVlmConsentRevokeRequest(StrictRequest):
    """Revoke a capability without exposing it in a path or query string."""

    session_id: str = Field(
        min_length=20,
        max_length=128,
        pattern=REMOTE_VLM_SESSION_PATTERN,
    )


class RemoteVlmConsentRevokeResponse(BaseModel):
    revoked: bool = Field(description="Whether an active session was found and revoked.")


class HandReviewRequest(StrictRequest):
    """Histórico no subconjunto PHH-NLHE inteiro aceito pelo revisor local."""

    phh: str = Field(
        min_length=1,
        max_length=1_000_000,
        description=(
            "Histórico PHH variant='NT' completo até um estado terminal, com antes, "
            "blinds_or_straddles, min_bet, starting_stacks e actions explícitos. PHH "
            "permite fragmentos, mas este produto os recusa para não emitir revisão parcial "
            "com aparência de mão inteira. Não é um parser universal do padrão PHH."
        ),
    )
    player: StrictInt = Field(
        default=1,
        ge=1,
        le=MAX_SEATS,
        description="Qual jogador é você (número 1..N, como no PHH: p1, p2, ...).",
    )


class HandReviewDecisionSchema(BaseModel):
    """Uma decisão sua na mão, avaliada pelo copiloto."""

    street: str = Field(description="pré-flop | flop | turn | river.")
    board: list[str] = Field(description="Board naquele momento.")
    hole: list[str] = Field(description="Suas cartas.")
    pot: int
    to_call: int
    equity_pct: int
    recommendation: str = Field(description="Ação recomendada (fold/check/call/raise).")
    recommendation_label: str
    recommendation_amount: int | None = Field(
        description="Alvo total exato quando a recomendação é raise."
    )
    headline: str
    your_action: str = Field(description="O que você REALMENTE fez, segundo o histórico.")
    your_amount: int | None = Field(description="Alvo total da sua ação quando ela foi raise.")
    matched: bool = Field(
        description="A categoria e, para raise, o alvo total bateram exatamente com a recomendação?"
    )


class HandReviewResponse(BaseModel):
    """Revisão da mão inteira: cada decisão sua vs a recomendação do copiloto."""

    hero: str = Field(description="Nome do jogador revisado.")
    decisions: list[HandReviewDecisionSchema]
    matched: int = Field(description="Quantas das suas jogadas bateram com a recomendação.")
    total: int = Field(description="Total de decisões suas na mão.")


class ReasoningSchema(BaseModel):
    """Como o bot que acabou de jogar está pensando — o card didático (modo `watch`)."""

    seat: int = Field(description="Cadeira do bot que jogou.")
    name: str = Field(description="Nome do bot.")
    level: str = Field(description="Nível de IA.")
    action: str = Field(description="Jogada escolhida.")
    headline: str = Field(description="Resumo (ex.: 'Sofia vai PAGAR').")
    how_it_thinks: str = Field(description="Como aquele paradigma raciocina.")
    signal_label: str | None = Field(
        description="O número que o próprio bot usou (ex.: 'Equity 37%')."
    )
    signal_value: float | None = Field(description="Esse sinal em [0,1] (para a barra).")
    hand_label: str | None = Field(
        description="Melhor mão atual ou as cartas (ex.: 'Par de Reis')."
    )
    equity_pct: int = Field(description="Equity modelada por simulação, 0..100.")
    pot: int = Field(description="Fichas no pote.")
    to_call: int = Field(description="Quanto custa pagar.")
    pot_odds_pct: int = Field(description="Preço relativo (pot odds), 0..100.")
    options: list[OptionSchema] = Field(description="As jogadas possíveis avaliadas.")
    why_chosen: str = Field(description="Por que ESTE cérebro escolheu ESTA jogada.")
    mdf_pct: int | None = Field(
        default=None,
        description="MDF de quem enfrenta a aposta atual, 0..100 (referência teórica heads-up/river). `null` sem aposta.",
    )
    bluff_alpha_pct: int | None = Field(
        default=None,
        description="α: % de desistências que a aposta/aumento DESTE bot precisa pra lucrar como blefe puro (risco/(risco+recompensa)), 0..100. `null` quando a ação não é agressiva.",
    )


class TableStateResponse(BaseModel):
    """O estado COMPLETO da mesa — a resposta de quase todos os endpoints de mesa.

    A maioria dos campos opcionais só aparece no contexto certo: `legal` e `analysis`
    no seu turno (`play`), `watch_stats` no Modo Laboratório (`watch`).
    """

    table_id: str = Field(description="ID da mesa (use nas próximas chamadas).")
    version: int = Field(
        ge=0,
        description=(
            "Versão monotônica da sessão. Envie-a em `If-Match` nas mutações "
            "para impedir que dois comandos concorrentes sejam aplicados."
        ),
    )
    hand_number: int = Field(description="Número da mão atual (começa em 1).")
    phase: str = Field(
        description=(
            "Fase atual: `human_turn` (sua vez), `bot_turn` (vez de um bot — avance com "
            "`/step` no modo watch), `hand_over` (mão terminou — chame `/next-hand`) ou "
            "`game_over` (partida encerrada)."
        )
    )
    board: list[str] = Field(description="Cartas comunitárias (0 no pré-flop, até 5 no river).")
    pot: int = Field(description="Total de fichas no pote.")
    seats: list[SeatSchema] = Field(description="As cadeiras da mão atual.")
    legal: LegalSchema | None = Field(
        description="Jogadas válidas — presente só quando `phase == human_turn`."
    )
    last_actions: list[ActionSchema] = Field(
        description="Últimas ações da mesa (para animar a UI)."
    )
    winners: list[int] | None = Field(
        description="Cadeiras vencedoras — presente quando a mão termina."
    )
    roster: list[RosterSeatSchema] = Field(
        default=[], description="Elenco atual da mesa (para entrar/sair de jogadores)."
    )
    opponent_read: OpponentReadSchema | None = Field(
        default=None, description="O que o bot adaptativo aprendeu sobre você."
    )
    analysis: HumanAnalysisSchema | None = Field(
        default=None, description="Análise da sua jogada — presente só no seu turno."
    )
    watch_stats: WatchStatsSchema | None = Field(
        default=None, description="Estatísticas do Laboratório — presente só no modo `watch`."
    )
    reasoning: ReasoningSchema | None = Field(
        default=None,
        description="Como o bot que jogou está pensando — card didático (modo `watch`).",
    )

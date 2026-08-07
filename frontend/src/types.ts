import type { StandardPosition } from './positions'

export type Phase = 'human_turn' | 'bot_turn' | 'hand_over' | 'game_over'

export interface Insight {
  kind: string // expert | montecarlo | heuristic | adaptive | random
  label: string
  confidence: number
  probs?: number[] | null // expert: 5 probabilidades (fold/pagar/½/pote/all-in)
  fold_to_bet?: number | null // adaptive
  bias?: number | null // adaptive
}

export interface Seat {
  seat: number
  player_id: string
  name: string
  kind: string
  stack: number
  current_bet: number
  status: string
  is_button: boolean
  is_turn: boolean
  cards: string[] | null
  position?: StandardPosition
  insight?: Insight | null
}

export interface ActionLog {
  seat: number
  type: string
  amount: number
}

export interface Legal {
  actions: string[]
  to_call: number
  min_raise_to: number
  max_raise_to: number
}

export interface OpponentRead {
  fold_to_bet: number
  aggression: number
  samples: number
  tilt?: boolean // detector didático: agressão subiu após perda grande (>=15 bb)
  tilt_delta?: number // agressão pós-perda − base, em [-1,1]
}

export interface WinProb {
  seat: number
  prob: number
}

export interface CouncilEntry {
  level: string
  action: string
  amount: number
  confidence: number | null
}

export interface Analysis {
  equity: number
  win_probs: WinProb[]
  hand_name: string | null
  outs: number
  draws: string[]
  pot_odds: number
  ev_call: number
  nut: string | null
  texture: string | null
  spr: number | null
  position: StandardPosition | ''
  council: CouncilEntry[]
  best_action: string | null
  best_amount: number | null
  confidence: number | null
  your_profile_fold: number
  your_profile_aggr: number
  your_profile_samples: number
  mdf?: number | null // frequência mínima de defesa diante da aposta atual [0,1]
  realization?: string | null // equity realization qualitativa: alta | média | baixa
  realization_why?: string | null
  blockers?: string[] // cartas suas que bloqueiam as mãos mais fortes do vilão
}

// ---- painéis do modo laboratório (jogo automático) ----
export interface PosStat {
  bucket: string // early | middle | late | blinds
  hands: number
  vpip: number // 0..1
  pfr: number // 0..1
}
export interface BotStat {
  seat: number
  player_id: string
  name: string
  level: string
  stack: number
  delta: number
  hands_won: number
  hands_dealt: number
  vpip: number // 0..1 — % de mãos que entra (solto x apertado)
  aggression: number // 0..1 — % de ações agressivas (agressivo x passivo)
  pfr: number // 0..1 — % de mãos que abre aumentando (gap VPIP−PFR = passividade)
  wtsd: number // 0..1 — viu o flop e chegou ao showdown
  wsd: number // 0..1 — showdowns vencidos
  positions: PosStat[] // VPIP/PFR por região da mesa
}
export interface ChipSeries {
  seat: number
  player_id: string
  name: string
  level: string
  points: (number | null)[] // null nas mãos antes do jogador entrar
}
export interface WatchStats {
  bots: BotStat[]
  series: ChipSeries[]
  hands: number
  showdowns: number
  biggest_pot: number
  biggest_pot_winner: string | null
  series_total_points: number
  series_start_hand: number
  series_truncated: boolean
}

// ---- raciocínio didático (como o bot está pensando, modo automático) ----
export interface ReasoningOption {
  action: string
  label: string
  verdict: 'good' | 'ok' | 'bad'
  reason: string
  chosen: boolean
}
export interface Reasoning {
  seat: number
  name: string
  level: string
  action: string
  headline: string
  how_it_thinks: string
  signal_label: string | null
  signal_value: number | null
  hand_label: string | null
  equity_pct: number
  pot: number
  to_call: number
  pot_odds_pct: number
  options: ReasoningOption[]
  why_chosen: string
  mdf_pct?: number | null // MDF de quem enfrenta a aposta, 0..100
  bluff_alpha_pct?: number | null // α: folds necessários pra aposta lucrar como blefe, 0..100
}

// ---- Copiloto (revisão de spot, pós-jogo) ----
export interface CopilotRequest {
  hole: string[]
  board: string[]
  pot: number
  to_call: number
  my_stack: number
  num_opponents: number
  in_position: boolean
  position?: StandardPosition | null
  big_blind?: number
}
export interface CopilotResult {
  hand_label: string | null
  equity_pct: number
  pot: number
  to_call: number
  pot_odds_pct: number
  ev_call: number
  mdf_pct: number | null
  outs: number
  draws: string[]
  nut: string | null
  texture: string | null
  blockers: string[]
  spr: number | null
  realization: string
  realization_why: string
  options: ReasoningOption[]
  council: CouncilEntry[]
  recommendation: string
  recommendation_label: string
  headline: string
  position?: StandardPosition | null
  num_players?: number
}

// ---- Revisão de mão inteira (colar histórico PHH) ----
export interface HandReviewDecision {
  street: string
  board: string[]
  hole: string[]
  pot: number
  to_call: number
  equity_pct: number
  recommendation: string
  recommendation_label: string
  headline: string
  your_action: string
  matched: boolean
}
export interface HandReviewResult {
  hero: string
  decisions: HandReviewDecision[]
  matched: number
  total: number
}

// ---- Copiloto a partir de uma IMAGEM (visão computacional) ----
export interface FromImageResult {
  engine: string // Ex.: F3-vlm, F2-onnx ou F1-template; tratar valores novos como desconhecidos.
  detected: {
    hole: string[]
    board: string[]
    pot: number | null
    n_cards: number
    confidence: number
    n_players: number // participantes detectados na mesa (0 = não detectou)
    position: StandardPosition | ''
    stacks: Record<string, number> // fichas por assento (índice -> fichas), via OCR
    pot_source: string // 'ocr', 'template' ou 'skipped-card-gate' (abstenção precoce)
  }
  sanity: { ok: boolean; problems: string[]; warnings: string[] }
  decision: CopilotResult | null
}

export interface TableState {
  table_id: string
  version: number
  etag?: string
  replayed?: boolean
  hand_number: number
  phase: Phase
  board: string[]
  pot: number
  seats: Seat[]
  legal: Legal | null
  last_actions: ActionLog[]
  winners: number[] | null
  roster?: RosterSeat[]
  opponent_read?: OpponentRead | null
  analysis?: Analysis | null
  watch_stats?: WatchStats | null
  reasoning?: Reasoning | null
}

export interface RosterSeat {
  seat: number
  player_id: string
  name: string
  level: string // "human" ou o nível do bot
  stack: number
  is_human: boolean
}
export interface AddPlayer {
  level: string
  name?: string
  buy_in?: number | null
}

export interface BotSpec {
  name: string
  level: string
}

// ---- auditoria (logs de partida) ----
export interface GameSummary {
  id: string
  created: string | null
  mode: string | null
  levels: string[]
  hands: number
  last: string | null
}
export interface LogInsight {
  kind: string
  label: string
  confidence: number
}
export interface LogAction {
  seat: number
  player_id?: string
  name: string
  level: string
  street: string
  action: string
  amount: number
  board: string[]
  insight: LogInsight | null
}
export interface LogSeat {
  seat: number
  player_id?: string
  name: string
  level: string
  start: number
}
export interface LogResult {
  seat: number
  player_id?: string
  name: string
  end: number
  delta: number
}
export interface LogHand {
  hand: number
  ts: string
  button: number
  seats: LogSeat[]
  actions: LogAction[]
  board: string[]
  pot: number
  winners: { seat: number; player_id?: string; name: string }[]
  result: LogResult[]
}
export interface GameLog {
  meta: Record<string, unknown>
  hands: LogHand[]
  page: PageInfo
}
export interface PageInfo {
  offset: number
  limit: number
  returned: number
  total: number
  next_offset: number | null
}
export interface GameList {
  games: GameSummary[]
  page: PageInfo
}

export interface CreateConfig {
  human_name: string
  bots: BotSpec[]
  starting_stack: number
  small_blind: number
  big_blind: number
  mode?: 'play' | 'watch'
  rebuy?: boolean // true = cash game (infinito) | false = torneio (eliminação)
  hand_limit?: number | null // para após N mãos (null = sem limite)
  seed?: number | null
}

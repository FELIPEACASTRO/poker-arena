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
  name: string
  kind: string
  stack: number
  current_bet: number
  status: string
  is_button: boolean
  is_turn: boolean
  cards: string[] | null
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
  position: string
  council: CouncilEntry[]
  best_action: string | null
  best_amount: number | null
  confidence: number | null
  your_profile_fold: number
  your_profile_aggr: number
  your_profile_samples: number
}

// ---- painéis do modo laboratório (jogo automático) ----
export interface BotStat {
  seat: number
  name: string
  level: string
  stack: number
  delta: number
  hands_won: number
  hands_dealt: number
  vpip: number // 0..1 — % de mãos que entra (solto x apertado)
  aggression: number // 0..1 — % de ações agressivas (agressivo x passivo)
}
export interface ChipSeries {
  seat: number
  name: string
  level: string
  points: number[]
}
export interface WatchStats {
  bots: BotStat[]
  series: ChipSeries[]
  hands: number
  showdowns: number
  biggest_pot: number
  biggest_pot_winner: string | null
}

export interface TableState {
  table_id: string
  hand_number: number
  phase: Phase
  board: string[]
  pot: number
  seats: Seat[]
  legal: Legal | null
  last_actions: ActionLog[]
  winners: number[] | null
  opponent_read?: OpponentRead | null
  analysis?: Analysis | null
  watch_stats?: WatchStats | null
}

export interface BotSpec {
  name: string
  level: string
}

// ---- auditoria (logs de partida) ----
export interface GameSummary {
  id: string
  created: string
  mode: string
  levels: string[]
  hands: number
  last: string
}
export interface LogInsight {
  kind: string
  label: string
  confidence: number
}
export interface LogAction {
  seat: number
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
  name: string
  level: string
  start: number
}
export interface LogResult {
  seat: number
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
  winners: { seat: number; name: string }[]
  result: LogResult[]
}
export interface GameLog {
  meta: Record<string, unknown>
  hands: LogHand[]
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

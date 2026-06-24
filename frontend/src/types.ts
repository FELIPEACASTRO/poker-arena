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
}

export interface BotSpec {
  name: string
  level: string
}

export interface CreateConfig {
  human_name: string
  bots: BotSpec[]
  starting_stack: number
  small_blind: number
  big_blind: number
  mode?: 'play' | 'watch'
  seed?: number | null
}

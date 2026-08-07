import type { Seat, TableState } from '../types'

export function seat(over: Partial<Seat> = {}): Seat {
  return {
    seat: 0,
    player_id: '00000000000000000000000000000000',
    name: 'Bot',
    kind: 'bot:montecarlo',
    stack: 1000,
    current_bet: 0,
    status: 'active',
    is_button: false,
    is_turn: false,
    cards: null,
    insight: null,
    ...over,
  }
}

export function tableState(over: Partial<TableState> = {}): TableState {
  return {
    table_id: 't1',
    version: 0,
    hand_number: 1,
    phase: 'human_turn',
    board: [],
    pot: 0,
    seats: [],
    legal: null,
    last_actions: [],
    winners: null,
    opponent_read: null,
    ...over,
  }
}

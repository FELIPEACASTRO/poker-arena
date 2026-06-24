import { create } from 'zustand'
import { api } from './api'
import type { CreateConfig, TableState } from './types'

interface GameState {
  state: TableState | null
  watch: boolean
  paused: boolean
  busy: boolean
  error: string | null
  wins: Record<number, number> // vitórias por assento (cumulativo na sessão)
  handsDone: number
  lastHand: number
  stepDelay: number // ms por jogada no modo automático (controlado pelo usuário)
  setStepDelay: (ms: number) => void
  create: (cfg: CreateConfig) => Promise<void>
  act: (type: string, amount?: number) => Promise<void>
  next: () => Promise<void>
  step: () => Promise<void>
  togglePause: () => void
  leave: () => void
}

const FRESH = { wins: {} as Record<number, number>, handsDone: 0, lastHand: -1 }

export const useGame = create<GameState>((set, get) => {
  const run = async (fn: () => Promise<TableState>) => {
    set({ busy: true, error: null })
    try {
      const next = await fn()
      set((s) => {
        // conta a mão UMA vez, quando ela termina (evita contagem dupla)
        const ended = next.phase === 'hand_over' || next.phase === 'game_over'
        if (ended && next.winners?.length && next.hand_number !== s.lastHand) {
          const wins = { ...s.wins }
          for (const seat of next.winners) wins[seat] = (wins[seat] ?? 0) + 1
          return { state: next, wins, handsDone: s.handsDone + 1, lastHand: next.hand_number }
        }
        return { state: next }
      })
    } catch (e) {
      set({ error: (e as Error).message })
    } finally {
      set({ busy: false })
    }
  }
  const id = () => get().state?.table_id ?? ''

  return {
    state: null,
    watch: false,
    paused: false,
    busy: false,
    error: null,
    stepDelay: 1800, // padrão mais calmo (dá pra acompanhar e pensar)
    setStepDelay: (ms) => set({ stepDelay: ms }),
    ...FRESH,
    create: async (cfg) => {
      set({ watch: cfg.mode === 'watch', paused: false, ...FRESH })
      await run(() => api.createTable(cfg))
    },
    act: (type, amount = 0) => run(() => api.act(id(), type, amount)),
    next: () => run(() => api.nextHand(id())),
    step: () => run(() => api.step(id())),
    togglePause: () => set((s) => ({ paused: !s.paused })),
    leave: () => set({ state: null, error: null, watch: false, paused: false, ...FRESH }),
  }
})

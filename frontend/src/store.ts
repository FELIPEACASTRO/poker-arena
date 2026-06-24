import { create } from 'zustand'
import { api } from './api'
import type { CreateConfig, TableState } from './types'

interface GameState {
  state: TableState | null
  watch: boolean
  paused: boolean
  busy: boolean
  error: string | null
  create: (cfg: CreateConfig) => Promise<void>
  act: (type: string, amount?: number) => Promise<void>
  next: () => Promise<void>
  step: () => Promise<void>
  togglePause: () => void
  leave: () => void
}

export const useGame = create<GameState>((set, get) => {
  const run = async (fn: () => Promise<TableState>) => {
    set({ busy: true, error: null })
    try {
      set({ state: await fn() })
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
    create: async (cfg) => {
      set({ watch: cfg.mode === 'watch', paused: false })
      await run(() => api.createTable(cfg))
    },
    act: (type, amount = 0) => run(() => api.act(id(), type, amount)),
    next: () => run(() => api.nextHand(id())),
    step: () => run(() => api.step(id())),
    togglePause: () => set((s) => ({ paused: !s.paused })),
    leave: () => set({ state: null, error: null, watch: false, paused: false }),
  }
})

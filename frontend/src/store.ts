import { create } from 'zustand'
import { api } from './api'
import type { AddPlayer, CreateConfig, TableState } from './types'

interface GameState {
  state: TableState | null
  watch: boolean
  paused: boolean
  busy: boolean
  error: string | null
  wins: Record<number, number> // vitórias por assento (cumulativo na sessão)
  handsDone: number
  lastHand: number
  colors: Record<string, string> // cor estável por competidor (nome -> hex)
  stepDelay: number // ms por jogada no modo automático (controlado pelo usuário)
  setStepDelay: (ms: number) => void
  create: (cfg: CreateConfig) => Promise<void>
  act: (type: string, amount?: number) => Promise<void>
  next: () => Promise<void>
  step: () => Promise<void>
  addPlayer: (body: AddPlayer) => Promise<void>
  removePlayer: (seat: number) => Promise<void>
  togglePause: () => void
  leave: () => void
}

// paleta de cores por COMPETIDOR (não por nível) — distinguir cada um no gráfico
const PALETTE = [
  '#34d399', // verde
  '#60a5fa', // azul
  '#fbbf24', // dourado
  '#f472b6', // rosa
  '#c084fc', // roxo
  '#fb923c', // laranja
  '#2dd4bf', // turquesa
  '#f87171', // vermelho
  '#a3e635', // lima
  '#38bdf8', // céu
  '#e879f9', // magenta
  '#fde047', // amarelo
]

/** Cor estável por NOME: mantém a já atribuída e dá uma cor livre a cada novo
 *  jogador, garantindo que os que estão na mesa AGORA tenham cores distintas. */
function assignColors(prev: Record<string, string>, names: string[]): Record<string, string> {
  const active = [...new Set(names)]
  const next: Record<string, string> = {}
  const used = new Set<string>()
  for (const n of active) {
    if (prev[n]) {
      next[n] = prev[n]
      used.add(prev[n])
    }
  }
  for (const n of active) {
    if (next[n]) continue
    const free = PALETTE.find((c) => !used.has(c)) ?? PALETTE[active.indexOf(n) % PALETTE.length]
    next[n] = free
    used.add(free)
  }
  return next
}

const FRESH = {
  wins: {} as Record<number, number>,
  handsDone: 0,
  lastHand: -1,
  colors: {} as Record<string, string>,
}

export const useGame = create<GameState>((set, get) => {
  const run = async (fn: () => Promise<TableState>) => {
    set({ busy: true, error: null })
    try {
      const next = await fn()
      set((s) => {
        // cor estável por competidor (cobre elenco da mesa + assentos da mão)
        const names = [
          ...(next.roster ?? []).map((r) => r.name),
          ...next.seats.map((se) => se.name),
        ]
        const colors = assignColors(s.colors, names)
        // conta a mão UMA vez, quando ela termina (evita contagem dupla)
        const ended = next.phase === 'hand_over' || next.phase === 'game_over'
        if (ended && next.winners?.length && next.hand_number !== s.lastHand) {
          const wins = { ...s.wins }
          for (const seat of next.winners) wins[seat] = (wins[seat] ?? 0) + 1
          return { state: next, colors, wins, handsDone: s.handsDone + 1, lastHand: next.hand_number }
        }
        return { state: next, colors }
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
    addPlayer: (body) => run(() => api.addPlayer(id(), body)),
    removePlayer: (seat) => run(() => api.removePlayer(id(), seat)),
    togglePause: () => set((s) => ({ paused: !s.paused })),
    leave: () => set({ state: null, error: null, watch: false, paused: false, ...FRESH }),
  }
})

import { create } from 'zustand'
import { api } from './api'
import type { CommandOptions } from './api'
import { assignColors } from './colors'
import type { AddPlayer, CreateConfig, TableState } from './types'

interface GameState {
  state: TableState | null
  watch: boolean
  paused: boolean
  busy: boolean
  error: string | null
  wins: Record<string, number> // vitórias por identidade imutável do jogador
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

const FRESH = {
  wins: {} as Record<string, number>,
  handsDone: 0,
  lastHand: -1,
  colors: {} as Record<string, string>,
}

function newCommandId(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  const bytes = new Uint8Array(16)
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes)
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export const useGame = create<GameState>((set, get) => {
  let requestSequence = 0
  let activeController: AbortController | null = null

  const applyState = (next: TableState) => {
    set((s) => {
      const names = [
        ...(next.roster ?? []).map((r) => r.name),
        ...next.seats.map((seat) => seat.name),
      ]
      const colors = assignColors(s.colors, names)
      const ended = next.phase === 'hand_over' || next.phase === 'game_over'
      const winnerIds = (next.winners ?? [])
        .map((seat) => next.seats.find((candidate) => candidate.seat === seat)?.player_id)
        .filter((playerId): playerId is string => Boolean(playerId))
      if (ended && winnerIds.length && next.hand_number !== s.lastHand) {
        const wins = { ...s.wins }
        for (const playerId of winnerIds) wins[playerId] = (wins[playerId] ?? 0) + 1
        return {
          state: next,
          colors,
          wins,
          handsDone: s.handsDone + 1,
          lastHand: next.hand_number,
        }
      }
      return { state: next, colors }
    })
  }

  const isConflict = (caught: unknown): caught is Error & { status: number } =>
    caught instanceof Error && 'status' in caught && caught.status === 409

  const isRetryableNetworkFailure = (caught: unknown, signal: AbortSignal) =>
    caught instanceof TypeError && !signal.aborted

  const run = async (
    fn: (options: CommandOptions) => Promise<TableState>,
    versioned = true,
  ) => {
    const expectedVersion = versioned ? get().state?.version : undefined
    if (versioned && !Number.isInteger(expectedVersion)) {
      const failure = new Error('Versão da mesa indisponível; recarregue a sessão antes de agir.')
      set({ busy: false, error: failure.message })
      throw failure
    }
    const sequence = ++requestSequence
    activeController?.abort()
    const controller = new AbortController()
    activeController = controller
    const tableId = get().state?.table_id
    const options: CommandOptions = {
      commandId: newCommandId(),
      expectedVersion,
      signal: controller.signal,
    }
    set({ busy: true, error: null })
    try {
      let next: TableState
      try {
        next = await fn(options)
      } catch (firstFailure) {
        if (!isRetryableNetworkFailure(firstFailure, controller.signal)) throw firstFailure
        // Uma falha de transporte pode ocorrer depois de o servidor confirmar o
        // comando. Repetir UMA vez com a mesma chave torna a tentativa segura.
        next = await fn(options)
      }
      if (sequence !== requestSequence) return
      applyState(next)
    } catch (caught) {
      if (sequence !== requestSequence) return
      let failure = caught
      if (isConflict(caught) && tableId) {
        try {
          const fresh = await api.getTable(tableId, controller.signal)
          if (sequence !== requestSequence) return
          applyState(fresh)
          failure = new Error(
            `A mesa mudou antes deste comando. Estado ressincronizado na versão ${fresh.version}; revise e tente novamente.`,
          )
        } catch (resyncFailure) {
          if (sequence !== requestSequence) return
          const detail = resyncFailure instanceof Error ? resyncFailure.message : String(resyncFailure)
          failure = new Error(`${caught.message}; também falhou ao ressincronizar: ${detail}`)
        }
      }
      const message = failure instanceof Error ? failure.message : String(failure)
      set({ error: message })
      throw failure
    } finally {
      if (sequence === requestSequence) {
        activeController = null
        set({ busy: false })
      }
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
      await run((options) => api.createTable(cfg, options), false)
    },
    act: (type, amount = 0) => run((options) => api.act(id(), type, amount, options)),
    next: () => run((options) => api.nextHand(id(), options)),
    step: () => run((options) => api.step(id(), options)),
    addPlayer: (body) => run((options) => api.addPlayer(id(), body, options)),
    removePlayer: (seat) => run((options) => api.removePlayer(id(), seat, options)),
    togglePause: () => set((s) => ({ paused: !s.paused })),
    leave: () => {
      requestSequence += 1
      activeController?.abort()
      activeController = null
      set({ state: null, error: null, watch: false, paused: false, busy: false, ...FRESH })
    },
  }
})

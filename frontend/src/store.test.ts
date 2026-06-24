import { beforeEach, describe, expect, it, vi } from 'vitest'
import { tableState } from './test/factory'
import type { CreateConfig } from './types'

vi.mock('./api', () => ({
  api: {
    createTable: vi.fn(),
    nextHand: vi.fn(),
    step: vi.fn(),
    act: vi.fn(),
  },
}))

import { api } from './api'
import { useGame } from './store'

const cfg: CreateConfig = {
  human_name: 'EU',
  bots: [],
  starting_stack: 1000,
  small_blind: 10,
  big_blind: 20,
}

beforeEach(() => {
  useGame.setState({ state: null, wins: {}, handsDone: 0, lastHand: -1, busy: false, error: null })
  vi.clearAllMocks()
})

describe('store de jogo', () => {
  it('conta o vencedor uma vez quando a mão termina', async () => {
    vi.mocked(api.createTable).mockResolvedValue(
      tableState({ phase: 'hand_over', hand_number: 1, winners: [2] }),
    )
    await useGame.getState().create(cfg)
    expect(useGame.getState().wins[2]).toBe(1)
    expect(useGame.getState().handsDone).toBe(1)
  })

  it('não conta a mesma mão duas vezes', async () => {
    vi.mocked(api.createTable).mockResolvedValue(
      tableState({ phase: 'hand_over', hand_number: 1, winners: [2] }),
    )
    await useGame.getState().create(cfg)
    vi.mocked(api.step).mockResolvedValue(
      tableState({ phase: 'hand_over', hand_number: 1, winners: [2] }),
    )
    await useGame.getState().step()
    expect(useGame.getState().wins[2]).toBe(1)
    expect(useGame.getState().handsDone).toBe(1)
  })

  it('conta mãos diferentes separadamente', async () => {
    vi.mocked(api.createTable).mockResolvedValue(
      tableState({ phase: 'hand_over', hand_number: 1, winners: [0] }),
    )
    await useGame.getState().create(cfg)
    vi.mocked(api.nextHand).mockResolvedValue(
      tableState({ phase: 'hand_over', hand_number: 2, winners: [3] }),
    )
    await useGame.getState().next()
    expect(useGame.getState().handsDone).toBe(2)
    expect(useGame.getState().wins[0]).toBe(1)
    expect(useGame.getState().wins[3]).toBe(1)
  })

  it('captura erro da API sem travar (busy volta a false)', async () => {
    vi.mocked(api.createTable).mockRejectedValue(new Error('boom'))
    await useGame.getState().create(cfg)
    expect(useGame.getState().error).toBe('boom')
    expect(useGame.getState().busy).toBe(false)
  })
})

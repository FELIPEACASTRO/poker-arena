import { beforeEach, describe, expect, it, vi } from 'vitest'
import { seat, tableState } from './test/factory'
import type { CreateConfig } from './types'

vi.mock('./api', () => ({
  api: {
    createTable: vi.fn(),
    nextHand: vi.fn(),
    step: vi.fn(),
    act: vi.fn(),
    addPlayer: vi.fn(),
    removePlayer: vi.fn(),
    getTable: vi.fn(),
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

const PLAYER_A = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const PLAYER_B = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

function ended(hand: number, winnerSeat: number, playerId: string) {
  return tableState({
    phase: 'hand_over',
    hand_number: hand,
    winners: [winnerSeat],
    seats: [seat({ seat: winnerSeat, player_id: playerId })],
  })
}

beforeEach(() => {
  useGame.setState({ state: null, wins: {}, handsDone: 0, lastHand: -1, busy: false, error: null })
  vi.clearAllMocks()
})

describe('store de jogo', () => {
  it('conta o vencedor uma vez quando a mão termina', async () => {
    vi.mocked(api.createTable).mockResolvedValue(
      ended(1, 2, PLAYER_A),
    )
    await useGame.getState().create(cfg)
    expect(useGame.getState().wins[PLAYER_A]).toBe(1)
    expect(useGame.getState().handsDone).toBe(1)
  })

  it('não conta a mesma mão duas vezes', async () => {
    vi.mocked(api.createTable).mockResolvedValue(
      ended(1, 2, PLAYER_A),
    )
    await useGame.getState().create(cfg)
    vi.mocked(api.step).mockResolvedValue(
      ended(1, 2, PLAYER_A),
    )
    await useGame.getState().step()
    expect(useGame.getState().wins[PLAYER_A]).toBe(1)
    expect(useGame.getState().handsDone).toBe(1)
  })

  it('conta mãos diferentes separadamente', async () => {
    vi.mocked(api.createTable).mockResolvedValue(
      ended(1, 0, PLAYER_A),
    )
    await useGame.getState().create(cfg)
    vi.mocked(api.nextHand).mockResolvedValue(
      ended(2, 3, PLAYER_B),
    )
    await useGame.getState().next()
    expect(useGame.getState().handsDone).toBe(2)
    expect(useGame.getState().wins[PLAYER_A]).toBe(1)
    expect(useGame.getState().wins[PLAYER_B]).toBe(1)
  })

  it('captura erro da API sem travar (busy volta a false)', async () => {
    vi.mocked(api.createTable).mockRejectedValue(new Error('boom'))
    await expect(useGame.getState().create(cfg)).rejects.toThrow('boom')
    expect(useGame.getState().error).toBe('boom')
    expect(useGame.getState().busy).toBe(false)
  })

  it('ignora uma resposta antiga que chega depois da mais nova', async () => {
    let resolveFirst!: (value: ReturnType<typeof tableState>) => void
    let resolveSecond!: (value: ReturnType<typeof tableState>) => void
    vi.mocked(api.createTable)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve }))

    const first = useGame.getState().create(cfg)
    const second = useGame.getState().create(cfg)
    resolveSecond(tableState({ table_id: 'new' }))
    await second
    resolveFirst(tableState({ table_id: 'old' }))
    await first
    expect(useGame.getState().state?.table_id).toBe('new')
  })

  it('aborta e invalida a resposta pendente ao sair', async () => {
    let resolve!: (value: ReturnType<typeof tableState>) => void
    vi.mocked(api.createTable).mockImplementationOnce(
      () => new Promise((done) => { resolve = done }),
    )
    const pending = useGame.getState().create(cfg)
    useGame.getState().leave()
    resolve(tableState({ table_id: 'zumbi' }))
    await pending
    expect(useGame.getState().state).toBeNull()
  })

  it('gera UUID novo e envia a versão corrente em cada comando', async () => {
    const current = { ...tableState({ table_id: 'mesa-versionada' }), version: 5 }
    useGame.setState({ state: current })
    vi.mocked(api.act)
      .mockResolvedValueOnce({ ...current, version: 6 })
      .mockResolvedValueOnce({ ...current, version: 7 })

    await useGame.getState().act('check')
    await useGame.getState().act('check')

    const firstOptions = vi.mocked(api.act).mock.calls[0][3]
    const secondOptions = vi.mocked(api.act).mock.calls[1][3]
    expect(firstOptions).toMatchObject({ expectedVersion: 5 })
    expect(secondOptions).toMatchObject({ expectedVersion: 6 })
    expect(firstOptions.commandId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)
    expect(secondOptions.commandId).not.toBe(firstOptions.commandId)
  })

  it('repete falha de transporte uma vez com a mesma chave idempotente', async () => {
    const current = { ...tableState({ table_id: 'mesa-retry' }), version: 2 }
    useGame.setState({ state: current })
    vi.mocked(api.act)
      .mockRejectedValueOnce(new TypeError('conexão interrompida'))
      .mockResolvedValueOnce({ ...current, version: 3 })

    await useGame.getState().act('check')

    expect(api.act).toHaveBeenCalledTimes(2)
    const first = vi.mocked(api.act).mock.calls[0][3]
    const retry = vi.mocked(api.act).mock.calls[1][3]
    expect(retry.commandId).toBe(first.commandId)
    expect(retry.expectedVersion).toBe(2)
  })

  it('ressincroniza a mesa após 409 e usa a nova versão no comando seguinte', async () => {
    const current = { ...tableState({ table_id: 'mesa-conflito' }), version: 5 }
    const fresh = { ...current, version: 9 }
    useGame.setState({ state: current })
    vi.mocked(api.act).mockRejectedValueOnce(Object.assign(new Error('HTTP 409'), { status: 409 }))
    vi.mocked(api.getTable).mockResolvedValueOnce(fresh)

    await expect(useGame.getState().act('check')).rejects.toThrow('ressincronizado na versão 9')
    expect(useGame.getState().state?.version).toBe(9)

    vi.mocked(api.act).mockResolvedValueOnce({ ...fresh, version: 10 })
    await useGame.getState().act('check')
    expect(vi.mocked(api.act).mock.calls[1][3].expectedVersion).toBe(9)
  })

  it('mantém vitórias com o jogador quando sua cadeira muda', async () => {
    vi.mocked(api.createTable).mockResolvedValue(ended(1, 2, PLAYER_A))
    await useGame.getState().create(cfg)
    vi.mocked(api.nextHand).mockResolvedValue(ended(2, 0, PLAYER_A))
    await useGame.getState().next()

    expect(useGame.getState().wins[PLAYER_A]).toBe(2)
    expect(useGame.getState().handsDone).toBe(2)
  })
})

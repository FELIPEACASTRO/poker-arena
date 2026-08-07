import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import AuditPage from './AuditPage'

vi.mock('../api', () => ({ api: { listGames: vi.fn(), getGame: vi.fn() } }))

const game = { id: 'g1', created: '2026-01-01T00:00:00Z', mode: 'watch', levels: [], hands: 0, last: '' }

beforeEach(() => vi.clearAllMocks())

describe('AuditPage', () => {
  it('distingue falha de rede de histórico vazio', async () => {
    vi.mocked(api.listGames).mockRejectedValue(new Error('offline'))
    render(<AuditPage onClose={() => undefined} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(screen.queryByText(/nenhuma partida gravada/)).not.toBeInTheDocument()
  })

  it('não recarrega a lista ao abrir um jogo', async () => {
    vi.mocked(api.listGames).mockResolvedValue({
      games: [game],
      page: { offset: 0, limit: 50, returned: 1, total: 1, next_offset: null },
      unreadable_logs: 0,
    })
    vi.mocked(api.getGame).mockResolvedValue({
      meta: { id: 'g1' },
      hands: [],
      page: { offset: 0, limit: 100, returned: 0, total: 0, next_offset: null },
    })
    render(<AuditPage onClose={() => undefined} />)
    await userEvent.click(await screen.findByRole('button', { name: /Modo Laboratório/ }))
    await screen.findByText(/esta partida ainda não tem mãos/)
    await waitFor(() => expect(api.listGames).toHaveBeenCalledTimes(1))
  })

  it('oferece e anexa páginas adicionais sem ocultar o histórico', async () => {
    const game2 = { ...game, id: 'g2' }
    vi.mocked(api.listGames)
      .mockResolvedValueOnce({
        games: [game],
        page: { offset: 0, limit: 1, returned: 1, total: 2, next_offset: 1 },
        unreadable_logs: 0,
      })
      .mockResolvedValueOnce({
        games: [game2],
        page: { offset: 1, limit: 1, returned: 1, total: 2, next_offset: null },
        unreadable_logs: 0,
      })
    render(<AuditPage onClose={() => undefined} />)

    await userEvent.click(await screen.findByRole('button', { name: /Carregar mais partidas/ }))
    expect(await screen.findAllByRole('button', { name: /Modo Laboratório/ })).toHaveLength(2)
    expect(api.listGames).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 1, limit: 1 }))
  })
})

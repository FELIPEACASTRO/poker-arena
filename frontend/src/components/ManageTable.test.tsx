import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useGame } from '../store'
import { tableState } from '../test/factory'
import ManageTable from './ManageTable'

vi.mock('../api', () => ({
  api: { getLevels: vi.fn().mockResolvedValue({ levels: ['montecarlo'] }) },
}))

beforeEach(() => {
  useGame.setState({
    state: tableState({
      roster: Array.from({ length: 6 }, (_, seat) => ({
        seat,
        player_id: seat.toString(16).padStart(32, '0'),
        name: `P${seat}`,
        level: 'montecarlo',
        stack: 1000,
        is_human: seat === 0,
      })),
    }),
    busy: false,
    error: null,
    colors: {},
  })
})

describe('ManageTable', () => {
  it('usa a capacidade única de nove lugares', async () => {
    render(<ManageTable onClose={() => undefined} />)
    expect(screen.getByText('6/9 lugares')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: /Adicionar/ })).toBeEnabled())
  })

  it('expõe semântica de dialog acessível', () => {
    render(<ManageTable onClose={() => undefined} />)
    expect(screen.getByRole('dialog', { name: /Gerenciar mesa/ })).toHaveAttribute('aria-modal', 'true')
  })
})

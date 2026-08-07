import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useGame } from '../store'
import { seat, tableState } from '../test/factory'
import WinStats from './WinStats'

beforeEach(() => {
  useGame.setState({ state: null, wins: {}, handsDone: 0 })
})

describe('WinStats (quem mais ganha — por fichas)', () => {
  it('ranqueia por fichas e destaca o líder', () => {
    useGame.setState({
      state: tableState({
        seats: [
          seat({ seat: 0, name: 'Alfa', kind: 'bot:expert', stack: 8000 }),
          seat({ seat: 1, name: 'Beta', kind: 'bot:random', stack: 2000 }),
        ],
      }),
      wins: {},
      handsDone: 5,
    })
    render(<WinStats />)
    expect(screen.getByText('das fichas da mesa')).toBeInTheDocument()
    // Alfa (8000 de 10000) lidera com 80%
    expect(screen.getAllByText('Alfa').length).toBeGreaterThan(0)
    expect(screen.getAllByText('80%').length).toBeGreaterThan(0)
  })

  it('o líder é por FICHAS, não por mãos vencidas (o ponto do glass-box)', () => {
    useGame.setState({
      state: tableState({
        seats: [
          seat({ seat: 0, name: 'Crusher', kind: 'bot:expert', stack: 9000 }),
          seat({ seat: 1, name: 'Fish', kind: 'bot:random', stack: 1000 }),
        ],
      }),
      wins: { 1: 8, 0: 2 }, // Fish vence MAIS mãos
      handsDone: 10,
    })
    render(<WinStats />)
    // mesmo o Fish vencendo mais mãos, quem lidera (mais fichas) é o Crusher
    expect(document.querySelector('.winstats-leader-name')?.textContent).toBe('Crusher')
  })
})

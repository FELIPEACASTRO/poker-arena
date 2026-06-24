import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useGame } from '../store'
import { seat, tableState } from '../test/factory'
import WinStats from './WinStats'

beforeEach(() => {
  useGame.setState({ state: null, wins: {}, handsDone: 0 })
})

describe('WinStats (quem mais ganha)', () => {
  it('destaca o líder com maior % de vitórias', () => {
    useGame.setState({
      state: tableState({
        seats: [
          seat({ seat: 0, name: 'Alfa', kind: 'bot:expert' }),
          seat({ seat: 1, name: 'Beta', kind: 'bot:random' }),
        ],
      }),
      wins: { 0: 8, 1: 2 },
      handsDone: 10,
    })
    render(<WinStats />)
    expect(screen.getByText('vence mais que todos')).toBeInTheDocument()
    // "Alfa" aparece no bloco do líder E na lista
    expect(screen.getAllByText('Alfa').length).toBeGreaterThan(0)
    expect(screen.getAllByText('80%').length).toBeGreaterThan(0)
  })

  it('mostra placeholder antes de qualquer mão', () => {
    useGame.setState({
      state: tableState({ seats: [seat()] }),
      wins: {},
      handsDone: 0,
    })
    render(<WinStats />)
    expect(screen.getByText(/jogue algumas mãos/)).toBeInTheDocument()
  })
})

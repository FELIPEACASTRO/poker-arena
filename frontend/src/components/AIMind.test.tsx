import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useGame } from '../store'
import { seat, tableState } from '../test/factory'
import AIMind from './AIMind'

beforeEach(() => {
  useGame.setState({ state: null })
})

describe('AIMind (glass-box)', () => {
  it('mostra as 5 probabilidades da rede do Expert', () => {
    useGame.setState({
      state: tableState({
        last_actions: [{ seat: 0, type: 'raise', amount: 120 }],
        seats: [
          seat({
            seat: 0,
            name: 'Rex',
            kind: 'bot:expert',
            insight: {
              kind: 'expert',
              label: 'Rede neural: aumentar ½ (48%)',
              confidence: 0.48,
              probs: [0.04, 0.26, 0.48, 0.18, 0.04],
            },
          }),
        ],
      }),
    })
    render(<AIMind />)
    expect(screen.getByText('Rex')).toBeInTheDocument()
    expect(screen.getByText('aumentar ½')).toBeInTheDocument()
    expect(screen.getByText('48%')).toBeInTheDocument()
  })

  it('mostra a equity do MonteCarlo', () => {
    useGame.setState({
      state: tableState({
        last_actions: [{ seat: 1, type: 'call', amount: 0 }],
        seats: [
          seat({
            seat: 1,
            name: 'Mon',
            kind: 'bot:montecarlo',
            insight: { kind: 'montecarlo', label: 'Equity 72% (200 simulações)', confidence: 0.72 },
          }),
        ],
      }),
    })
    render(<AIMind />)
    expect(screen.getByText(/Equity 72%/)).toBeInTheDocument()
    expect(screen.getByText('72%')).toBeInTheDocument()
  })

  it('não renderiza quando a última jogada foi do humano (sem insight)', () => {
    useGame.setState({
      state: tableState({
        last_actions: [{ seat: 0, type: 'fold', amount: 0 }],
        seats: [seat({ seat: 0, name: 'Você', kind: 'human', insight: null })],
      }),
    })
    const { container } = render(<AIMind />)
    expect(container).toBeEmptyDOMElement()
  })
})

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useGame } from '../store'
import { tableState } from '../test/factory'
import { boundedPoints } from '../series'
import { StylePanel } from './WatchPanels'

beforeEach(() => {
  useGame.setState({
    state: tableState({
      watch_stats: {
        hands: 3, showdowns: 0, biggest_pot: 0, biggest_pot_winner: null, series: [],
        series_total_points: 3, series_start_hand: 1, series_truncated: false,
        bots: [{
          seat: 0, player_id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', name: 'Luna', level: 'montecarlo', position: 'BTN', stack: 1000, delta: 0, buy_in_total: 1000,
          hands_won: 0, hands_dealt: 3, vpip: 0, pfr: 0, aggression: 0, wtsd: 0, wsd: 0,
          positions: [{ bucket: 'early', hands: 3, vpip: 0, pfr: 0 }],
          competitive_profile: {
            version: 'ci-local-v1', scope: 'local_session_only', authority: 'descriptive_only_no_action_advice',
            posterior_method: 'beta-binomial Beta(1,1)', interval_method: 'Wilson score 95%', minimum_opportunities: 12,
            signals: [
              {
                key: 'position_exact_BTN_vpip', label: 'VPIP — BTN', family: 'posição exata', context: 'BTN',
                successes: 1, opportunities: 3, observed_rate: 1 / 3, posterior_mean: 0.4,
                interval95_low: 0.06, interval95_high: 0.79, evidence_fraction: 0.1, evidence: 'insufficient', ready: false,
              },
              {
                key: 'preflop_open_raise', label: 'Open-raise/RFI', family: 'papel', context: 'pote ainda não aberto',
                successes: 1, opportunities: 3, observed_rate: 1 / 3, posterior_mean: 0.4,
                interval95_low: 0.06, interval95_high: 0.79, evidence_fraction: 0.1, evidence: 'insufficient', ready: false,
              },
            ],
            recency: { actions: 3, ewma_aggression: 0.2, long_run_aggression: 0, delta: 0.2, direction: 'insufficient', ready: false },
          },
        }],
      },
    }),
    colors: {},
  })
})

describe('métricas do laboratório', () => {
  it('não rotula estilo com amostra insuficiente', () => {
    render(<StylePanel />)
    expect(screen.getByText(/amostra insuficiente/i)).toBeInTheDocument()
    expect(screen.queryByText('Apertado')).not.toBeInTheDocument()
  })

  it('limita e preserva as extremidades da série desenhada', () => {
    const points = Array.from({ length: 2_000 }, (_, i) => i)
    const bounded = boundedPoints(points, 500)
    expect(bounded.length).toBeLessThanOrEqual(500)
    expect(bounded[0]).toBe(0)
    expect(bounded[bounded.length - 1]).toBe(1999)
  })

  it('expõe o perfil contextual como descrição local e abstém com pouca amostra', () => {
    render(<StylePanel />)
    fireEvent.click(screen.getByText(/Inteligência contextual/i))

    expect(screen.getByText(/Sessão local · somente descritivo/i)).toBeInTheDocument()
    expect(screen.getByText('VPIP — BTN')).toBeInTheDocument()
    expect(screen.getAllByText(/abstém/i)[0]).toHaveTextContent('n=3/12')
    expect(screen.queryByText(/recomenda (pagar|aumentar|desistir)/i)).not.toBeInTheDocument()
  })
})

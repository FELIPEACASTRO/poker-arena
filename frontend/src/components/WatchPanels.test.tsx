import { render, screen } from '@testing-library/react'
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
          seat: 0, player_id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', name: 'Luna', level: 'montecarlo', stack: 1000, delta: 0, buy_in_total: 1000,
          hands_won: 0, hands_dealt: 3, vpip: 0, pfr: 0, aggression: 0, wtsd: 0, wsd: 0,
          positions: [{ bucket: 'early', hands: 3, vpip: 0, pfr: 0 }],
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
})

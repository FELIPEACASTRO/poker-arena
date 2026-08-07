import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import CopilotScreen from './CopilotScreen'
import type { CopilotResult } from '../types'

vi.mock('../api', () => ({
  api: { copilot: vi.fn(), reviewHand: vi.fn(), fromImage: vi.fn() },
}))

describe('CopilotScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('implementa dialog, foco, Escape e tabs acessíveis', async () => {
    const onClose = vi.fn()
    render(<CopilotScreen onClose={onClose} />)
    const dialog = screen.getByRole('dialog', { name: /Copiloto de mãos/ })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveFocus()
    expect(screen.getAllByRole('tab')).toHaveLength(3)
    expect(screen.getByRole('tab', { name: /Spot único/ })).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('identifica F3-vlm, expõe o gate e não o chama de baseline', async () => {
    vi.mocked(api.fromImage).mockResolvedValue({
      engine: 'F3-vlm',
      detected: {
        hole: ['As', 'Ks'], board: [], pot: 100, n_cards: 2, confidence: 0.9,
        n_players: 2, position: 'CO', stacks: {}, pot_source: 'ocr',
      },
      sanity: { ok: true, problems: [], warnings: [] },
      decision: null,
    })
    render(<CopilotScreen onClose={() => undefined} />)
    await userEvent.click(screen.getByRole('tab', { name: /Da imagem/ }))
    await userEvent.upload(screen.getByLabelText(/Screenshot da mesa/), new File(['x'], 'mesa.png', { type: 'image/png' }))
    expect(await screen.findByText('F3 · proposta multimodal')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /Diagnóstico verificável/ })).toBeInTheDocument()
    expect(screen.getByText(/Sinal interno; não equivale a acurácia/i)).toBeInTheDocument()
    expect(screen.queryByText('F1 · baseline por template')).not.toBeInTheDocument()
  })

  it('rejeita no cliente upload acima do mesmo limite de 5 MB do backend', async () => {
    render(<CopilotScreen onClose={() => undefined} />)
    await userEvent.click(screen.getByRole('tab', { name: /Da imagem/ }))
    const oversized = new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'grande.png', {
      type: 'image/png',
    })
    await userEvent.upload(screen.getByLabelText(/Screenshot da mesa/), oversized)

    expect(await screen.findByRole('alert')).toHaveTextContent(/limite de 5 MB/i)
    expect(api.fromImage).not.toHaveBeenCalled()
  })

  it('upload inválido aborta e torna irrecuperável uma análise de imagem anterior', async () => {
    let resolveImage!: (value: Awaited<ReturnType<typeof api.fromImage>>) => void
    vi.mocked(api.fromImage).mockReturnValue(new Promise((resolve) => {
      resolveImage = resolve
    }))
    render(<CopilotScreen onClose={() => undefined} />)
    await userEvent.click(screen.getByRole('tab', { name: /Da imagem/ }))
    const input = screen.getByLabelText(/Screenshot da mesa/)
    await userEvent.upload(input, new File(['valid'], 'a.png', { type: 'image/png' }))
    const signal = vi.mocked(api.fromImage).mock.calls[0][2]
    const oversized = new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'b.png', {
      type: 'image/png',
    })
    await userEvent.upload(input, oversized)

    expect(signal?.aborted).toBe(true)
    expect(await screen.findByRole('alert')).toHaveTextContent(/limite de 5 MB/i)
    await act(async () => resolveImage({
      engine: 'F3-vlm',
      detected: {
        hole: ['As', 'Ks'], board: [], pot: 100, n_cards: 2, confidence: 0.9,
        n_players: 2, position: 'CO', stacks: {}, pot_source: 'ocr',
      },
      sanity: { ok: true, problems: [], warnings: [] },
      decision: null,
    }))
    expect(screen.queryByText('F3 · proposta multimodal')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /Diagnóstico verificável/ })).not.toBeInTheDocument()
  })

  it('descarta resposta pendente quando o spot muda durante a análise', async () => {
    let resolveRequest!: (value: CopilotResult) => void
    vi.mocked(api.copilot).mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve
    }))
    const result: CopilotResult = {
      hand_label: 'Par de ases', equity_pct: 80, equity_method: 'monte-carlo-uniform-range',
      equity_trials: 5000, equity_standard_error_pct: 0.5, equity_ci95_lower_pct: 79,
      equity_ci95_upper_pct: 81, pot: 100, to_call: 40, call_cost: 40,
      pot_odds_pct: 29, ev_call: 72, mdf_pct: 71, outs: 0, draws: [], nut: null,
      texture: null, blockers: [], spr: 10, realization: 'alta', realization_why: 'teste',
      options: [], council: [], recommendation: 'call', recommendation_label: 'Pagar 40',
      recommendation_amount: null, recommendation_stable: true, decision_note: 'estável',
      headline: 'RESULTADO OBSOLETO NÃO PODE APARECER', position: null, num_players: 2,
    }

    render(<CopilotScreen onClose={() => undefined} />)
    await userEvent.click(screen.getByRole('button', { name: 'Analisar spot' }))
    const signal = vi.mocked(api.copilot).mock.calls[0][1]
    await userEvent.clear(screen.getByPlaceholderText('As Ks'))
    await userEvent.type(screen.getByPlaceholderText('As Ks'), 'Ah Ad')

    expect(signal?.aborted).toBe(true)
    await act(async () => resolveRequest(result))
    expect(screen.queryByText(result.headline)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analisar spot' })).toBeEnabled()
  })
})

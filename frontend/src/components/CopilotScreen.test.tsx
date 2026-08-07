import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import CopilotScreen from './CopilotScreen'

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
})

import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { FromImageResult } from '../types'
import VisionDiagnostics from './VisionDiagnostics'

const accepted: FromImageResult = {
  engine: 'F2-onnx',
  detected: {
    hole: ['As', 'Kh'],
    board: ['2c', '3d', '4h'],
    pot: 120,
    n_cards: 5,
    confidence: 0.82,
    n_players: 3,
    position: 'BTN',
    stacks: { '0': 900, '1': 1100 },
    pot_source: 'ocr',
  },
  sanity: { ok: true, problems: [], warnings: ['reflexo no canto inferior'] },
  decision: null,
}

describe('VisionDiagnostics', () => {
  it('expõe estado, confiança reportada, latência observada e limites da evidência', () => {
    render(<VisionDiagnostics result={accepted} latencyMs={137.4} />)
    const panel = screen.getByRole('region', {
      name: /Diagnóstico verificável da leitura de imagem/,
    })

    expect(within(panel).getByText('F2 · detector ONNX')).toBeInTheDocument()
    expect(within(panel).getByText('82%')).toBeInTheDocument()
    expect(within(panel).getByText('137 ms')).toBeInTheDocument()
    expect(within(panel).getByText(/Mão As Kh · Board 2c 3d 4h/)).toBeInTheDocument()
    expect(within(panel).getByText('Pote: 120')).toBeInTheDocument()
    expect(within(panel).getByText(/não equivale a acurácia ou calibração/i)).toBeInTheDocument()
    expect(within(panel).getByText(/não demonstra generalização/i)).toBeInTheDocument()
  })

  it('torna abstinência e todos os motivos de falha visíveis', () => {
    render(
      <VisionDiagnostics
        result={{
          ...accepted,
          engine: 'F3-vlm',
          detected: { ...accepted.detected, confidence: 0 },
          sanity: {
            ok: false,
            problems: ['carta abaixo do limiar', 'pote não detectado'],
            warnings: ['proposta remota não calibrada'],
          },
        }}
        latencyMs={null}
      />,
    )

    expect(screen.getByText('Abstenção ativa')).toBeInTheDocument()
    expect(screen.getByText('Bloqueada')).toBeInTheDocument()
    expect(screen.getByText('carta abaixo do limiar')).toBeInTheDocument()
    expect(screen.getByText('pote não detectado')).toBeInTheDocument()
    expect(screen.getByText('proposta remota não calibrada')).toBeInTheDocument()
    expect(screen.getByText('Não medida')).toBeInTheDocument()
  })

  it('não transforma confiança inválida em porcentagem aparentemente válida', () => {
    render(
      <VisionDiagnostics
        result={{ ...accepted, detected: { ...accepted.detected, confidence: Number.NaN } }}
        latencyMs={Number.POSITIVE_INFINITY}
      />,
    )
    expect(screen.getByText('Indisponível')).toBeInTheDocument()
    expect(screen.getByText('Não medida')).toBeInTheDocument()
  })
})

import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { seat, tableState } from '../test/factory'
import ActionBar from './ActionBar'

function humanTurn() {
  return tableState({
    phase: 'human_turn',
    pot: 100,
    seats: [seat({ seat: 0, name: 'Você', kind: 'human', is_turn: true, current_bet: 0 })],
    legal: { actions: ['fold', 'call', 'raise', 'all_in'], to_call: 20, min_raise_to: 40, max_raise_to: 1000 },
  })
}

const noop = () => undefined

describe('ActionBar', () => {
  it('o botão Desistir chama onAction(fold)', async () => {
    const onAction = vi.fn()
    render(
      <ActionBar state={humanTurn()} onAction={onAction} onNext={noop} onLeave={noop} busy={false} error={null} />,
    )
    await userEvent.click(screen.getByRole('button', { name: /Desistir/ }))
    expect(onAction).toHaveBeenCalledWith('fold')
  })

  it('o preset "½ pote" ajusta o valor do aumento (poker bet-sizing)', async () => {
    render(
      <ActionBar state={humanTurn()} onAction={noop} onNext={noop} onLeave={noop} busy={false} error={null} />,
    )
    // começa no mínimo legal (min_raise_to = 40)
    expect(screen.getByRole('button', { name: /Aumentar p\/\s*40/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /½ Pote/i }))
    // callTo=20, potAfterCall=120 -> ½ pote = 20 + 60 = 80
    expect(screen.getByRole('button', { name: /Aumentar p\/\s*80/ })).toBeInTheDocument()
  })

  it('o atalho de teclado F desiste', async () => {
    const onAction = vi.fn()
    render(
      <ActionBar state={humanTurn()} onAction={onAction} onNext={noop} onLeave={noop} busy={false} error={null} />,
    )
    await userEvent.keyboard('f')
    expect(onAction).toHaveBeenCalledWith('fold')
  })

  it('ignora atalhos enquanto o usuário digita', async () => {
    const onAction = vi.fn()
    render(
      <>
        <input aria-label="anotação" />
        <ActionBar state={humanTurn()} onAction={onAction} onNext={noop} onLeave={noop} busy={false} error={null} />
      </>,
    )
    const input = screen.getByRole('textbox', { name: 'anotação' })
    input.focus()
    await userEvent.keyboard('far')
    expect(onAction).not.toHaveBeenCalled()
  })

  it('ignora atalhos com modal aberto, modificadores ou key repeat', () => {
    const onAction = vi.fn()
    render(
      <>
        <div role="dialog" aria-modal="true">modal</div>
        <ActionBar state={humanTurn()} onAction={onAction} onNext={noop} onLeave={noop} busy={false} error={null} />
      </>,
    )
    fireEvent.keyDown(window, { key: 'f' })
    fireEvent.keyDown(window, { key: 'f', ctrlKey: true })
    fireEvent.keyDown(window, { key: 'f', repeat: true })
    expect(onAction).not.toHaveBeenCalled()
  })

  it('não transforma campo de aumento vazio em NaN', async () => {
    render(
      <ActionBar state={humanTurn()} onAction={noop} onNext={noop} onLeave={noop} busy={false} error={null} />,
    )
    const input = screen.getByRole('spinbutton')
    await userEvent.clear(input)
    expect(input).toHaveValue(40)
    expect(screen.getByRole('button', { name: /Aumentar p\/\s*40/ })).toBeInTheDocument()
  })
})

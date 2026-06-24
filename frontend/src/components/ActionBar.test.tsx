import { render, screen } from '@testing-library/react'
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
    expect(screen.getByRole('button', { name: /Aumentar p\/ 40/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '½ pote' }))
    // callTo=20, potAfterCall=120 -> ½ pote = 20 + 60 = 80
    expect(screen.getByRole('button', { name: /Aumentar p\/ 80/ })).toBeInTheDocument()
  })

  it('o atalho de teclado F desiste', async () => {
    const onAction = vi.fn()
    render(
      <ActionBar state={humanTurn()} onAction={onAction} onNext={noop} onLeave={noop} busy={false} error={null} />,
    )
    await userEvent.keyboard('f')
    expect(onAction).toHaveBeenCalledWith('fold')
  })
})

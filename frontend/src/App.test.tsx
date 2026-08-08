import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import App from './App'

describe('App startup view', () => {
  afterEach(() => {
    window.history.replaceState({}, '', '/')
    window.localStorage.clear()
  })

  it('mantém disponível a revisão manual quando a URL usa view=copilot', async () => {
    window.history.replaceState({}, '', '/?view=copilot')

    render(<App />)

    expect(
      await screen.findByRole('dialog', { name: /Copiloto de mãos/ }, { timeout: 5_000 }),
    ).toBeInTheDocument()
  })

  it('abre o workspace de captura quando o launcher usa view=capture', async () => {
    window.history.replaceState({}, '', '/?view=capture')

    render(<App />)

    const workspace = await screen.findByRole(
      'main',
      { name: /Captura supervisionada/ },
      { timeout: 5_000 },
    )
    expect(workspace).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Selecionar janela no outro monitor/ }),
    ).toBeDisabled()
    expect(screen.queryByRole('heading', { name: /^Poker Arena/ })).not.toBeInTheDocument()
    expect(workspace).toHaveFocus()
    expect(workspace).toHaveTextContent(/somente depois da confirmação/i)
  })
})

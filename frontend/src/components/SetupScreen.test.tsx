import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import SetupScreen from './SetupScreen'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('SetupScreen authentication', () => {
  it('edita o token como senha controlada sem persistir no navegador', async () => {
    vi.spyOn(api, 'getLevels').mockResolvedValue({ levels: ['random', 'heuristic'] })
    const onApiTokenChange = vi.fn()
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem')
    render(
      <SetupScreen
        apiToken=""
        busy={false}
        error={null}
        onApiTokenChange={onApiTokenChange}
        onCreate={() => undefined}
      />,
    )

    const input = screen.getByLabelText(/Token da API/i)
    expect(input).toHaveAttribute('type', 'password')
    await userEvent.type(input, 'secret')

    await waitFor(() => expect(onApiTokenChange).toHaveBeenCalled())
    expect(storageWrite).not.toHaveBeenCalled()
    expect(screen.getByText(/somente na memória/i)).toBeInTheDocument()
  })
})

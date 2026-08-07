import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import LiveCopilotScreen from './LiveCopilotScreen'

function fakeStream(surface?: 'window' | 'monitor' | 'browser' | 'unknown') {
  const track = {
    stop: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    getSettings: () => ({ displaySurface: surface }),
  }
  return { stream: { getTracks: () => [track], getVideoTracks: () => [track] } as unknown as MediaStream, track }
}

describe('LiveCopilotScreen', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  })

  it('exige consentimento explícito e impede duas capturas simultâneas', async () => {
    const { stream } = fakeStream('window')
    let resolvePermission: (stream: MediaStream) => void = () => undefined
    const permission = new Promise<MediaStream>((resolve) => {
      resolvePermission = resolve
    })
    const getDisplayMedia = vi.fn().mockReturnValue(permission)
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getDisplayMedia } })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    render(<LiveCopilotScreen onClose={() => undefined} />)

    const capture = screen.getByRole('button', { name: /Selecionar janela do jogo/ })
    expect(capture).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: /captura desta tela/i }))
    await userEvent.dblClick(capture)
    await waitFor(() => expect(getDisplayMedia).toHaveBeenCalledTimes(1))
    resolvePermission(stream)
    await userEvent.click(await screen.findByRole('button', { name: /Escolher outra janela/ }))
    const consent = screen.getByRole('checkbox', { name: /captura desta tela/i })
    expect(consent).toBeChecked()
    await userEvent.click(consent)
    expect(screen.getByRole('button', { name: /Selecionar janela do jogo/ })).toBeDisabled()
  })

  it('encerra tracks se o preview falhar depois da permissão', async () => {
    const { stream, track } = fakeStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(new Error('preview falhou'))
    render(<LiveCopilotScreen onClose={() => undefined} />)
    await userEvent.click(screen.getByRole('checkbox', { name: /captura desta tela/i }))
    await userEvent.click(screen.getByRole('button', { name: /Selecionar janela do jogo/ }))
    await screen.findByText(/preview falhou/)
    expect(track.stop).toHaveBeenCalled()
  })

  it('revogação durante o prompt de captura encerra o stream antes de qualquer sessão', async () => {
    const { stream, track } = fakeStream()
    let resolvePermission: (stream: MediaStream) => void = () => undefined
    const permission = new Promise<MediaStream>((resolve) => {
      resolvePermission = resolve
    })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockReturnValue(permission) },
    })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    render(<LiveCopilotScreen onClose={() => undefined} />)

    const consent = screen.getByRole('checkbox', { name: /captura desta tela/i })
    await userEvent.click(consent)
    await userEvent.click(screen.getByRole('button', { name: /Selecionar janela do jogo/ }))
    await userEvent.click(consent)
    resolvePermission(stream)

    await waitFor(() => expect(track.stop).toHaveBeenCalled())
    expect(consent).not.toBeChecked()
    expect(screen.getByRole('button', { name: /Selecionar janela do jogo/ })).toBeDisabled()
  })

  it('mantém opt-in remoto separado, opcional e desligado por padrão', async () => {
    render(<LiveCopilotScreen onClose={() => undefined} />)
    const localConsent = screen.getByRole('checkbox', { name: /captura desta tela/i })
    const remoteConsent = screen.getByRole('checkbox', { name: /VLM remoto de terceiro/i })

    expect(remoteConsent).not.toBeChecked()
    expect(remoteConsent).toBeDisabled()
    await userEvent.click(localConsent)
    expect(remoteConsent).toBeEnabled()
    expect(remoteConsent).not.toBeChecked()
    await userEvent.click(remoteConsent)
    expect(remoteConsent).toBeChecked()
    await userEvent.click(localConsent)
    expect(localConsent).not.toBeChecked()
    expect(remoteConsent).not.toBeChecked()
  })

  it('captura local não concede compartilhamento remoto implicitamente', async () => {
    const { stream } = fakeStream('window')
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback) => {
      callback(new Blob(['frame'], { type: 'image/jpeg' }))
    })
    const fromImage = vi.spyOn(api, 'fromImage').mockResolvedValue({
      engine: 'F1-template',
      detected: {
        hole: [], board: [], pot: null, n_cards: 0, confidence: 0,
        n_players: 0, position: '', stacks: {}, pot_source: 'template',
      },
      sanity: { ok: false, problems: ['leitura insuficiente'], warnings: [] },
      decision: null,
    })
    render(<LiveCopilotScreen onClose={() => undefined} />)
    const video = document.querySelector('video') as HTMLVideoElement
    Object.defineProperties(video, {
      videoWidth: { configurable: true, value: 800 },
      videoHeight: { configurable: true, value: 600 },
    })

    await userEvent.click(screen.getByRole('checkbox', { name: /captura desta tela/i }))
    await userEvent.click(screen.getByRole('button', { name: /Selecionar janela do jogo/ }))
    expect(fromImage).not.toHaveBeenCalled()
    await userEvent.click(await screen.findByRole('button', { name: /Confirmar e iniciar análise/ }))
    await waitFor(() => expect(fromImage).toHaveBeenCalled(), { timeout: 2500 })

    const options = fromImage.mock.calls[0][1]
    expect(options.remoteVlmConsent).toBeUndefined()
    expect(
      await screen.findByRole('region', { name: /Diagnóstico verificável/ }),
    ).toBeInTheDocument()
    expect(screen.getByText('Abstenção ativa')).toBeInTheDocument()
    expect(screen.getByText('leitura insuficiente')).toBeInTheDocument()
  })

  it('usa sessão emitida pelo servidor e a revoga ao parar', async () => {
    const { stream } = fakeStream('window')
    const sessionId = 'server-issued-session-1234567890'
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    const createConsent = vi.spyOn(api, 'createRemoteVlmConsent').mockResolvedValue({
      session_id: sessionId,
      expires_in_seconds: 600,
    })
    const revokeConsent = vi.spyOn(api, 'revokeRemoteVlmConsent').mockResolvedValue({
      revoked: true,
    })
    render(<LiveCopilotScreen onClose={() => undefined} />)

    await userEvent.click(screen.getByRole('checkbox', { name: /captura desta tela/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /VLM remoto de terceiro/i }))
    await userEvent.click(screen.getByRole('button', { name: /Selecionar janela do jogo/ }))
    expect(createConsent).not.toHaveBeenCalled()
    await userEvent.click(await screen.findByRole('button', { name: /Confirmar e iniciar análise/ }))
    await screen.findByRole('button', { name: /Encerrar compartilhamento/ })

    expect(createConsent).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: /Encerrar compartilhamento/ }))
    await waitFor(() => expect(revokeConsent).toHaveBeenCalledWith(sessionId))
  })

  it('não atualiza captura após desmontar enquanto video.play ainda está pendente', async () => {
    const { stream, track } = fakeStream('window')
    let resolvePlay: () => void = () => undefined
    const playPending = new Promise<void>((resolve) => {
      resolvePlay = resolve
    })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockReturnValue(playPending)
    const view = render(<LiveCopilotScreen onClose={() => undefined} />)

    await userEvent.click(screen.getByRole('checkbox', { name: /captura desta tela/i }))
    await userEvent.click(screen.getByRole('button', { name: /Selecionar janela do jogo/ }))
    await waitFor(() => expect(play).toHaveBeenCalledTimes(1))
    view.unmount()
    await act(async () => resolvePlay())

    await waitFor(() => expect(track.stop).toHaveBeenCalled())
  })

  it('encerra a track ao desmontar enquanto o servidor ainda emite consentimento remoto', async () => {
    const { stream, track } = fakeStream('window')
    const sessionId = 'server-issued-session-1234567890'
    let resolveConsent: (value: { session_id: string; expires_in_seconds: number }) => void =
      () => undefined
    const pendingConsent = new Promise<{ session_id: string; expires_in_seconds: number }>(
      (resolve) => {
        resolveConsent = resolve
      },
    )
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    const createConsent = vi
      .spyOn(api, 'createRemoteVlmConsent')
      .mockReturnValue(pendingConsent)
    const revokeConsent = vi.spyOn(api, 'revokeRemoteVlmConsent').mockResolvedValue({
      revoked: true,
    })
    const view = render(<LiveCopilotScreen onClose={() => undefined} />)

    await userEvent.click(screen.getByRole('checkbox', { name: /captura desta tela/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /VLM remoto de terceiro/i }))
    await userEvent.click(screen.getByRole('button', { name: /Selecionar janela do jogo/ }))
    await userEvent.click(await screen.findByRole('button', { name: /Confirmar e iniciar análise/ }))
    await waitFor(() => expect(createConsent).toHaveBeenCalledTimes(1))
    view.unmount()
    expect(track.stop).toHaveBeenCalled()

    await act(async () => resolveConsent({ session_id: sessionId, expires_in_seconds: 600 }))
    await waitFor(() => expect(revokeConsent).toHaveBeenCalledWith(sessionId))
  })

  it.each(['monitor', 'browser', 'unknown', undefined] as const)(
    'bloqueia a análise quando a fonte escolhida é %s',
    async (surface) => {
      const { stream } = fakeStream(surface)
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
      })
      vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
      const fromImage = vi.spyOn(api, 'fromImage')
      render(<LiveCopilotScreen onClose={() => undefined} />)

      await userEvent.click(screen.getByRole('checkbox', { name: /captura desta tela/i }))
      await userEvent.click(screen.getByRole('button', { name: /Selecionar janela do jogo/ }))

      const confirm = await screen.findByRole('button', { name: /Confirmar e iniciar análise/ })
      expect(confirm).toBeDisabled()
      expect(screen.getByRole('alert')).toHaveTextContent(/Somente uma fonte confirmada pelo navegador como Janela/)
      expect(screen.queryByText(/Esta é a janela correta/)).not.toBeInTheDocument()
      expect(fromImage).not.toHaveBeenCalled()
    },
  )

  it('foca o workspace autônomo e identifica a prévia', () => {
    render(<LiveCopilotScreen standalone onClose={() => undefined} />)
    const workspace = screen.getByRole('main', { name: /Captura supervisionada/ })
    expect(workspace).toHaveFocus()
    expect(screen.getByLabelText('Prévia da janela compartilhada')).toBeInTheDocument()
    expect(screen.queryByText('Recomendação')).not.toBeInTheDocument()
  })

  it('explica a recusa de permissão sem iniciar análise', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getDisplayMedia: vi.fn().mockRejectedValue(
          new DOMException('Permissão de compartilhamento negada', 'NotAllowedError'),
        ),
      },
    })
    const fromImage = vi.spyOn(api, 'fromImage')
    render(<LiveCopilotScreen onClose={() => undefined} />)

    await userEvent.click(screen.getByRole('checkbox', { name: /captura desta tela/i }))
    await userEvent.click(screen.getByRole('button', { name: /Selecionar janela do jogo/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/Permissão de compartilhamento negada/)
    expect(fromImage).not.toHaveBeenCalled()
  })

  it('anuncia quando o navegador encerra a track compartilhada', async () => {
    const { stream, track } = fakeStream('window')
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    render(<LiveCopilotScreen onClose={() => undefined} />)
    await userEvent.click(screen.getByRole('checkbox', { name: /captura desta tela/i }))
    await userEvent.click(screen.getByRole('button', { name: /Selecionar janela do jogo/ }))
    await screen.findByRole('button', { name: /Confirmar e iniciar análise/ })

    const ended = track.addEventListener.mock.calls.find(([event]) => event === 'ended')?.[1]
    expect(ended).toBeTypeOf('function')
    await act(async () => { (ended as EventListener)(new Event('ended')) })

    expect(screen.getByRole('alert')).toHaveTextContent(/compartilhamento foi encerrado/)
    expect(screen.getByRole('status')).toHaveTextContent(/Nenhum quadro está sendo analisado/)
  })
})

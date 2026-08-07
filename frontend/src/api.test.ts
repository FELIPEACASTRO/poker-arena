import { afterEach, describe, expect, it, vi } from 'vitest'
import { API_BASE, HttpError, api, setApiToken } from './api'

const bettingContext = {
  to_call: 0,
  my_stack: 1000,
  effective_stack: 1000,
  num_opponents: 1,
  in_position: true,
  hero_current_bet: 0,
  current_bet: 0,
  min_raise_increment: 20,
  raise_reopened: true,
}

afterEach(() => {
  setApiToken(null)
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('cliente HTTP', () => {
  it('ativa strict=true em toda análise por imagem', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.fromImage(new File(['x'], 'mesa.png', { type: 'image/png' }), {
      ...bettingContext,
    })

    const body = fetchMock.mock.calls[0][1]?.body as FormData
    expect(body.get('strict')).toBe('true')
    expect(body.get('remote_vlm_consent')).toBe('false')
    expect(body.has('remote_vlm_session_id')).toBe(false)
  })

  it('vincula consentimento remoto explícito a cada request da sessão', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const sessionId = '123e4567-e89b-42d3-a456-426614174000'

    await api.fromImage(new File(['x'], 'mesa.png', { type: 'image/png' }), {
      ...bettingContext,
      remoteVlmConsent: { granted: true, sessionId },
    })

    const body = fetchMock.mock.calls[0][1]?.body as FormData
    expect(body.get('remote_vlm_consent')).toBe('true')
    expect(body.get('remote_vlm_session_id')).toBe(sessionId)
  })

  it('formata detail[] do FastAPI com status e campos', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: [{ loc: ['body', 'my_stack'], msg: 'Input should be greater than 0' }] }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    await expect(api.copilot({
      hole: ['As', 'Ks'], board: [], pot: 0, to_call: 0, my_stack: 0,
      effective_stack: 1000, num_opponents: 1, in_position: true,
      table_size: 2, hero_current_bet: 0, current_bet: 0,
      min_raise_increment: 20, raise_reopened: true,
    })).rejects.toThrow('HTTP 422: my_stack: Input should be greater than 0')
  })

  it('preserva corpo textual em erro não JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('serviço indisponível', { status: 503 })))
    await expect(api.getLevels()).rejects.toThrow('HTTP 503: serviço indisponível')
  })

  it('expõe status e corpo estruturados para recuperação de conflitos', async () => {
    const body = { detail: 'versão divergente' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status: 409,
        headers: { 'Content-Type': 'application/json' },
      }),
    ))

    const failure = await api.getTable('mesa').catch((caught: unknown) => caught)
    expect(failure).toBeInstanceOf(HttpError)
    expect(failure).toMatchObject({ status: 409, body })
  })

  it('envia paginação explícita nas consultas de auditoria', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ games: [], page: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ meta: {}, hands: [], page: {} }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.listGames({ offset: 50, limit: 25 })
    await api.getGame('partida/1', { offset: 100, limit: 40 })

    expect(fetchMock.mock.calls[0][0]).toBe(`${API_BASE}/games?offset=50&limit=25`)
    expect(fetchMock.mock.calls[1][0]).toBe(`${API_BASE}/games/partida%2F1?offset=100&limit=40`)
  })

  it('envia idempotência e versão esperada nos comandos de sessão', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ version: 8 }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          ETag: '"8"',
          'X-Idempotent-Replay': 'true',
        },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await api.act('mesa-1', 'fold', 0, {
      commandId: '123e4567-e89b-42d3-a456-426614174000',
      expectedVersion: 7,
    })

    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(headers.get('Idempotency-Key')).toBe('123e4567-e89b-42d3-a456-426614174000')
    expect(headers.get('If-Match')).toBe('7')
    expect(result).toMatchObject({ version: 8, etag: '"8"', replayed: true })
  })

  it('envia idempotência sem If-Match ao criar mesa', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ version: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.createTable({
      human_name: 'EU', bots: [], starting_stack: 1000, small_blind: 10, big_blind: 20,
    }, { commandId: '123e4567-e89b-42d3-a456-426614174001' })

    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(headers.get('Idempotency-Key')).toBe('123e4567-e89b-42d3-a456-426614174001')
    expect(headers.has('If-Match')).toBe(false)
  })

  it('propaga cancelamento sem tratar consultas do copiloto como comandos', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await api.reviewHand('starting_stacks=[1,1]\nactions=[]', 1, controller.signal)

    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = new Headers(init.headers)
    expect(init.signal).toBe(controller.signal)
    expect(headers.has('Idempotency-Key')).toBe(false)
    expect(headers.has('If-Match')).toBe(false)
  })

  it('envia token somente em header e nunca em URL, corpo ou armazenamento', async () => {
    const token = 't'.repeat(32)
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem')
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ levels: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    setApiToken(token)
    await api.getLevels()

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`${API_BASE}/levels`)
    expect(url).not.toContain(token)
    expect(new Headers(init.headers).get('X-Poker-Token')).toBe(token)
    expect(init.body).toBeUndefined()
    expect(storageWrite).not.toHaveBeenCalled()
  })

  it('autentica multipart sem transformar token em campo do formulário', async () => {
    const token = 'm'.repeat(32)
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    setApiToken(token)

    await api.fromImage(new File(['x'], 'mesa.png', { type: 'image/png' }), {
      ...bettingContext,
    })

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const body = init.body as FormData
    expect(url).not.toContain(token)
    expect(new Headers(init.headers).get('X-Poker-Token')).toBe(token)
    expect([...body.values()]).not.toContain(token)
    expect(new Headers(init.headers).has('Content-Type')).toBe(false)
  })

  it('cria e revoga consentimento remoto por corpo autenticado, nunca por URL', async () => {
    const token = 'r'.repeat(32)
    const sessionId = 'server-issued-session-1234567890'
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ session_id: sessionId, expires_in_seconds: 600 }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ revoked: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)
    setApiToken(token)

    const issued = await api.createRemoteVlmConsent()
    await api.revokeRemoteVlmConsent(issued.session_id)

    const [createUrl, createInit] = fetchMock.mock.calls[0] as [string, RequestInit]
    const [revokeUrl, revokeInit] = fetchMock.mock.calls[1] as [string, RequestInit]
    expect(createUrl).toBe(`${API_BASE}/copilot/remote-vlm/consent-sessions`)
    expect(revokeUrl).toBe(createUrl)
    expect(createUrl).not.toContain(sessionId)
    expect(revokeUrl).not.toContain(sessionId)
    expect(createInit.method).toBe('POST')
    expect(createInit.body).toBe(JSON.stringify({ consent: true }))
    expect(revokeInit.method).toBe('DELETE')
    expect(revokeInit.body).toBe(JSON.stringify({ session_id: sessionId }))
    expect(new Headers(createInit.headers).get('X-Poker-Token')).toBe(token)
    expect(new Headers(revokeInit.headers).get('X-Poker-Token')).toBe(token)
  })
})

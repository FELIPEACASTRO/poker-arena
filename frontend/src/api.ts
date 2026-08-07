import type {
  AddPlayer,
  CopilotRequest,
  CopilotResult,
  CreateConfig,
  FromImageResult,
  GameList,
  GameLog,
  HandReviewResult,
  TableState,
} from './types'
import type { StandardPosition } from './positions'

export const API_BASE = import.meta.env.VITE_API ?? 'http://127.0.0.1:8000'

// Authentication is deliberately process-memory only: never URL, storage or build-time env.
let apiToken: string | null = null

export function setApiToken(value: string | null): void {
  apiToken = value && value.length > 0 ? value : null
}

export interface CommandOptions {
  commandId: string
  expectedVersion?: number
  signal?: AbortSignal
}

export interface PageOptions {
  offset?: number
  limit?: number
  signal?: AbortSignal
}

export class HttpError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, message: string, body: unknown) {
    super(message)
    this.name = 'HttpError'
    this.status = status
    this.body = body
  }
}

export interface RemoteVlmConsent {
  granted: true
  sessionId: string
}

export interface RemoteVlmConsentSession {
  session_id: string
  expires_in_seconds: number
}

type FastApiIssue = { loc?: unknown[]; msg?: unknown }

function issueText(issue: FastApiIssue): string | null {
  if (typeof issue.msg !== 'string') return null
  const path = Array.isArray(issue.loc)
    ? issue.loc.filter((part) => part !== 'body' && part !== 'query').join('.')
    : ''
  return path ? `${path}: ${issue.msg}` : issue.msg
}

function errorText(body: unknown): string | null {
  if (typeof body === 'string') return body.trim() || null
  if (!body || typeof body !== 'object') return null
  const value = body as Record<string, unknown>
  if (typeof value.detail === 'string') return value.detail
  if (Array.isArray(value.detail)) {
    const issues = value.detail
      .map((item) => (item && typeof item === 'object' ? issueText(item as FastApiIssue) : null))
      .filter((item): item is string => Boolean(item))
    if (issues.length) return issues.join('; ')
  }
  if (typeof value.message === 'string') return value.message
  if (typeof value.error === 'string') return value.error
  return null
}

async function asJson<T>(response: Response): Promise<T> {
  const text = await response.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text) as unknown
    } catch {
      body = text
    }
  }
  if (!response.ok) {
    const detail = errorText(body)
    throw new HttpError(
      response.status,
      `HTTP ${response.status}${detail ? `: ${detail}` : ''}`,
      body,
    )
  }
  if (!text) throw new Error(`HTTP ${response.status}: resposta vazia`)
  if (typeof body === 'string') throw new Error(`HTTP ${response.status}: resposta JSON inválida`)
  return body as T
}

async function asTableState(response: Response): Promise<TableState> {
  const view = await asJson<TableState>(response)
  const replay = response.headers.get('X-Idempotent-Replay')?.toLowerCase()
  return {
    ...view,
    etag: response.headers.get('ETag') ?? undefined,
    replayed: replay === 'true' || replay === '1',
  }
}

const authHeaders = (): Record<string, string> =>
  apiToken ? { 'X-Poker-Token': apiToken } : {}

const commandHeaders = (options?: CommandOptions): Record<string, string> => {
  const headers = authHeaders()
  if (options?.commandId) headers['Idempotency-Key'] = options.commandId
  if (options?.expectedVersion !== undefined) {
    headers['If-Match'] = String(options.expectedVersion)
  }
  return headers
}

const post = (body?: unknown, options?: CommandOptions): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json', ...commandHeaders(options) },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  signal: options?.signal,
})

const queryPost = (body: unknown, signal?: AbortSignal): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json', ...authHeaders() },
  body: JSON.stringify(body),
  signal,
})

function pageQuery(options: PageOptions, defaultLimit: number): string {
  const params = new URLSearchParams({
    offset: String(options.offset ?? 0),
    limit: String(options.limit ?? defaultLimit),
  })
  return params.toString()
}

export const api = {
  createTable: (cfg: CreateConfig, options: CommandOptions) =>
    fetch(`${API_BASE}/tables`, post(cfg, options)).then(asTableState),

  getTable: (id: string, signal?: AbortSignal) =>
    fetch(`${API_BASE}/tables/${encodeURIComponent(id)}`, { headers: authHeaders(), signal }).then(asTableState),

  act: (id: string, type: string, amount = 0, options: CommandOptions) =>
    fetch(`${API_BASE}/tables/${encodeURIComponent(id)}/actions`, post({ type, amount }, options)).then(
      asTableState,
    ),

  nextHand: (id: string, options: CommandOptions) =>
    fetch(`${API_BASE}/tables/${encodeURIComponent(id)}/next-hand`, post(undefined, options)).then(
      asTableState,
    ),

  step: (id: string, options: CommandOptions) =>
    fetch(`${API_BASE}/tables/${encodeURIComponent(id)}/step`, post(undefined, options)).then(
      asTableState,
    ),

  addPlayer: (id: string, body: AddPlayer, options: CommandOptions) =>
    fetch(`${API_BASE}/tables/${encodeURIComponent(id)}/players`, post(body, options)).then(
      asTableState,
    ),

  removePlayer: (id: string, seat: number, options: CommandOptions) =>
    fetch(`${API_BASE}/tables/${encodeURIComponent(id)}/players/${seat}`, {
      method: 'DELETE',
      headers: commandHeaders(options),
      signal: options.signal,
    }).then(asTableState),

  getLevels: (signal?: AbortSignal) =>
    fetch(`${API_BASE}/levels`, { headers: authHeaders(), signal }).then(asJson<{ levels: string[] }>),

  listGames: (options: PageOptions = {}) =>
    fetch(`${API_BASE}/games?${pageQuery(options, 50)}`, {
      headers: authHeaders(),
      signal: options.signal,
    }).then(asJson<GameList>),

  getGame: (id: string, options: PageOptions = {}) =>
    fetch(`${API_BASE}/games/${encodeURIComponent(id)}?${pageQuery(options, 100)}`, {
      headers: authHeaders(),
      signal: options.signal,
    }).then(asJson<GameLog>),

  copilot: (body: CopilotRequest, signal?: AbortSignal) =>
    fetch(
      `${API_BASE}/copilot`,
      queryPost(body, signal),
    ).then(asJson<CopilotResult>),

  reviewHand: (phh: string, player: number, signal?: AbortSignal) =>
    fetch(`${API_BASE}/copilot/review-hand`, queryPost({ phh, player }, signal)).then(
      asJson<HandReviewResult>,
    ),

  createRemoteVlmConsent: (signal?: AbortSignal) =>
    fetch(
      `${API_BASE}/copilot/remote-vlm/consent-sessions`,
      queryPost({ consent: true }, signal),
    ).then(asJson<RemoteVlmConsentSession>),

  revokeRemoteVlmConsent: (sessionId: string, signal?: AbortSignal) =>
    fetch(`${API_BASE}/copilot/remote-vlm/consent-sessions`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ session_id: sessionId }),
      signal,
    }).then(asJson<{ revoked: boolean }>),

  fromImage: (
    file: File,
    opts: {
      to_call: number
      my_stack: number
      effective_stack: number
      num_opponents: number
      in_position: boolean
      hero_current_bet: number
      current_bet: number
      min_raise_increment: number
      raise_reopened: boolean
      position?: StandardPosition
      remoteVlmConsent?: RemoteVlmConsent
    },
    signal?: AbortSignal,
  ) => {
    const fd = new FormData()
    fd.append('image', file)
    fd.append('to_call', String(opts.to_call))
    fd.append('my_stack', String(opts.my_stack))
    fd.append('effective_stack', String(opts.effective_stack))
    fd.append('num_opponents', String(opts.num_opponents))
    fd.append('in_position', String(opts.in_position))
    fd.append('hero_current_bet', String(opts.hero_current_bet))
    fd.append('current_bet', String(opts.current_bet))
    fd.append('min_raise_increment', String(opts.min_raise_increment))
    fd.append('raise_reopened', String(opts.raise_reopened))
    fd.append('strict', 'true')
    fd.append('remote_vlm_consent', String(opts.remoteVlmConsent?.granted === true))
    if (opts.remoteVlmConsent) {
      fd.append('remote_vlm_session_id', opts.remoteVlmConsent.sessionId)
    }
    if (opts.position) fd.append('position', opts.position)
    return fetch(`${API_BASE}/copilot/from-image`, {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
      signal,
    }).then(
      asJson<FromImageResult>,
    )
  },
}

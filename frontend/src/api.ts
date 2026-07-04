import type {
  AddPlayer,
  CopilotRequest,
  CopilotResult,
  CreateConfig,
  FromImageResult,
  GameLog,
  GameSummary,
  HandReviewResult,
  TableState,
} from './types'

const BASE = import.meta.env.VITE_API ?? 'http://127.0.0.1:8000'

async function asJson<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = (await r.json().catch(() => ({}))) as { detail?: string }
    throw new Error(body.detail ?? `Erro HTTP ${r.status}`)
  }
  return (await r.json()) as T
}

const POST = { method: 'POST', headers: { 'Content-Type': 'application/json' } }

export const api = {
  createTable: (cfg: CreateConfig) =>
    fetch(`${BASE}/tables`, { ...POST, body: JSON.stringify(cfg) }).then((r) =>
      asJson<TableState>(r),
    ),

  getTable: (id: string) =>
    fetch(`${BASE}/tables/${id}`).then((r) => asJson<TableState>(r)),

  act: (id: string, type: string, amount = 0) =>
    fetch(`${BASE}/tables/${id}/actions`, {
      ...POST,
      body: JSON.stringify({ type, amount }),
    }).then((r) => asJson<TableState>(r)),

  nextHand: (id: string) =>
    fetch(`${BASE}/tables/${id}/next-hand`, POST).then((r) => asJson<TableState>(r)),

  step: (id: string) =>
    fetch(`${BASE}/tables/${id}/step`, POST).then((r) => asJson<TableState>(r)),

  addPlayer: (id: string, body: AddPlayer) =>
    fetch(`${BASE}/tables/${id}/players`, { ...POST, body: JSON.stringify(body) }).then((r) =>
      asJson<TableState>(r),
    ),

  removePlayer: (id: string, seat: number) =>
    fetch(`${BASE}/tables/${id}/players/${seat}`, { method: 'DELETE' }).then((r) =>
      asJson<TableState>(r),
    ),

  getLevels: () =>
    fetch(`${BASE}/levels`).then((r) => asJson<{ levels: string[] }>(r)),

  listGames: () => fetch(`${BASE}/games`).then((r) => asJson<{ games: GameSummary[] }>(r)),

  getGame: (id: string) => fetch(`${BASE}/games/${id}`).then((r) => asJson<GameLog>(r)),

  copilot: (body: CopilotRequest) =>
    fetch(`${BASE}/copilot`, { ...POST, body: JSON.stringify(body) }).then((r) =>
      asJson<CopilotResult>(r),
    ),

  reviewHand: (phh: string, player: number) =>
    fetch(`${BASE}/copilot/review-hand`, { ...POST, body: JSON.stringify({ phh, player }) }).then(
      (r) => asJson<HandReviewResult>(r),
    ),

  fromImage: (
    file: File,
    opts: { to_call: number; my_stack: number; num_opponents: number; in_position: boolean },
  ) => {
    const fd = new FormData()
    fd.append('image', file)
    fd.append('to_call', String(opts.to_call))
    fd.append('my_stack', String(opts.my_stack))
    fd.append('num_opponents', String(opts.num_opponents))
    fd.append('in_position', String(opts.in_position))
    return fetch(`${BASE}/copilot/from-image`, { method: 'POST', body: fd }).then((r) =>
      asJson<FromImageResult>(r),
    )
  },
}

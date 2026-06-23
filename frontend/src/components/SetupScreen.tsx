import { useState } from 'react'
import type { BotSpec, CreateConfig } from '../types'

const LEVELS = [
  { id: 'random', label: '🟢 Iniciante — joga no chute' },
  { id: 'heuristic', label: '🟡 Amador — joga por regras' },
  { id: 'montecarlo', label: '🟠 Intermediário — calcula chances' },
]
const NAMES = ['Luna', 'Caio', 'Sofia', 'Alex', 'Maya']

interface Props {
  onCreate: (cfg: CreateConfig) => void
  busy: boolean
  error: string | null
}

export default function SetupScreen({ onCreate, busy, error }: Props) {
  const [count, setCount] = useState(3)
  const [levels, setLevels] = useState<string[]>([
    'random',
    'heuristic',
    'montecarlo',
    'heuristic',
    'montecarlo',
  ])
  const [stack, setStack] = useState(1000)

  function start() {
    const bots: BotSpec[] = Array.from({ length: count }, (_, i) => ({
      name: NAMES[i],
      level: levels[i],
    }))
    onCreate({
      human_name: 'VOCÊ',
      bots,
      starting_stack: stack,
      small_blind: 10,
      big_blind: 20,
    })
  }

  return (
    <div className="setup">
      <div className="setup-card">
        <div className="setup-suit">♠</div>
        <h1 className="brand">Poker Arena</h1>
        <p className="tagline">Você contra a inteligência das máquinas.</p>

        <label className="field">
          <span>Quantos bots na mesa?</span>
          <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>

        <div className="bots-config">
          {Array.from({ length: count }, (_, i) => (
            <label className="field" key={i}>
              <span>{NAMES[i]}</span>
              <select
                value={levels[i]}
                onChange={(e) => {
                  const next = [...levels]
                  next[i] = e.target.value
                  setLevels(next)
                }}
              >
                {LEVELS.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.label}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>

        <label className="field">
          <span>Fichas iniciais</span>
          <input
            type="number"
            value={stack}
            min={100}
            step={100}
            onChange={(e) => setStack(Number(e.target.value))}
          />
        </label>

        {error && <div className="error">⚠ {error}</div>}

        <button className="btn btn-start" disabled={busy} onClick={start}>
          {busy ? 'Embaralhando…' : 'Sentar à mesa'}
        </button>
        <p className="hint">Dica: rode o backend antes — <code>uvicorn poker_arena.api.app:app</code></p>
      </div>
    </div>
  )
}

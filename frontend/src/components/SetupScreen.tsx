import { useEffect, useState } from 'react'
import { api } from '../api'
import type { BotSpec, CreateConfig } from '../types'

const LEVELS = [
  { id: 'random', label: '🟢 Iniciante — joga no chute' },
  { id: 'heuristic', label: '🟡 Amador — joga por regras' },
  { id: 'montecarlo', label: '🟠 Intermediário — calcula chances' },
  { id: 'expert', label: '🔴 Expert — IA treinada (solver + self-play)' },
]
const NAMES = ['Luna', 'Caio', 'Sofia', 'Alex', 'Maya', 'Rex']

interface Props {
  onCreate: (cfg: CreateConfig) => void
  busy: boolean
  error: string | null
}

export default function SetupScreen({ onCreate, busy, error }: Props) {
  const [mode, setMode] = useState<'play' | 'watch'>('play')
  const [count, setCount] = useState(3)
  const [levels, setLevels] = useState<string[]>([
    'random',
    'heuristic',
    'montecarlo',
    'heuristic',
    'montecarlo',
    'heuristic',
  ])
  const [stack, setStack] = useState(1000)
  const [available, setAvailable] = useState<string[]>(['random', 'heuristic', 'montecarlo'])

  // o Expert só aparece quando o modelo treinado existe no backend
  useEffect(() => {
    api.getLevels().then((r) => setAvailable(r.levels)).catch(() => {})
  }, [])
  const levelOptions = LEVELS.filter((l) => available.includes(l.id))

  function pickMode(m: 'play' | 'watch') {
    setMode(m)
    if (m === 'watch' && count < 2) setCount(2)
    if (m === 'play' && count > 5) setCount(5)
  }

  const counts = mode === 'watch' ? [2, 3, 4, 5, 6] : [1, 2, 3, 4, 5]

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
      mode,
    })
  }

  return (
    <div className="setup">
      <div className="setup-card">
        <div className="setup-suit">♠</div>
        <h1 className="brand">Poker Arena</h1>
        <p className="tagline">Você contra a inteligência das máquinas.</p>

        <div className="mode-toggle">
          <button
            className={mode === 'play' ? 'mode-btn active' : 'mode-btn'}
            onClick={() => pickMode('play')}
          >
            🎮 Eu jogo
          </button>
          <button
            className={mode === 'watch' ? 'mode-btn active' : 'mode-btn'}
            onClick={() => pickMode('watch')}
          >
            👀 Assistir (só bots)
          </button>
        </div>

        <label className="field">
          <span>{mode === 'watch' ? 'Quantos bots disputam?' : 'Quantos bots na mesa?'}</span>
          <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
            {counts.map((n) => (
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
                {levelOptions.map((l) => (
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
          {busy ? 'Embaralhando…' : mode === 'watch' ? 'Assistir à partida' : 'Sentar à mesa'}
        </button>
        <p className="hint">
          {mode === 'watch'
            ? 'Os bots jogam sozinhos com as cartas abertas — você só assiste.'
            : 'Dica: rode o backend antes — '}
          {mode === 'play' && <code>uvicorn poker_arena.api.app:app</code>}
        </p>
      </div>
    </div>
  )
}

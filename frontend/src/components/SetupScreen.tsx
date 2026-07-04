import { useEffect, useState } from 'react'
import { api } from '../api'
import type { BotSpec, CreateConfig } from '../types'

const LEVELS = [
  { id: 'random', label: '🟢 Iniciante — joga no chute' },
  { id: 'heuristic', label: '🟡 Amador — joga por regras' },
  { id: 'montecarlo', label: '🟠 Intermediário — calcula chances' },
  { id: 'adaptive', label: '🧠 Adaptativo — aprende e explora você' },
  { id: 'expert', label: '🔴 Expert — IA treinada (solver + self-play)' },
]
const NAMES = ['Luna', 'Caio', 'Sofia', 'Alex', 'Maya', 'Rex', 'Theo', 'Nina', 'Vera']

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
    'montecarlo',
    'heuristic',
    'montecarlo',
  ])
  const [stack, setStack] = useState(1000)
  const [rebuy, setRebuy] = useState(true) // true = cash game (infinito) | false = torneio
  const [handLimit, setHandLimit] = useState(0) // 0 = sem limite
  // padrão enquanto /levels não responde (adaptive está SEMPRE disponível; expert só
  // aparece se o modelo treinado existir, então vem do backend)
  const [available, setAvailable] = useState<string[]>([
    'random',
    'heuristic',
    'montecarlo',
    'adaptive',
  ])

  // o Expert só aparece quando o modelo treinado existe no backend. Como o backend
  // pode estar SUBINDO quando esta tela abre, tenta de novo por alguns segundos —
  // senão o Expert "some" até um reload manual (era o bug relatado).
  useEffect(() => {
    let alive = true
    let tries = 0
    const load = () => {
      api
        .getLevels()
        .then((r) => {
          if (alive) setAvailable(r.levels)
        })
        .catch(() => {
          if (alive && tries++ < 10) setTimeout(load, 1000) // backend subindo? re-tenta
        })
    }
    load()
    return () => {
      alive = false
    }
  }, [])
  const levelOptions = LEVELS.filter((l) => available.includes(l.id))

  function pickMode(m: 'play' | 'watch') {
    setMode(m)
    if (m === 'watch' && count < 2) setCount(2)
    if (m === 'play' && count > 8) setCount(8) // você + 8 bots = mesa de 9
  }

  // até 9 jogadores: assistir = até 9 bots; jogar = você + até 8 bots
  const counts = mode === 'watch' ? [2, 3, 4, 5, 6, 7, 8, 9] : [1, 2, 3, 4, 5, 6, 7, 8]

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
      rebuy,
      hand_limit: handLimit || null,
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

        <label className="field">
          <span>Formato</span>
          <select value={rebuy ? 'cash' : 'tourney'} onChange={(e) => setRebuy(e.target.value === 'cash')}>
            <option value="cash">Cash game — nunca acaba (recompra ao zerar)</option>
            <option value="tourney">Torneio — até sobrar 1 (eliminação)</option>
          </select>
        </label>

        <label className="field">
          <span>Limite de mãos</span>
          <select value={handLimit} onChange={(e) => setHandLimit(Number(e.target.value))}>
            <option value={0}>Sem limite</option>
            <option value={30}>Parar em 30 mãos</option>
            <option value={50}>Parar em 50 mãos</option>
            <option value={100}>Parar em 100 mãos</option>
          </select>
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

        <div className="rg-note">
          <b>Aviso — projeto educacional.</b> A Poker Arena é um estudo de{' '}
          <b>probabilidade, estatística e IA</b>. Não há dinheiro real, apostas nem prêmios —
          as fichas são só pontos. No mundo real, poker envolve risco financeiro e o acaso
          domina o curto prazo; bots são proibidos em todo site de verdade. Se o jogo deixar
          de ser diversão para alguém: <b>CVV 188</b> (24h, gratuito) ·{' '}
          <a href="https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/jogo-responsavel" target="_blank" rel="noreferrer">
            gov.br/Jogo&nbsp;Responsável
          </a>{' '}
          ·{' '}
          <a href="https://www.jogadoresanonimos.com.br" target="_blank" rel="noreferrer">
            Jogadores&nbsp;Anônimos
          </a>
          .
        </div>
      </div>
    </div>
  )
}

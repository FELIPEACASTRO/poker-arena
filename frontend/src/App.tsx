import { useEffect, useState } from 'react'
import { api } from './api'
import ActionBar from './components/ActionBar'
import PokerTable from './components/PokerTable'
import SetupScreen from './components/SetupScreen'
import type { CreateConfig, TableState } from './types'

export default function App() {
  const [state, setState] = useState<TableState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [watch, setWatch] = useState(false)
  const [paused, setPaused] = useState(false)

  async function run(fn: () => Promise<TableState>) {
    setBusy(true)
    setError(null)
    try {
      setState(await fn())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // modo assistir: avança sozinho (jogada a jogada) com um respiro pra dar pra ver
  useEffect(() => {
    if (!state || !watch || paused || error) return
    let t = 0
    if (state.phase === 'bot_turn') {
      t = window.setTimeout(() => run(() => api.step(state.table_id)), 850)
    } else if (state.phase === 'hand_over') {
      t = window.setTimeout(() => run(() => api.nextHand(state.table_id)), 2600)
    }
    return () => clearTimeout(t)
  }, [state, watch, paused, error])

  if (!state) {
    return (
      <SetupScreen
        busy={busy}
        error={error}
        onCreate={(cfg: CreateConfig) => {
          setWatch(cfg.mode === 'watch')
          setPaused(false)
          run(() => api.createTable(cfg))
        }}
      />
    )
  }

  const read = state.opponent_read
  return (
    <div className="app">
      {read && read.samples >= 8 && (
        <div className="brain-banner">
          🧠 <b>Aprendi seu estilo</b> ({read.samples} jogadas): você desiste{' '}
          <b>{Math.round(read.fold_to_bet * 100)}%</b> das vezes diante de apostas
          {read.fold_to_bet > 0.55
            ? ' → vou te pressionar e blefar mais.'
            : read.fold_to_bet < 0.45
              ? ' → você paga muito, então aposto só com mão forte.'
              : ' → jogo equilibrado, por enquanto.'}
        </div>
      )}
      <PokerTable state={state} />
      <ActionBar
        state={state}
        busy={busy}
        error={error}
        watch={watch}
        paused={paused}
        onTogglePause={() => setPaused((p) => !p)}
        onAction={(type, amount = 0) => run(() => api.act(state.table_id, type, amount))}
        onNext={() => run(() => api.nextHand(state.table_id))}
        onLeave={() => {
          setState(null)
          setError(null)
          setWatch(false)
          setPaused(false)
        }}
      />
    </div>
  )
}

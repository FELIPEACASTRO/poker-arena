import { useState } from 'react'
import { api } from './api'
import ActionBar from './components/ActionBar'
import PokerTable from './components/PokerTable'
import SetupScreen from './components/SetupScreen'
import type { CreateConfig, TableState } from './types'

export default function App() {
  const [state, setState] = useState<TableState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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

  if (!state) {
    return (
      <SetupScreen
        busy={busy}
        error={error}
        onCreate={(cfg: CreateConfig) => run(() => api.createTable(cfg))}
      />
    )
  }

  return (
    <div className="app">
      <PokerTable state={state} />
      <ActionBar
        state={state}
        busy={busy}
        error={error}
        onAction={(type, amount = 0) => run(() => api.act(state.table_id, type, amount))}
        onNext={() => run(() => api.nextHand(state.table_id))}
        onLeave={() => {
          setState(null)
          setError(null)
        }}
      />
    </div>
  )
}

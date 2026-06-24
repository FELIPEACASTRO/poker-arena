import { useEffect } from 'react'
import { Cpu, FlaskConical, Gamepad2, LogOut } from 'lucide-react'
import ActionBar from './components/ActionBar'
import PokerTable from './components/PokerTable'
import SetupScreen from './components/SetupScreen'
import { useGame } from './store'

export default function App() {
  const { state, watch, paused, busy, error, create, act, next, step, togglePause, leave } =
    useGame()

  // modo laboratório: avança sozinho (jogada a jogada) com um respiro pra dar pra ver
  useEffect(() => {
    if (!state || !watch || paused || error) return
    let t = 0
    if (state.phase === 'bot_turn') t = window.setTimeout(() => step(), 850)
    else if (state.phase === 'hand_over') t = window.setTimeout(() => next(), 2600)
    return () => clearTimeout(t)
  }, [state, watch, paused, error, step, next])

  if (!state) {
    return <SetupScreen busy={busy} error={error} onCreate={create} />
  }

  const read = state.opponent_read
  return (
    <div className="lab-shell">
      <header className="lab-header">
        <div className="lab-brand">
          <span className="ico">
            <Cpu size={20} />
          </span>
          Poker Arena
          <span className="lab-tag">LAB</span>
        </div>
        <div className="lab-header-spacer" />
        <div className="lab-header-right">
          <span className="chip">
            {watch ? <FlaskConical size={14} /> : <Gamepad2 size={14} />}
            {watch ? 'Modo laboratório' : 'Você joga'}
          </span>
          <button className="ico-btn" onClick={leave} aria-label="Sair da mesa">
            <LogOut size={16} />
          </button>
        </div>
      </header>

      <main className="lab-main">
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
          onTogglePause={togglePause}
          onAction={act}
          onNext={next}
          onLeave={leave}
        />
      </main>
    </div>
  )
}

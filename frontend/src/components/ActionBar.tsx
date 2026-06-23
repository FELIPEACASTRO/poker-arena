import { useEffect, useState } from 'react'
import type { TableState } from '../types'

interface Props {
  state: TableState
  onAction: (type: string, amount?: number) => void
  onNext: () => void
  onLeave: () => void
  busy: boolean
  error: string | null
  watch?: boolean
  paused?: boolean
  onTogglePause?: () => void
}

function winnerNames(state: TableState): string {
  return (state.winners ?? [])
    .map((i) => state.seats.find((s) => s.seat === i)?.name ?? `#${i}`)
    .join(', ')
}

export default function ActionBar({
  state,
  onAction,
  onNext,
  onLeave,
  busy,
  error,
  watch = false,
  paused = false,
  onTogglePause,
}: Props) {
  const legal = state.legal
  const minR = legal?.min_raise_to ?? 0
  const maxR = legal?.max_raise_to ?? 0
  const [raiseTo, setRaiseTo] = useState(minR)

  useEffect(() => {
    setRaiseTo(minR)
  }, [minR, state.hand_number])

  if (watch) {
    const actor = state.seats.find((s) => s.is_turn)?.name
    return (
      <div className="actionbar">
        {error && <div className="error">⚠ {error}</div>}
        <div className="actions result-row">
          {state.phase === 'bot_turn' && (
            <span className="result">👀 Assistindo — <b>{actor}</b> vai jogar…</span>
          )}
          {state.phase === 'hand_over' && (
            <span className="result">🏅 Venceu: <b>{winnerNames(state)}</b> — próxima mão…</span>
          )}
          {state.phase === 'game_over' ? (
            <>
              <span className="result">🏆 Campeão: <b>{winnerNames(state)}</b></span>
              <button className="btn" onClick={onLeave}>Nova partida</button>
            </>
          ) : (
            <>
              <button className="btn btn-call" onClick={onTogglePause}>
                {paused ? '▶ Continuar' : '⏸ Pausar'}
              </button>
              <button className="btn" onClick={onLeave}>Sair</button>
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="actionbar">
      {error && <div className="error">⚠ {error}</div>}

      {state.phase === 'human_turn' && legal && (
        <div className="actions">
          {legal.actions.includes('fold') && (
            <button className="btn btn-fold" disabled={busy} onClick={() => onAction('fold')}>
              Desistir
            </button>
          )}
          {legal.actions.includes('check') && (
            <button className="btn" disabled={busy} onClick={() => onAction('check')}>
              Passar
            </button>
          )}
          {legal.actions.includes('call') && (
            <button className="btn btn-call" disabled={busy} onClick={() => onAction('call')}>
              Pagar <b>{legal.to_call}</b>
            </button>
          )}
          {legal.actions.includes('raise') && (
            <div className="raise-group">
              <input
                type="range"
                min={minR}
                max={maxR}
                value={raiseTo}
                onChange={(e) => setRaiseTo(Number(e.target.value))}
              />
              <button
                className="btn btn-raise"
                disabled={busy}
                onClick={() => onAction('raise', raiseTo)}
              >
                Aumentar p/ <b>{raiseTo}</b>
              </button>
            </div>
          )}
          {legal.actions.includes('all_in') && (
            <button className="btn btn-allin" disabled={busy} onClick={() => onAction('all_in')}>
              All-in
            </button>
          )}
        </div>
      )}

      {state.phase === 'hand_over' && (
        <div className="actions result-row">
          <span className="result">🏅 Venceu: <b>{winnerNames(state)}</b></span>
          <button className="btn btn-next" disabled={busy} onClick={onNext}>
            Próxima mão →
          </button>
        </div>
      )}

      {state.phase === 'game_over' && (
        <div className="actions result-row">
          <span className="result">🏆 Fim de jogo — campeão: <b>{winnerNames(state)}</b></span>
          <button className="btn" onClick={onLeave}>Nova partida</button>
        </div>
      )}
    </div>
  )
}

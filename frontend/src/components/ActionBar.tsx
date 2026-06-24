import { useEffect, useState } from 'react'
import { AlertTriangle, Eye, LogOut, Pause, Play, Trophy } from 'lucide-react'
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

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

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

  // reseta o slider quando muda a mão ou o mínimo legal (padrão React, sem efeito)
  const resetKey = `${state.hand_number}:${minR}`
  const [seenKey, setSeenKey] = useState(resetKey)
  if (seenKey !== resetKey) {
    setSeenKey(resetKey)
    setRaiseTo(minR)
  }

  // tamanhos de aposta relativos ao pote (poker de verdade)
  const me = state.seats.find((s) => s.is_turn)
  const callTo = (me?.current_bet ?? 0) + (legal?.to_call ?? 0)
  const potAfterCall = state.pot + (legal?.to_call ?? 0)
  const sizeTo = (frac: number) => clamp(Math.round(callTo + frac * potAfterCall), minR, maxR)
  const canRaise = !!legal?.actions.includes('raise')

  // atalhos de teclado (só na vez do humano)
  useEffect(() => {
    if (watch || busy) return
    const onKey = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase()
      if (state.phase === 'hand_over' && (k === 'enter' || k === ' ')) return onNext()
      if (state.phase !== 'human_turn' || !legal) return
      if (k === 'f' && legal.actions.includes('fold')) onAction('fold')
      else if (k === 'c') {
        if (legal.actions.includes('check')) onAction('check')
        else if (legal.actions.includes('call')) onAction('call')
      } else if (k === 'r' && canRaise) onAction('raise', raiseTo)
      else if (k === 'a' && legal.actions.includes('all_in')) onAction('all_in')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [watch, busy, state.phase, legal, canRaise, raiseTo, onAction, onNext])

  if (watch) {
    const actor = state.seats.find((s) => s.is_turn)?.name
    return (
      <div className="actionbar">
        {error && (
          <div className="error">
            <AlertTriangle size={14} /> {error}
          </div>
        )}
        <div className="actions result-row">
          {state.phase === 'bot_turn' && (
            <span className="result">
              <Eye size={15} /> Assistindo — <b>{actor}</b> vai jogar…
            </span>
          )}
          {state.phase === 'hand_over' && (
            <span className="result">
              <Trophy size={15} /> Venceu: <b>{winnerNames(state)}</b> — próxima mão…
            </span>
          )}
          {state.phase === 'game_over' ? (
            <>
              <span className="result">
                <Trophy size={15} /> Campeão: <b>{winnerNames(state)}</b>
              </span>
              <button className="btn" onClick={onLeave}>
                Nova partida
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-call" onClick={onTogglePause}>
                {paused ? <Play size={15} /> : <Pause size={15} />}
                {paused ? 'Continuar' : 'Pausar'}
              </button>
              <button className="btn" onClick={onLeave}>
                <LogOut size={15} /> Sair
              </button>
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="actionbar">
      {error && (
        <div className="error">
          <AlertTriangle size={14} /> {error}
        </div>
      )}

      {state.phase === 'human_turn' && legal && (
        <div className="actions">
          {legal.actions.includes('fold') && (
            <button className="btn btn-fold" disabled={busy} onClick={() => onAction('fold')}>
              Desistir <kbd>F</kbd>
            </button>
          )}
          {legal.actions.includes('check') && (
            <button className="btn" disabled={busy} onClick={() => onAction('check')}>
              Passar <kbd>C</kbd>
            </button>
          )}
          {legal.actions.includes('call') && (
            <button className="btn btn-call" disabled={busy} onClick={() => onAction('call')}>
              Pagar <b className="mono">{legal.to_call}</b> <kbd>C</kbd>
            </button>
          )}
          {canRaise && (
            <div className="raise-group">
              <div className="raise-presets">
                <button className="raise-chip" onClick={() => setRaiseTo(sizeTo(0.5))}>
                  ½ pote
                </button>
                <button className="raise-chip" onClick={() => setRaiseTo(sizeTo(0.75))}>
                  ¾ pote
                </button>
                <button className="raise-chip" onClick={() => setRaiseTo(sizeTo(1))}>
                  pote
                </button>
                <button className="raise-chip" onClick={() => setRaiseTo(maxR)}>
                  máx
                </button>
              </div>
              <div className="raise-row">
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
                  Aumentar p/ <b className="mono">{raiseTo}</b> <kbd>R</kbd>
                </button>
              </div>
            </div>
          )}
          {legal.actions.includes('all_in') && (
            <button className="btn btn-allin" disabled={busy} onClick={() => onAction('all_in')}>
              All-in <kbd>A</kbd>
            </button>
          )}
        </div>
      )}

      {state.phase === 'hand_over' && (
        <div className="actions result-row">
          <span className="result">
            <Trophy size={15} /> Venceu: <b>{winnerNames(state)}</b>
          </span>
          <button className="btn btn-next" disabled={busy} onClick={onNext}>
            Próxima mão <kbd>↵</kbd>
          </button>
        </div>
      )}

      {state.phase === 'game_over' && (
        <div className="actions result-row">
          <span className="result">
            <Trophy size={15} /> Fim de jogo — campeão: <b>{winnerNames(state)}</b>
          </span>
          <button className="btn" onClick={onLeave}>
            Nova partida
          </button>
        </div>
      )}
    </div>
  )
}

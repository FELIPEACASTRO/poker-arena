import { Brain, Lightbulb } from 'lucide-react'
import { motion } from 'framer-motion'
import { levelName } from '../levels'
import { useGame } from '../store'

const VERDICT: Record<string, { c: string; icon: string; t: string }> = {
  good: { c: 'var(--pos)', icon: '✓', t: 'boa' },
  ok: { c: 'var(--lvl-heuristic)', icon: '!', t: 'arriscada' },
  bad: { c: 'var(--neg)', icon: '✕', t: 'ruim' },
}

/** Modo Laboratório: como o competidor que acabou de jogar está pensando. */
export default function ReasoningCard() {
  const { state, colors } = useGame()
  const r = state?.reasoning
  if (!r) return null
  const color = colors[r.name] ?? 'var(--accent)'
  const headline = r.headline.replace(r.name, '').trim() // só o "vai PAGAR"

  return (
    <motion.div
      className="apanel reason"
      key={r.seat + '-' + r.action + '-' + r.pot}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <div className="apanel-h">
        <Brain size={14} /> Como o competidor está pensando
      </div>

      <div className="reason-head">
        <span className="reason-dot" style={{ background: color }} />
        <span className="reason-name" style={{ color }}>
          {r.name}
        </span>
        <span className="reason-lvl">{levelName(r.level)}</span>
        <span className="reason-headline">{headline}</span>
      </div>

      <p className="reason-how">
        <Lightbulb size={13} /> {r.how_it_thinks}
      </p>

      <div className="reason-saw">
        {r.hand_label && (
          <span>
            <b>{r.hand_label}</b>
            <small>mão</small>
          </span>
        )}
        <span>
          <b>{r.equity_pct}%</b>
          <small>chance real</small>
        </span>
        <span>
          <b>{r.pot}</b>
          <small>pote</small>
        </span>
        <span>
          <b>{r.to_call}</b>
          <small>pra pagar</small>
        </span>
        <span>
          <b>{r.pot_odds_pct}%</b>
          <small>preço (pot odds)</small>
        </span>
      </div>

      {r.signal_label && (
        <div className="reason-signal">
          <span className="reason-signal-k">
            o que ele calculou: <b>{r.signal_label}</b>
          </span>
          {r.signal_value != null && (
            <div className="reason-bar">
              <span style={{ width: `${Math.round(r.signal_value * 100)}%`, background: color }} />
            </div>
          )}
        </div>
      )}

      <div className="reason-opts-h">As jogadas possíveis — e por quê</div>
      <div className="reason-opts">
        {r.options.map((o, i) => (
          <div
            key={i}
            className={'reason-opt' + (o.chosen ? ' is-chosen' : '')}
            style={{ borderLeftColor: VERDICT[o.verdict]?.c }}
          >
            <span className="reason-opt-badge" style={{ background: VERDICT[o.verdict]?.c }}>
              {VERDICT[o.verdict]?.icon}
            </span>
            <div className="reason-opt-body">
              <span className="reason-opt-label">
                {o.label}
                {o.chosen && <em> — foi o que ele fez</em>}
              </span>
              <span className="reason-opt-reason">{o.reason}</span>
            </div>
          </div>
        ))}
      </div>

      <p className="reason-why">➡️ {r.why_chosen}</p>
    </motion.div>
  )
}

import { motion } from 'framer-motion'
import { Crown, Trophy } from 'lucide-react'
import { levelColor } from '../levels'
import { useGame } from '../store'

const levelOf = (kind: string) => (kind.startsWith('bot:') ? kind.slice(4) : kind)

export default function WinStats() {
  const { state, wins, handsDone } = useGame()
  if (!state) return null

  // métrica honesta: quem tem mais FICHAS (lucro real), não quem vence mais mãos
  const total = state.seats.reduce((a, s) => a + s.stack, 0) || 1
  const rows = state.seats
    .map((s) => ({
      seat: s.seat,
      name: s.name,
      color: levelColor(levelOf(s.kind)),
      chips: s.stack,
      pct: Math.round((s.stack / total) * 100), // % das fichas da mesa
      handPct: handsDone ? Math.round(((wins[s.seat] ?? 0) / handsDone) * 100) : 0,
    }))
    .sort((a, b) => b.chips - a.chips)

  const leader = rows[0]

  return (
    <div className="winstats">
      <div className="winstats-head">
        <span className="winstats-title">
          <Trophy size={15} /> Quem mais ganha
        </span>
        <span className="mono winstats-hands">{handsDone} mãos</span>
      </div>

      <div className="winstats-leader">
        <Crown size={16} />
        <span className="winstats-leader-name" style={{ color: leader.color }}>
          {leader.name}
        </span>
        <span className="winstats-leader-pct mono">{leader.pct}%</span>
        <span className="winstats-leader-sub">das fichas da mesa</span>
      </div>

      <div className="winstats-list">
        {rows.map((r, i) => (
          <motion.div
            layout
            key={r.seat}
            transition={{ type: 'spring', stiffness: 480, damping: 38 }}
            className={'winstats-row' + (i === 0 ? ' is-lead' : '')}
            title={`${r.chips.toLocaleString('pt-BR')} fichas · vence ${r.handPct}% das mãos`}
          >
            <span className="winstats-dot" style={{ background: r.color }} />
            <span className="winstats-name">{r.name}</span>
            <span className="winstats-chips mono">{r.chips.toLocaleString('pt-BR')}</span>
            <span className="winstats-bar">
              <motion.span
                animate={{ width: `${r.pct}%` }}
                transition={{ type: 'spring', stiffness: 200, damping: 26 }}
                style={{ background: r.color }}
              />
            </span>
            <span className="winstats-pct mono">{r.pct}%</span>
          </motion.div>
        ))}
      </div>
    </div>
  )
}

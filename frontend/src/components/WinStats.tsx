import { motion } from 'framer-motion'
import { Crown, Trophy } from 'lucide-react'
import { useGame } from '../store'

const LVL_COLOR: Record<string, string> = {
  random: 'var(--lvl-random)',
  heuristic: 'var(--lvl-heuristic)',
  montecarlo: 'var(--lvl-montecarlo)',
  adaptive: 'var(--lvl-adaptive)',
  expert: 'var(--lvl-expert)',
  human: 'var(--accent)',
}
const levelOf = (kind: string) => (kind.startsWith('bot:') ? kind.slice(4) : kind)

export default function WinStats() {
  const { state, wins, handsDone } = useGame()
  if (!state) return null

  const rows = state.seats
    .map((s) => {
      const w = wins[s.seat] ?? 0
      return {
        seat: s.seat,
        name: s.name,
        color: LVL_COLOR[levelOf(s.kind)] ?? 'var(--text-dim)',
        wins: w,
        pct: handsDone ? Math.round((w / handsDone) * 100) : 0,
      }
    })
    .sort((a, b) => b.pct - a.pct || b.wins - a.wins)

  const leader = rows[0]

  return (
    <div className="winstats">
      <div className="winstats-head">
        <span className="winstats-title">
          <Trophy size={15} /> Quem mais ganha
        </span>
        <span className="mono winstats-hands">{handsDone} mãos</span>
      </div>

      {handsDone === 0 ? (
        <p className="winstats-empty">jogue algumas mãos pra ver o ranking…</p>
      ) : (
        <>
          <div className="winstats-leader">
            <Crown size={16} />
            <span className="winstats-leader-name" style={{ color: leader.color }}>
              {leader.name}
            </span>
            <span className="winstats-leader-pct mono">{leader.pct}%</span>
            <span className="winstats-leader-sub">vence mais que todos</span>
          </div>

          <div className="winstats-list">
            {rows.map((r, i) => (
              <motion.div
                layout
                key={r.seat}
                transition={{ type: 'spring', stiffness: 480, damping: 38 }}
                className={'winstats-row' + (i === 0 ? ' is-lead' : '')}
              >
                <span className="winstats-dot" style={{ background: r.color }} />
                <span className="winstats-name">{r.name}</span>
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
        </>
      )}
    </div>
  )
}

import { motion } from 'framer-motion'
import type { TableState } from '../types'
import { CardFace } from './Card'
import SeatView from './Seat'

// posições ao redor da mesa oval (até 6 cadeiras; o humano sempre embaixo)
const SLOTS = [
  'slot-bottom',
  'slot-left-low',
  'slot-left-high',
  'slot-top',
  'slot-right-high',
  'slot-right-low',
]

export default function PokerTable({ state }: { state: TableState }) {
  const showWinners = state.phase === 'hand_over' || state.phase === 'game_over'
  const winners = new Set(state.winners ?? [])
  return (
    <div className="table-wrap">
      <div className="felt">
        <div className="felt-glow" />
        <div className="board">
          {[0, 1, 2, 3, 4].map((i) => {
            const c = state.board[i]
            return c ? (
              <motion.div
                key={c}
                className="board-card"
                initial={{ opacity: 0, y: -16, rotateY: 55, scale: 0.82 }}
                animate={{ opacity: 1, y: 0, rotateY: 0, scale: 1 }}
                transition={{ delay: i * 0.08, type: 'spring', stiffness: 320, damping: 22 }}
              >
                <CardFace code={c} />
              </motion.div>
            ) : (
              <span key={`slot-${i}`} className="board-slot" />
            )
          })}
        </div>

        <div className="pot-badge">
          <span className="pot-label">POTE</span>
          <motion.span
            key={state.pot}
            className="pot-value"
            initial={{ scale: 1.28 }}
            animate={{ scale: 1 }}
            transition={{ type: 'spring', stiffness: 420, damping: 16 }}
          >
            {state.pot.toLocaleString('pt-BR')}
          </motion.span>
        </div>

        {state.seats.map((s, i) => (
          <div key={s.seat} className={`seat-slot ${SLOTS[i] ?? ''}`}>
            <SeatView seat={s} isWinner={showWinners && winners.has(s.seat)} />
          </div>
        ))}
      </div>
    </div>
  )
}

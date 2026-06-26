import type { CSSProperties } from 'react'
import { motion } from 'framer-motion'
import { useGame } from '../store'
import type { TableState } from '../types'
import { CardFace } from './Card'
import FeltGraphic from './FeltGraphic'
import SeatView from './Seat'

// posição de cada cadeira (2 a 9): distribuídas UNIFORMEMENTE ao redor da elipse,
// com você (cadeira 0) no centro de baixo; as demais seguem pela esquerda, sobem,
// cruzam o topo e descem pela direita — preenchendo a mesa toda.
function seatStyle(i: number, n: number): CSSProperties {
  const angle = ((90 + (360 / n) * i) * Math.PI) / 180 // 90° = base; gira ao redor
  const left = 50 + 50 * Math.cos(angle) // raio horizontal (mesa larga)
  const top = 50 + 53 * Math.sin(angle) // raio vertical (assentos um pouco pra fora)
  return { left: `${left.toFixed(1)}%`, top: `${top.toFixed(1)}%`, transform: 'translate(-50%, -50%)' }
}

export default function PokerTable({
  state,
  onPositionClick,
}: {
  state: TableState
  onPositionClick?: (pos: string) => void
}) {
  const colors = useGame((s) => s.colors)
  const showWinners = state.phase === 'hand_over' || state.phase === 'game_over'
  const winners = new Set(state.winners ?? [])
  return (
    <div className="table-wrap">
      <div className="felt">
        <div className="felt-glow" />
        <FeltGraphic />
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

        {state.pot > 0 && (
          <div className="pot-chips" aria-hidden="true">
            <span className="pchip" style={{ background: '#1a1a1a' }} />
            <span className="pchip" style={{ background: '#1d9e75' }} />
            <span className="pchip" style={{ background: '#185fa5' }} />
            <span className="pchip" style={{ background: '#a32d2d' }} />
          </div>
        )}

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
          <div key={s.seat} className="seat-slot" style={seatStyle(i, state.seats.length)}>
            <SeatView
              seat={s}
              color={colors[s.name]}
              isWinner={showWinners && winners.has(s.seat)}
              onPositionClick={onPositionClick}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

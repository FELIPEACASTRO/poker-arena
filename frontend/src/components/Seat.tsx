import { AnimatePresence, motion } from 'framer-motion'
import { CircleUserRound, Trophy } from 'lucide-react'
import type { Seat } from '../types'
import { CardBack, CardFace } from './Card'

const LABEL: Record<string, string> = {
  human: 'Você',
  random: 'Iniciante',
  heuristic: 'Amador',
  montecarlo: 'Intermediário',
  adaptive: 'Adaptativo',
  expert: 'Expert',
}
const levelOf = (kind: string) => (kind.startsWith('bot:') ? kind.slice(4) : 'human')

export default function SeatView({
  seat,
  color,
  isWinner = false,
}: {
  seat: Seat
  color?: string
  isWinner?: boolean
}) {
  const level = levelOf(seat.kind)
  const isHuman = level === 'human'
  const folded = seat.status === 'folded'

  return (
    <div
      data-level={level}
      className={[
        'seat',
        isHuman ? 'seat-human' : '',
        seat.is_turn ? 'is-turn' : '',
        folded ? 'is-folded' : '',
        isWinner ? 'is-winner' : '',
      ].join(' ')}
    >
      <AnimatePresence>
        {isWinner && (
          <motion.div
            className="seat-win"
            initial={{ opacity: 0, scale: 0.5, y: 6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ type: 'spring', stiffness: 460, damping: 18 }}
          >
            <Trophy size={12} /> venceu
          </motion.div>
        )}
      </AnimatePresence>
      <div className="seat-cards">
        {seat.cards ? (
          seat.cards.map((c, i) => <CardFace key={i} code={c} />)
        ) : (
          <>
            <CardBack />
            <CardBack />
          </>
        )}
      </div>

      <div className="seat-plate">
        <div className="seat-top">
          <span
            className="seat-cdot"
            style={color ? { background: color, boxShadow: `0 0 6px ${color}` } : undefined}
          />
          <CircleUserRound size={15} className="seat-ava" style={color ? { color } : undefined} />
          <span className="seat-name">{seat.name}</span>
          {seat.is_button && <span className="dealer-chip">D</span>}
        </div>
        <div className="seat-kind">{LABEL[level] ?? level}</div>
        <div className="seat-stack mono">{seat.stack.toLocaleString('pt-BR')}</div>
        {seat.current_bet > 0 && (
          <motion.div
            key={seat.current_bet}
            className="seat-bet mono"
            initial={{ scale: 0.4, opacity: 0, y: -4 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            transition={{ type: 'spring', stiffness: 520, damping: 20 }}
          >
            {seat.current_bet}
          </motion.div>
        )}
      </div>
    </div>
  )
}

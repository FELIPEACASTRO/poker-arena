import { CircleUserRound } from 'lucide-react'
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

export default function SeatView({ seat }: { seat: Seat }) {
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
      ].join(' ')}
    >
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
          <CircleUserRound size={15} className="seat-ava" />
          <span className="seat-name">{seat.name}</span>
          {seat.is_button && <span className="dealer-chip">D</span>}
        </div>
        <div className="seat-kind">{LABEL[level] ?? level}</div>
        <div className="seat-stack mono">{seat.stack.toLocaleString('pt-BR')}</div>
        {seat.current_bet > 0 && <div className="seat-bet mono">{seat.current_bet}</div>}
      </div>
    </div>
  )
}

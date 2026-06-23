import type { Seat } from '../types'
import { CardBack, CardFace } from './Card'

export default function SeatView({ seat }: { seat: Seat }) {
  const isHuman = seat.kind === 'human'
  const label = isHuman ? 'VOCÊ' : seat.kind.replace('bot:', '').toUpperCase()
  const folded = seat.status === 'folded'

  return (
    <div
      className={[
        'seat',
        isHuman ? 'seat-human' : '',
        seat.is_turn ? 'is-turn' : '',
        folded ? 'is-folded' : '',
      ].join(' ')}
    >
      <div className="seat-cards">
        {seat.cards
          ? seat.cards.map((c, i) => <CardFace key={i} code={c} />)
          : (
            <>
              <CardBack />
              <CardBack />
            </>
          )}
      </div>

      <div className="seat-plate">
        <div className="seat-name">
          {seat.name}
          {seat.is_button && <span className="dealer-chip">D</span>}
        </div>
        <div className="seat-kind">{label}</div>
        <div className="seat-stack">{seat.stack.toLocaleString('pt-BR')}</div>
        {seat.current_bet > 0 && <div className="seat-bet">{seat.current_bet}</div>}
      </div>
    </div>
  )
}

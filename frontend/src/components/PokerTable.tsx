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
  return (
    <div className="table-wrap">
      <div className="felt">
        <div className="felt-glow" />
        <div className="board">
          {state.board.length === 0 ? (
            <span className="board-empty">— aguardando as cartas —</span>
          ) : (
            state.board.map((c, i) => (
              <div key={i} className="board-card" style={{ animationDelay: `${i * 70}ms` }}>
                <CardFace code={c} />
              </div>
            ))
          )}
        </div>

        <div className="pot-badge">
          <span className="pot-label">POTE</span>
          <span className="pot-value">{state.pot.toLocaleString('pt-BR')}</span>
        </div>

        {state.seats.map((s, i) => (
          <div key={s.seat} className={`seat-slot ${SLOTS[i] ?? ''}`}>
            <SeatView seat={s} />
          </div>
        ))}
      </div>
    </div>
  )
}

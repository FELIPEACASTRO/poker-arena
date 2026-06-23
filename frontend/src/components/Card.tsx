const SUIT: Record<string, string> = { s: '♠', h: '♥', d: '♦', c: '♣' }
const RED = new Set(['h', 'd'])

export function CardFace({ code }: { code: string }) {
  const rank = code.slice(0, -1)
  const suit = code.slice(-1)
  return (
    <div className={`card ${RED.has(suit) ? 'red' : 'black'}`}>
      <span className="card-rank">{rank}</span>
      <span className="card-suit">{SUIT[suit] ?? suit}</span>
    </div>
  )
}

export function CardBack() {
  return <div className="card card-back" />
}

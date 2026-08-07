// Camada decorativa do feltro (estilo cassino clássico): linha de aposta em
// "estádio" + florituras douradas no topo e na base. Puro SVG, escala com a mesa.
const GOLD = '#c39a55'

function Flourish({ cy, flip }: { cy: number; flip: boolean }) {
  const d = flip ? -1 : 1
  return (
    <g stroke={GOLD} strokeOpacity="0.7" strokeWidth="2" strokeLinecap="round" fill="none">
      <path d={`M268 ${cy} q34 ${4 * d} 56 ${-2 * d}`} />
      <path d={`M392 ${cy} q-34 ${4 * d} -56 ${-2 * d}`} />
      <line x1="236" y1={cy} x2="268" y2={cy} />
      <line x1="424" y1={cy} x2="392" y2={cy} />
      <path
        d={`M330 ${cy - 10 * d} l6 ${9 * d} l-6 ${9 * d} l-6 ${-9 * d} z`}
        fill={GOLD}
        fillOpacity="0.85"
        stroke="none"
      />
      <circle cx="236" cy={cy} r="2.4" fill={GOLD} stroke="none" />
      <circle cx="424" cy={cy} r="2.4" fill={GOLD} stroke="none" />
    </g>
  )
}

export default function FeltGraphic() {
  return (
    <svg
      className="felt-graphic"
      viewBox="0 0 660 300"
      fill="none"
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
    >
      <rect
        x="66"
        y="96"
        width="528"
        height="108"
        rx="54"
        stroke={GOLD}
        strokeOpacity="0.42"
        strokeWidth="2"
      />
      <Flourish cy={88} flip={false} />
      <Flourish cy={212} flip />
    </svg>
  )
}

// Cor por COMPETIDOR (não por nível) — para distinguir cada um nas telas.
export const PALETTE = [
  '#34d399', // verde
  '#60a5fa', // azul
  '#fbbf24', // dourado
  '#f472b6', // rosa
  '#c084fc', // roxo
  '#fb923c', // laranja
  '#2dd4bf', // turquesa
  '#f87171', // vermelho
  '#a3e635', // lima
  '#38bdf8', // céu
  '#e879f9', // magenta
  '#fde047', // amarelo
]

/** Cor estável por NOME: mantém a já atribuída e dá uma cor livre a cada novo
 *  jogador, garantindo que os jogadores ativos tenham cores distintas. */
export function assignColors(
  prev: Record<string, string>,
  names: string[],
): Record<string, string> {
  const active = [...new Set(names)]
  const next: Record<string, string> = {}
  const used = new Set<string>()
  for (const n of active) {
    if (prev[n]) {
      next[n] = prev[n]
      used.add(prev[n])
    }
  }
  for (const n of active) {
    if (next[n]) continue
    const free = PALETTE.find((c) => !used.has(c)) ?? PALETTE[active.indexOf(n) % PALETTE.length]
    next[n] = free
    used.add(free)
  }
  return next
}

/** Mapa de cores a partir de um conjunto de nomes (sem estado anterior). */
export const colorMap = (names: string[]): Record<string, string> => assignColors({}, names)

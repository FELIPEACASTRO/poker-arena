export const STANDARD_POSITIONS = ['UTG', 'UTG+1', 'MP', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'] as const
export type StandardPosition = (typeof STANDARD_POSITIONS)[number]

export function canonicalPosition(position?: string | null): StandardPosition | '' {
  if (!position) return ''
  const candidate = position.toUpperCase()
  return STANDARD_POSITIONS.includes(candidate as StandardPosition)
    ? (candidate as StandardPosition)
    : ''
}

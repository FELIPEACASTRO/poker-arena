import { describe, expect, it } from 'vitest'
import { canonicalPosition, STANDARD_POSITIONS } from './positions'

describe('ontologia de posições', () => {
  it('expõe exatamente a taxonomia canônica de nove posições', () => {
    expect(STANDARD_POSITIONS).toEqual(['UTG', 'UTG+1', 'MP', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'])
  })

  it('normaliza caixa sem inventar posição desconhecida', () => {
    expect(canonicalPosition('co')).toBe('CO')
    expect(canonicalPosition('posição-inválida')).toBe('')
  })
})

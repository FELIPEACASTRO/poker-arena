import { describe, expect, it } from 'vitest'
import { fitWithin } from './capture'

describe('captura de tela', () => {
  it('reduz quadros grandes preservando proporção', () => {
    expect(fitWithin(3840, 2160, 1280)).toEqual({ width: 1280, height: 720 })
    expect(fitWithin(800, 600, 1280)).toEqual({ width: 800, height: 600 })
  })
})

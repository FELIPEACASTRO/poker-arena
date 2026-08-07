// @ts-expect-error O runtime do Vitest fornece node:fs; o bundle web não instala tipos Node.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('entrega offline e cientificamente cautelosa', () => {
  it('não depende de Google Fonts', () => {
    expect(read('../index.html')).not.toContain('fonts.googleapis.com')
    expect(read('../index.html')).not.toContain('fonts.gstatic.com')
  })

  it('lazy-loads telas modais pesadas', () => {
    const app = read('./App.tsx')
    expect(app).toContain('lazy(')
    expect(app).not.toMatch(/import GuideScreen from/)
    expect(app).not.toMatch(/import CopilotScreen from/)
  })

  it('remove ou qualifica claims locais sem artefato reproduzível', () => {
    const guide = read('./components/GuideScreen.tsx')
    expect(guide).not.toContain('+450')
    expect(guide).not.toContain('a equity é precisa')
    expect(guide).not.toContain('da mesma família de ideias')
    expect(guide).not.toContain('ciência real')
  })

  it('mantém contraste AA para texto pequeno mais fraco', () => {
    const css = read('./theme.css')
    const hex = css.match(/--text-faint:\s*(#[0-9a-f]{6})/i)?.[1]
    expect(hex).toBeTruthy()
    const lum = (color: string) => {
      const channels = color.slice(1).match(/../g)!.map((v) => Number.parseInt(v, 16) / 255)
        .map((v) => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    }
    const ratio = (lum(hex!) + 0.05) / (lum('#1c2533') + 0.05)
    expect(ratio).toBeGreaterThanOrEqual(4.5)
  })
})

import { chromium } from '@playwright/test'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const root = path.resolve(import.meta.dirname, '..', '..')
const htmlPath = path.join(root, 'docs', 'GUIA_DE_NAVEGACAO_POKER_ARENA.html')
const pdfPath = path.join(root, 'docs', 'GUIA_DE_NAVEGACAO_POKER_ARENA.pdf')

const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  const context = await browser.newContext({ locale: 'pt-BR' })
  const page = await context.newPage()
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'networkidle' })
  await page.emulateMedia({ media: 'print' })
  await page.pdf({
    path: pdfPath,
    format: 'A4',
    printBackground: true,
    preferCSSPageSize: true,
    displayHeaderFooter: false,
  })
  await context.close()
  process.stdout.write(`${pdfPath}\n`)
} finally {
  await browser.close()
}

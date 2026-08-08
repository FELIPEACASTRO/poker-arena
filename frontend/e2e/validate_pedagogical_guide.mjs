import { chromium } from '@playwright/test'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const root = path.resolve(import.meta.dirname, '..', '..')
const guidePath = path.join(root, 'docs', 'GUIA_PEDAGOGICO_POKER_ARENA.html')
const screenshotPath = path.join(root, 'docs', 'assets', 'navigation-guide', '04-guia-pedagogico.png')
const browser = await chromium.launch({ channel: 'msedge', headless: true })

const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'pt-BR' })
  const runtimeErrors = []
  page.on('pageerror', (error) => runtimeErrors.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() === 'error') runtimeErrors.push(`console: ${message.text()}`)
  })

  await page.goto(pathToFileURL(guidePath).href, { waitUntil: 'networkidle' })
  assert(await page.title() === 'Como o Poker Arena funciona — guia pedagógico visual', 'Título inesperado.')
  assert(await page.locator('html').getAttribute('lang') === 'pt-BR', 'Idioma do documento está ausente ou incorreto.')
  assert(await page.locator('main .chapter').count() === 16, 'O guia deve conter 16 capítulos.')
  assert(await page.getByRole('heading', { level: 1 }).count() === 1, 'O guia deve ter um único H1.')
  assert(await page.locator('.learning-goals li').count() === 4, 'O contrato deve declarar quatro objetivos observáveis.')
  assert(await page.locator('.quiz').count() === 6, 'O guia deve conter seis checkpoints de recuperação.')
  assert(await page.locator('.exercise').count() >= 2, 'O guia deve exigir produção ativa, não apenas reconhecimento.')
  assert(
    (await page.locator('#captura').textContent())?.includes('Outro monitor (recomendado)')
      && (await page.locator('#captura').textContent())?.includes('Mesmo monitor')
      && (await page.locator('#captura').textContent())?.includes('número físico do monitor'),
    'O capítulo de captura deve ensinar os dois modos e o limite de verificação do navegador.',
  )
  assert(
    (await page.locator('#checkpointStatus').textContent())?.includes('0 de 6'),
    'O progresso inicial dos checkpoints está incorreto.',
  )

  const duplicateIds = await page.locator('[id]').evaluateAll((elements) => {
    const counts = new Map()
    elements.forEach((element) => counts.set(element.id, (counts.get(element.id) || 0) + 1))
    return [...counts.entries()].filter(([, count]) => count > 1).map(([id]) => id)
  })
  assert(duplicateIds.length === 0, `IDs duplicados: ${duplicateIds.join(', ')}`)
  const unnamedButtons = await page.locator('button').evaluateAll((buttons) => buttons
    .filter((button) => !button.textContent.trim() && !button.getAttribute('aria-label') && !button.title)
    .map((button) => button.outerHTML))
  assert(unnamedButtons.length === 0, `Botões sem nome acessível: ${unnamedButtons.join(' | ')}`)

  const assetReport = await page.locator('img').evaluateAll((images) => images.map((image) => ({
    alt: image.getAttribute('alt'),
    complete: image.complete,
    height: image.naturalHeight,
    src: image.getAttribute('src'),
    width: image.naturalWidth,
  })))
  assert(assetReport.every((item) => item.alt !== null), 'Toda imagem deve ter atributo alt.')
  assert(assetReport.every((item) => item.complete && item.width > 0 && item.height > 0), `Imagem inválida: ${JSON.stringify(assetReport)}`)

  const brokenAnchors = await page.locator('a[href^="#"]').evaluateAll((links) =>
    links
      .map((link) => link.getAttribute('href'))
      .filter((href) => href && !document.querySelector(href)),
  )
  assert(brokenAnchors.length === 0, `Âncoras quebradas: ${brokenAnchors.join(', ')}`)
  const localReferences = await page.locator('[href], [src]').evaluateAll((elements) => elements
    .flatMap((element) => [element.getAttribute('href'), element.getAttribute('src')])
    .filter((reference) => reference && !reference.startsWith('#') && !/^[a-z]+:/i.test(reference)))
  const missingLocalReferences = localReferences
    .map((reference) => ({ reference, target: path.resolve(path.dirname(guidePath), decodeURIComponent(reference.split('#')[0])) }))
    .filter(({ target }) => !existsSync(target))
  assert(
    missingLocalReferences.length === 0,
    `Referências locais ausentes: ${JSON.stringify(missingLocalReferences)}`,
  )

  const pathExpectations = [
    { button: 'Quero operar a demo', chapters: 11, target: 'captura', title: 'Operação da demonstração' },
    { button: 'Sou da banca', chapters: 15, target: 'visao-geral', title: 'Leitura para a banca' },
    { button: 'Quero arquitetura', chapters: 11, target: 'arquitetura', title: 'Arquitetura e implementação' },
    { button: 'Tenho 5 minutos', chapters: 10, target: 'visao-geral', title: 'Resumo de 5 minutos' },
    { button: 'Tudo', chapters: 16, target: 'visao-geral', title: 'Trilha completa' },
  ]
  for (const expectation of pathExpectations) {
    const button = page.getByRole('button', { name: expectation.button, exact: true })
    await button.click()
    assert(await button.getAttribute('aria-pressed') === 'true', `A trilha "${expectation.button}" não ficou selecionada.`)
    assert(
      await page.locator('.chapter:not([hidden])').count() === expectation.chapters,
      `A trilha "${expectation.button}" deveria mostrar ${expectation.chapters} capítulos.`,
    )
    assert(
      await page.locator('.toc a:not([hidden])').count() === expectation.chapters,
      `O índice da trilha "${expectation.button}" não acompanhou os capítulos.`,
    )
    assert(
      (await page.locator('#pathResult').textContent())?.includes(`${expectation.title} selecionada`),
      `A trilha "${expectation.button}" não mostrou confirmação visível.`,
    )
    await page.waitForFunction((target) => location.hash === `#${target}`, expectation.target)
    await page.waitForFunction((target) => {
      const rect = document.getElementById(target)?.getBoundingClientRect()
      return rect && rect.top >= -2 && rect.top < 500 && rect.bottom > 0
    }, expectation.target, { timeout: 5000 })
    const destination = await page.evaluate((target) => {
      const rect = document.getElementById(target).getBoundingClientRect()
      return { bottom: rect.bottom, hash: location.hash, scrollY: window.scrollY, top: rect.top }
    }, expectation.target)
    assert(
      destination.top >= -2 && destination.top < 500 && destination.bottom > 0,
      `A trilha "${expectation.button}" não navegou ao destino: ${JSON.stringify(destination)}.`,
    )
  }
  assert(await page.locator('#pathStart').getAttribute('href') === '#visao-geral', 'O início da trilha completa está incorreto.')
  await page.locator('.path-picker').scrollIntoViewIfNeeded()
  await page.locator('#pathStart').click()
  await page.waitForFunction(() => {
    const rect = document.getElementById('visao-geral')?.getBoundingClientRect()
    return rect && rect.top >= -2 && rect.top < 500 && rect.bottom > 0
  }, undefined, { timeout: 5000 })
  assert(
    await page.locator('#visao-geral').evaluate((element) => {
      const rect = element.getBoundingClientRect()
      return rect.top >= -2 && rect.top < 500 && rect.bottom > 0
    }),
    'O botão "Começar esta trilha" não navegou ao capítulo inicial.',
  )

  const search = page.getByPlaceholder(/Buscar:/)
  await search.fill('idempotência')
  assert(await page.locator('.chapter:not(.search-hidden)').count() >= 2, 'A busca por idempotência deveria encontrar capítulos.')
  await search.fill('')

  const scopeQuiz = page.locator('[data-checkpoint="scope"]')
  await scopeQuiz.getByRole('button', { name: /São decisões de escopos diferentes/ }).click()
  assert((await scopeQuiz.locator('.quiz-feedback').textContent())?.startsWith('Correto:'), 'Quiz não forneceu feedback causal.')
  assert(await scopeQuiz.getAttribute('data-complete') === 'true', 'Quiz correto não marcou conclusão.')

  const captureQuiz = page.locator('[data-checkpoint="capture"]')
  const wrongCaptureAnswer = captureQuiz.getByRole('button', { name: /caixa de autorização/ })
  await wrongCaptureAnswer.click()
  assert(await wrongCaptureAnswer.getAttribute('aria-pressed') === 'true', 'Resposta escolhida não foi exposta à tecnologia assistiva.')
  assert((await captureQuiz.locator('.quiz-feedback').textContent())?.startsWith('Ainda não:'), 'Resposta errada não explicou a causa.')
  await captureQuiz.getByRole('button', { name: /Depois de selecionar/ }).click()
  assert(
    (await page.locator('#checkpointStatus').textContent())?.includes('2 de 6'),
    'O progresso não acompanhou os checkpoints corretos.',
  )

  await page.getByRole('button', { name: 'Reiniciar prática' }).click()
  assert((await page.locator('#checkpointStatus').textContent())?.includes('0 de 6'), 'Reinício não limpou o progresso.')
  assert(await page.locator('.quiz[data-complete="true"]').count() === 0, 'Reinício deixou checkpoint concluído.')

  const firstFlashcard = page.locator('.flashcard').first()
  const revealButton = firstFlashcard.locator('button.reveal-button')
  assert((await revealButton.textContent()) === 'Revelar', 'Flashcard não começou com a ação esperada.')
  assert(await revealButton.getAttribute('aria-expanded') === 'false', 'Flashcard começou com estado acessível incorreto.')
  await revealButton.click()
  assert(await firstFlashcard.locator('.answer').isVisible(), 'Flashcard não revelou a resposta.')
  assert(await revealButton.getAttribute('aria-expanded') === 'true', 'Flashcard não anunciou a expansão.')

  const previousTheme = await page.locator('html').getAttribute('data-theme')
  await page.getByRole('button', { name: 'Alternar tema' }).click()
  assert(await page.locator('html').getAttribute('data-theme') !== previousTheme, 'Tema não foi alternado.')

  await page.goto(pathToFileURL(guidePath).href, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: 'Alternar tema' }).click()
  await page.evaluate(() => {
    window.scrollTo({ top: 0, behavior: 'instant' })
    document.querySelector('.sidebar')?.scrollTo({ top: 0, behavior: 'instant' })
  })
  await page.waitForTimeout(250)
  assert(await page.evaluate(() => window.scrollY) === 0, 'Captura canônica não começou no topo da página.')
  await page.screenshot({ path: screenshotPath, fullPage: false })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'networkidle' })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  const overflowSources = await page.evaluate(() => [...document.querySelectorAll('body *')]
    .map((element) => {
      const rect = element.getBoundingClientRect()
      return {
        className: element.className,
        id: element.id,
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        tag: element.tagName,
        width: Math.round(rect.width),
      }
    })
    .filter((item) => item.left < -1 || item.right > window.innerWidth + 1)
    .slice(0, 12))
  assert(overflow <= 1, `Layout móvel tem overflow horizontal de ${overflow}px: ${JSON.stringify(overflowSources)}`)
  assert(runtimeErrors.length === 0, `Erros de runtime: ${runtimeErrors.join(' | ')}`)

  process.stdout.write(JSON.stringify({
    anchors: await page.locator('a[href^="#"]').count(),
    chapters: await page.locator('main .chapter').count(),
    checkpoints: await page.locator('.quiz').count(),
    images: assetReport.length,
    localReferences: localReferences.length,
    mobileOverflow: overflow,
    overflowSources: overflowSources.length,
    runtimeErrors: runtimeErrors.length,
    screenshot: screenshotPath,
  }, null, 2))
} finally {
  await browser.close()
}

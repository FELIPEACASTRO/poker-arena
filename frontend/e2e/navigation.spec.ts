import { expect, test, type Locator, type Page, type Response } from '@playwright/test'

const API_ORIGIN = 'http://127.0.0.1:8765'
const GUIDE_OUTPUT = (
  globalThis as typeof globalThis & {
    process?: { env?: Record<string, string | undefined> }
  }
).process?.env?.POKER_E2E_GUIDE_DIR
if (!GUIDE_OUTPUT) throw new Error('POKER_E2E_GUIDE_DIR ausente; use o runner E2E')
const guideScreenshot = (filename: string) => `${GUIDE_OUTPUT}/${filename}`
const REVIEW_HAND_PHH = `variant = 'NT'
antes = [0, 0, 0, 0, 0, 0]
blinds_or_straddles = [50, 100, 0, 0, 0, 0]
min_bet = 100
starting_stacks = [10000, 10000, 10000, 10000, 10000, 10000]
actions = ['d dh p1 Ks7d', 'd dh p2 8sQh', 'd dh p3 2sKh', 'd dh p4 7c5d', 'd dh p5 Jh9d', 'd dh p6 TcJc', 'p3 f', 'p4 f', 'p5 f', 'p6 cbr 225', 'p1 f', 'p2 cc', 'd db 3dQc2c', 'p2 cc', 'p6 cbr 250', 'p2 cc', 'd db 9s', 'p2 cc', 'p6 cbr 1000', 'p2 cc', 'd db 5s', 'p2 cc', 'p6 cc', 'p2 sm 8sQh', 'p6 sm']
players = ['MrWhite', 'Gogo', 'Budd', 'Eddie', 'Bill', 'Pluribus']
`

async function expectHttpSuccess(pending: Promise<Response>) {
  const response = await pending
  const endpoint = `${response.request().method()} ${new URL(response.url()).pathname}`
  expect(response.status(), `${endpoint} deve retornar 2xx`).toBeGreaterThanOrEqual(200)
  expect(response.status(), `${endpoint} deve retornar 2xx`).toBeLessThan(300)
  return response
}

function captureRuntimeFailures(page: Page, allowedConsoleErrors: RegExp[] = []) {
  const failures: string[] = []
  page.on('pageerror', (error) => failures.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (
      message.type() === 'error' &&
      !allowedConsoleErrors.some((pattern) => pattern.test(message.text()))
    ) {
      failures.push(`console: ${message.text()}`)
    }
  })
  return () => expect(failures, 'a página não deve emitir erros de runtime').toEqual([])
}

async function expectBasicAccessibility(scope: Locator) {
  const findings = await scope.evaluate((root) => {
    const documentRoot = root.ownerDocument
    const all = Array.from(root.querySelectorAll<HTMLElement>('*'))
    const ids = all.map((node) => node.id).filter(Boolean)
    const duplicateIds = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))]
    const unnamedButtons = all
      .filter((node) => node.matches('button, a[href]'))
      .filter((node) => {
        const text = node.textContent?.trim()
        return !text && !node.getAttribute('aria-label') && !node.getAttribute('aria-labelledby') && !node.getAttribute('title')
      })
      .map((node) => node.outerHTML.slice(0, 160))
    const unlabeledControls = all
      .filter((node) => node.matches('input:not([type="hidden"]), select, textarea'))
      .filter((node) => {
        const control = node as HTMLInputElement
        return !control.labels?.length && !node.getAttribute('aria-label') && !node.getAttribute('aria-labelledby')
      })
      .map((node) => node.outerHTML.slice(0, 160))
    const brokenLabelReferences = all
      .filter((node) => node.hasAttribute('aria-labelledby'))
      .filter((node) =>
        (node.getAttribute('aria-labelledby') ?? '')
          .split(/\s+/)
          .some((id) => id && !documentRoot.getElementById(id)),
      )
      .map((node) => node.outerHTML.slice(0, 160))
    return { duplicateIds, unnamedButtons, unlabeledControls, brokenLabelReferences }
  })
  expect(findings).toEqual({
    duplicateIds: [],
    unnamedButtons: [],
    unlabeledControls: [],
    brokenLabelReferences: [],
  })
}

async function openDialog(page: Page, buttonName: string | RegExp, dialogName: string | RegExp) {
  const trigger = page.getByRole('button', { name: buttonName })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: dialogName })
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveAttribute('aria-modal', 'true')
  await expect
    .poll(() => dialog.evaluate((node) => node.contains(node.ownerDocument.activeElement)))
    .toBe(true)
  await expectBasicAccessibility(dialog)
  return { trigger, dialog }
}

async function startHumanTable(page: Page, seed: number) {
  await page.goto('/')
  await page.getByLabel('Quantos bots na mesa?').selectOption('1')
  const created = page.waitForResponse(
    (response) => response.url().endsWith('/tables') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Sentar à mesa' }).click()
  const response = await expectHttpSuccess(created)
  expect(response.status()).toBe(201)
  expect(response.request().postDataJSON()).toMatchObject({ seed, mode: 'play' })
  await expect(page.getByRole('navigation', { name: 'Ferramentas da mesa' })).toBeVisible()
}

async function leaveTable(page: Page) {
  await page.getByRole('button', { name: 'Sair da mesa' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Poker Arena' })).toBeVisible()
}

test('launcher abre workspace de captura da solução parceira sem depender de uma mesa', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page)

  await page.goto('/?view=capture')
  const workspace = page.getByRole('main', { name: /Captura supervisionada/ })
  await expect(workspace).toBeVisible()
  await expect(workspace).not.toHaveAttribute('aria-modal')
  await expect(page.getByRole('heading', { level: 1, name: 'Poker Arena' })).toHaveCount(0)
  await expect.poll(() => workspace.evaluate((node) => node === node.ownerDocument.activeElement)).toBe(true)
  const workspaceBox = await workspace.boundingBox()
  expect(workspaceBox?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(40)
  await expect(workspace.getByText(/somente depois da confirmação/i)).toBeVisible()
  const otherMonitor = workspace.getByRole('radio', { name: /Outro monitor/ })
  const sameMonitor = workspace.getByRole('radio', { name: /Mesmo monitor/ })
  await expect(otherMonitor).toBeChecked()
  await expect(workspace.getByRole('note', { name: /configuração de monitores/ })).toContainText('Monitor 1')
  await expect(workspace.getByRole('note', { name: /configuração de monitores/ })).toContainText('Monitor 2')
  await sameMonitor.check()
  await expect(workspace.getByRole('button', { name: /Selecionar janela neste mesmo monitor/ })).toBeDisabled()
  await otherMonitor.check()
  const capture = workspace.getByRole('button', { name: /Selecionar janela no outro monitor/ })
  await expect(capture).toBeDisabled()
  await workspace.getByText(/Autorizo a captura da janela/).click()
  await expect(capture).toBeEnabled()
  await expectBasicAccessibility(workspace)

  assertNoRuntimeFailures()
})

test('workspace executa seleção, confirmação, leitura real e encerramento', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page)
  await page.addInitScript(() => {
    const canvases: HTMLCanvasElement[] = []
    Object.defineProperty(navigator.mediaDevices, 'getDisplayMedia', {
      configurable: true,
      value: async (options: DisplayMediaStreamOptions) => {
        ;(window as unknown as { __pokerCaptureOptions?: DisplayMediaStreamOptions })
          .__pokerCaptureOptions = options
        const canvas = document.createElement('canvas')
        canvas.width = 640
        canvas.height = 480
        const context = canvas.getContext('2d')
        if (!context) throw new Error('Canvas 2D indisponível no teste de captura.')
        context.fillStyle = '#07543d'
        context.fillRect(0, 0, canvas.width, canvas.height)
        context.fillStyle = '#ffffff'
        context.fillRect(245, 170, 70, 100)
        context.fillRect(325, 170, 70, 100)
        canvases.push(canvas)
        ;(window as unknown as { __pokerCaptureCanvases?: HTMLCanvasElement[] })
          .__pokerCaptureCanvases = canvases
        const stream = canvas.captureStream(2)
        const track = stream.getVideoTracks()[0]
        Object.defineProperty(track, 'getSettings', {
          configurable: true,
          value: () => ({ displaySurface: 'window' }),
        })
        return stream
      },
    })
  })

  let imageRequests = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/copilot/from-image') && request.method() === 'POST') {
      imageRequests += 1
    }
  })

  await page.goto('/?view=capture')
  const workspace = page.getByRole('main', { name: /Captura supervisionada/ })
  await page.waitForTimeout(300)
  await page.screenshot({ path: guideScreenshot('01-workspace-inicial.png'), fullPage: true })
  await workspace.getByLabel(/Autorizo a captura da janela/).check()
  await workspace.getByRole('button', { name: /Selecionar janela no outro monitor/ }).click()

  const captureOptions = await page.evaluate(() =>
    (window as unknown as { __pokerCaptureOptions?: Record<string, unknown> }).__pokerCaptureOptions)
  expect(captureOptions).toMatchObject({
    audio: false,
    monitorTypeSurfaces: 'exclude',
    preferCurrentTab: false,
    selfBrowserSurface: 'exclude',
    surfaceSwitching: 'exclude',
    video: { displaySurface: 'window' },
  })

  await expect(workspace.getByText(/Esta é a janela correta/)).toBeVisible()
  await expect(workspace.getByLabel('Prévia da janela compartilhada')).toBeVisible()
  await page.screenshot({ path: guideScreenshot('02-confirmacao-previa.png'), fullPage: true })
  await page.waitForTimeout(1800)
  expect(imageRequests, 'selecionar a fonte não pode enviar quadros').toBe(0)

  const readFrame = page.waitForResponse(
    (response) => response.url().endsWith('/copilot/from-image')
      && response.request().method() === 'POST',
  )
  await workspace.getByRole('button', { name: 'Confirmar e iniciar análise' }).click()
  const response = await readFrame
  expect(response.status()).toBe(200)
  expect(imageRequests).toBeGreaterThanOrEqual(1)
  await expect(workspace.getByRole('region', { name: /Diagnóstico verificável/ })).toBeVisible()
  await expect(workspace.getByText('Proteção aprovada · recomendação suprimida')).toBeVisible()
  await expect(workspace.getByText(/Modo apresentação: estratégia não é exibida/)).toBeVisible()
  await page.screenshot({ path: guideScreenshot('03-diagnostico-ativo.png'), fullPage: true })

  await workspace.getByRole('button', { name: 'Encerrar compartilhamento' }).click()
  await expect(workspace.getByRole('button', { name: /Selecionar janela no outro monitor/ })).toBeEnabled()
  await expect(workspace.getByText(/Etapa 2 de 4/)).toBeVisible()
  assertNoRuntimeFailures()
})

test('workspace recusa fonte cujo navegador não comprova como janela', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page)
  await page.addInitScript(() => {
    const canvases: HTMLCanvasElement[] = []
    Object.defineProperty(navigator.mediaDevices, 'getDisplayMedia', {
      configurable: true,
      value: async () => {
        const canvas = document.createElement('canvas')
        canvas.width = 640
        canvas.height = 480
        const context = canvas.getContext('2d')
        if (!context) throw new Error('Canvas 2D indisponível no teste de fonte não verificável.')
        context.fillStyle = '#07543d'
        context.fillRect(0, 0, canvas.width, canvas.height)
        canvases.push(canvas)
        ;(window as unknown as { __pokerUnverifiedCanvases?: HTMLCanvasElement[] })
          .__pokerUnverifiedCanvases = canvases
        const stream = canvas.captureStream(2)
        const track = stream.getVideoTracks()[0]
        Object.defineProperty(track, 'getSettings', {
          configurable: true,
          value: () => ({}),
        })
        return stream
      },
    })
  })

  let imageRequests = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/copilot/from-image') && request.method() === 'POST') {
      imageRequests += 1
    }
  })

  await page.goto('/?view=capture')
  const workspace = page.getByRole('main', { name: /Captura supervisionada/ })
  await workspace.getByLabel(/Autorizo a captura da janela/).check()
  await workspace.getByRole('button', { name: /Selecionar janela no outro monitor/ }).click()

  await expect(workspace.getByRole('button', { name: 'Confirmar e iniciar análise' })).toBeDisabled()
  await expect(workspace.getByRole('alert')).toContainText(
    'Somente uma fonte confirmada pelo navegador como Janela',
  )
  await expect(workspace.getByText(/Esta é a janela correta/)).toHaveCount(0)
  await page.waitForTimeout(1800)
  expect(imageRequests, 'fonte sem displaySurface não pode enviar quadros').toBe(0)
  assertNoRuntimeFailures()
})

test('configuração inicial é navegável, responsiva e consulta níveis reais', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page)
  const levelsResponse = page.waitForResponse(
    (response) => response.url().endsWith('/levels') && response.request().method() === 'GET',
  )

  await page.goto('/')
  await expectHttpSuccess(levelsResponse)
  await expect(page.getByRole('heading', { level: 1, name: 'Poker Arena' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Eu jogo/ })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByLabel('Quantos bots na mesa?')).toHaveValue('3')

  const watchMode = page.getByRole('button', { name: /Assistir \(só bots\)/ })
  await expect(watchMode).toBeVisible()
  await expect(watchMode).toBeEnabled()
  // Este cenário valida também navegação sem mouse. Ativar o botão real com Enter
  // evita transformar animação/layout lento do host em um clique forçado.
  await watchMode.focus()
  await expect(watchMode).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(watchMode).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: /Eu jogo/ })).toHaveAttribute('aria-pressed', 'false')
  const botCounts = await page.getByLabel('Quantos bots disputam?').locator('option').allTextContents()
  expect(botCounts).toEqual(['2', '3', '4', '5', '6', '7', '8', '9'])
  await expect(page.getByRole('button', { name: 'Assistir à partida' })).toBeEnabled()

  for (const link of await page.locator('a[target="_blank"]').all()) {
    await expect(link).toHaveAttribute('rel', /noreferrer/)
  }
  await expectBasicAccessibility(page.locator('body'))

  await page.setViewportSize({ width: 390, height: 844 })
  const overflowingElements = await page.evaluate(() =>
    Array.from(document.querySelectorAll<HTMLElement>('body *'))
      .map((node) => {
        const bounds = node.getBoundingClientRect()
        return {
          tag: node.tagName.toLowerCase(),
          className: node.className.toString().slice(0, 80),
          left: Math.round(bounds.left),
          right: Math.round(bounds.right),
        }
      })
      .filter(({ left, right }) => left < -1 || right > document.documentElement.clientWidth + 1),
  )
  expect(overflowingElements, 'nenhum elemento deve ultrapassar a largura móvel').toEqual([])
  assertNoRuntimeFailures()
})

test('URL direta abre o copiloto sem criar mesa e retorna ao setup', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page)
  let tablesCreated = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/tables') && request.method() === 'POST') tablesCreated += 1
  })

  await page.goto('/?view=copilot')
  const dialog = page.getByRole('dialog', { name: /Copiloto de mãos/ })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('tab', { name: 'Spot único' })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await dialog.getByLabel('Fechar').click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: 'Sentar à mesa' })).toBeVisible()
  expect(tablesCreated).toBe(0)
  assertNoRuntimeFailures()
})

test('modo laboratório cobre configuração, painéis, pausa, velocidade e passo real', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page)
  await page.goto('/')
  await page.getByRole('button', { name: /Assistir \(só bots\)/ }).click()
  await page.getByLabel('Quantos bots disputam?').selectOption('3')
  await page.getByLabel('Luna').selectOption('adaptive')
  await page.getByLabel('Caio').selectOption('heuristic')
  await page.getByLabel('Sofia').selectOption('montecarlo')
  await page.getByLabel('Fichas iniciais').fill('1200')
  await page.getByLabel('Formato').selectOption('tourney')
  await page.getByLabel('Limite de mãos').selectOption('30')

  const created = page.waitForResponse(
    (response) => response.url().endsWith('/tables') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Assistir à partida' }).click()
  const response = await expectHttpSuccess(created)
  expect(response.status()).toBe(201)
  expect(response.request().postDataJSON()).toMatchObject({
    mode: 'watch',
    starting_stack: 1200,
    rebuy: false,
    hand_limit: 30,
    bots: [
      { name: 'Luna', level: 'adaptive' },
      { name: 'Caio', level: 'heuristic' },
      { name: 'Sofia', level: 'montecarlo' },
    ],
  })
  await expect(page.getByText('Placar do laboratório')).toBeVisible()
  await expect(page.getByText('Estilo de cada IA')).toBeVisible()
  await expect(page.getByText('Estatísticas da sessão')).toBeVisible()

  await page.getByRole('button', { name: 'Pausar' }).click()
  await expect(page.getByRole('button', { name: 'Continuar' })).toBeVisible()
  const speed = page.getByLabel('Tempo por jogada')
  await speed.fill('300')
  await expect(speed).toHaveValue('300')
  await expect(page.getByText('0.3s/jogada')).toBeVisible()
  const hintClose = page.getByRole('button', { name: 'Fechar dica' })
  if (await hintClose.count()) {
    await hintClose.click()
    await expect(hintClose).toHaveCount(0)
    expect(await page.evaluate(() => localStorage.getItem('pa_lab_hint_dismissed'))).toBe('1')
  }

  const stepped = page.waitForResponse((candidate) =>
    /\/tables\/[^/]+\/step$/.test(new URL(candidate.url()).pathname),
  )
  await page.getByRole('button', { name: 'Continuar' }).click()
  await expectHttpSuccess(stepped)
  await page.getByRole('button', { name: 'Pausar' }).click()
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sentar à mesa' })).toBeVisible()
  assertNoRuntimeFailures()
})

test('ações humanas e atalhos cobrem pagar, passar, aumentar, all-in, fold e próxima mão', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page)
  let activeSeed = 2
  await page.route('**/tables', async (route) => {
    const request = route.request()
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/tables') {
      await route.continue({
        postData: JSON.stringify({ ...request.postDataJSON(), seed: activeSeed }),
      })
      return
    }
    await route.continue()
  })

  await startHumanTable(page, activeSeed)
  let pending = page.waitForResponse((response) => response.url().endsWith('/actions'))
  await page.getByRole('button', { name: /Pagar\s+10/ }).click()
  let action = await expectHttpSuccess(pending)
  expect(action.request().postDataJSON()).toMatchObject({ type: 'call', amount: 0 })
  await expect(page.getByRole('button', { name: 'Passar' })).toBeVisible()
  pending = page.waitForResponse((response) => response.url().endsWith('/actions'))
  await page.keyboard.press('c')
  action = await expectHttpSuccess(pending)
  expect(action.request().postDataJSON()).toMatchObject({ type: 'check', amount: 0 })
  await leaveTable(page)

  activeSeed = 3
  await startHumanTable(page, activeSeed)
  const raiseValue = page.getByLabel('Valor total do aumento')
  await page.getByRole('button', { name: 'Pote', exact: true }).click()
  await expect(raiseValue).toHaveValue('60')
  await page.getByRole('button', { name: 'Diminuir aposta' }).click()
  await expect(raiseValue).toHaveValue('40')
  await page.getByRole('button', { name: 'Aumentar aposta' }).click()
  await expect(raiseValue).toHaveValue('60')
  await page.getByRole('button', { name: '2,5× Pote' }).click()
  await expect(raiseValue).toHaveValue('120')
  await page.getByRole('button', { name: 'Máx' }).click()
  await expect(raiseValue).toHaveValue('1000')
  await page.getByRole('button', { name: 'Min', exact: true }).click()
  await expect(raiseValue).toHaveValue('40')
  await raiseValue.fill('80')
  pending = page.waitForResponse((response) => response.url().endsWith('/actions'))
  await page.getByRole('button', { name: /Aumentar p\/\s*80/ }).click()
  action = await expectHttpSuccess(pending)
  expect(action.request().postDataJSON()).toMatchObject({ type: 'raise', amount: 80 })
  await leaveTable(page)

  activeSeed = 4
  await startHumanTable(page, activeSeed)
  pending = page.waitForResponse((response) => response.url().endsWith('/actions'))
  await page.keyboard.press('a')
  action = await expectHttpSuccess(pending)
  expect(action.request().postDataJSON()).toMatchObject({ type: 'all_in', amount: 0 })
  await leaveTable(page)

  activeSeed = 5
  await startHumanTable(page, activeSeed)
  pending = page.waitForResponse((response) => response.url().endsWith('/actions'))
  await page.keyboard.press('f')
  action = await expectHttpSuccess(pending)
  expect(action.request().postDataJSON()).toMatchObject({ type: 'fold', amount: 0 })
  await expect(page.getByRole('button', { name: /Próxima mão/ })).toBeVisible()
  const nextHand = page.waitForResponse((response) => response.url().endsWith('/next-hand'))
  await page.keyboard.press('Enter')
  await expectHttpSuccess(nextHand)
  await leaveTable(page)
  assertNoRuntimeFailures()
})

test('fluxo integrado cobre mesa, ações, copiloto, gestão e todos os diálogos', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page)
  await page.goto('/')
  await page.getByLabel('Quantos bots na mesa?').selectOption('1')

  const created = page.waitForResponse(
    (response) => response.url().endsWith('/tables') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Sentar à mesa' }).click()
  const createdResponse = await created
  expect(createdResponse.status()).toBe(201)
  expect(createdResponse.headers().etag).toMatch(/^"\d+"$/)
  await expect(page.getByText('Poker Arena', { exact: true })).toBeVisible()
  const handCounter = page.getByText(/mão #\d+/)
  await expect(handCounter).toBeVisible()
  const initialHandNumber = Number((await handCounter.textContent())?.match(/\d+/)?.[0])
  expect(initialHandNumber).toBeGreaterThanOrEqual(1)

  const manage = await openDialog(page, 'Gerenciar mesa', 'Gerenciar mesa')
  await manage.dialog.getByLabel('Nome do novo jogador').fill('Navegador E2E')
  await manage.dialog.getByLabel('Nível do novo jogador').selectOption('random')
  const added = page.waitForResponse(
    (response) => /\/tables\/[^/]+\/players$/.test(new URL(response.url()).pathname) && response.request().method() === 'POST',
  )
  await manage.dialog.getByRole('button', { name: 'Adicionar' }).click()
  await expectHttpSuccess(added)
  await expect(manage.dialog.getByText('3/9 lugares')).toBeVisible()

  const removed = page.waitForResponse(
    (response) => /\/tables\/[^/]+\/players\/\d+$/.test(new URL(response.url()).pathname) && response.request().method() === 'DELETE',
  )
  await manage.dialog.getByRole('button', { name: 'Remover Navegador E2E' }).click()
  await expectHttpSuccess(removed)
  await expect(manage.dialog.getByText('2/9 lugares')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(manage.dialog).toBeHidden()
  await expect(manage.trigger).toBeFocused()

  const positions = await openDialog(page, 'Guia de posições', /Posições da mesa/)
  await expect(positions.dialog.getByRole('heading', { name: 'Botão (Dealer)' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(positions.trigger).toBeFocused()

  const brains = await openDialog(page, 'Guia dos cérebros', /Os cérebros da Arena/)
  await expect(brains.dialog.getByText(/Uma sessão isolada não prova habilidade/)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(brains.trigger).toBeFocused()

  const live = await openDialog(page, 'Abrir captura supervisionada', /Captura supervisionada/)
  const capture = live.dialog.getByRole('button', { name: 'Selecionar janela do jogo' })
  await expect(capture).toBeDisabled()
  await live.dialog.getByLabel(/Autorizo a captura/).check()
  await expect(capture).toBeEnabled()
  await page.keyboard.press('Escape')
  await expect(live.trigger).toBeFocused()

  const copilot = await openDialog(page, 'Abrir copiloto de estudo', /Copiloto de mãos/)
  const tabs = copilot.dialog.getByRole('tablist', { name: 'Formas de análise' })
  await expect(tabs.getByRole('tab', { name: 'Spot único' })).toHaveAttribute('aria-selected', 'true')
  await tabs.getByRole('tab', { name: 'Spot único' }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(tabs.getByRole('tab', { name: /Colar mão/ })).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('Home')
  await expect(tabs.getByRole('tab', { name: 'Spot único' })).toHaveAttribute('aria-selected', 'true')

  await copilot.dialog.getByLabel('Suas 2 cartas').fill('As Ks')
  await copilot.dialog.getByLabel(/Board/).fill('Qs Js 2h')
  const analyzed = page.waitForResponse(
    (response) => response.url().endsWith('/copilot') && response.request().method() === 'POST',
  )
  await copilot.dialog.getByRole('button', { name: 'Analisar spot' }).click()
  await expectHttpSuccess(analyzed)
  await expect(copilot.dialog.getByText('Equity estimada')).toBeVisible()
  await expect(copilot.dialog.getByText('As jogadas, avaliadas')).toBeVisible()

  await tabs.getByRole('tab', { name: /Colar mão/ }).click()
  await copilot.dialog.getByLabel(/Cole o histórico da mão/).fill(REVIEW_HAND_PHH)
  await copilot.dialog.getByLabel(/Qual jogador/).fill('2')
  const reviewed = page.waitForResponse(
    (response) => response.url().endsWith('/copilot/review-hand') && response.request().method() === 'POST',
  )
  await copilot.dialog.getByRole('button', { name: 'Revisar minhas decisões' }).click()
  await expectHttpSuccess(reviewed)
  await expect(copilot.dialog.getByText(/Revisando Gogo/)).toBeVisible()
  await expect(copilot.dialog.locator('.cp-dec')).not.toHaveCount(0)

  const screenshot = await page.screenshot({ animations: 'disabled' })
  await tabs.getByRole('tab', { name: /Da imagem/ }).click()
  const imageReviewed = page.waitForResponse(
    (response) => response.url().endsWith('/copilot/from-image') && response.request().method() === 'POST',
  )
  await copilot.dialog.getByLabel(/Screenshot da mesa/).setInputFiles({
    name: 'mesa-e2e.png',
    mimeType: 'image/png',
    buffer: screenshot,
  })
  const imageResponse = await expectHttpSuccess(imageReviewed)
  const imageBody = (await imageResponse.json()) as {
    engine: string
    sanity: { ok: boolean }
    decision: unknown | null
  }
  expect(imageBody.engine).not.toBe('')
  expect(imageBody.sanity.ok === false || imageBody.decision !== null).toBe(true)
  await expect(copilot.dialog.getByAltText('mesa enviada')).toBeVisible()
  const visionDiagnostics = copilot.dialog.getByRole('region', {
    name: 'Diagnóstico verificável da leitura de imagem',
  })
  await expect(visionDiagnostics.getByRole('heading', { name: 'Estado detectado' })).toBeVisible()
  await expect(visionDiagnostics.getByText(/Motor executado/)).toBeVisible()
  await expect(visionDiagnostics.getByText(/Latência da chamada/)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(copilot.trigger).toBeFocused()

  const folded = page.waitForResponse(
    (response) => response.url().endsWith('/actions') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Desistir' }).click()
  await expectHttpSuccess(folded)
  await expect(page.getByRole('button', { name: /Próxima mão/ })).toBeVisible()

  const nextHand = page.waitForResponse(
    (response) => response.url().endsWith('/next-hand') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /Próxima mão/ }).click()
  await expectHttpSuccess(nextHand)
  await expect
    .poll(async () => Number((await handCounter.textContent())?.match(/\d+/)?.[0]))
    .toBeGreaterThan(initialHandNumber)

  const audit = await openDialog(page, 'Auditoria de partidas', /Auditoria de partidas/)
  const replay = page.waitForResponse(
    (response) => /\/games\/[^/]+$/.test(new URL(response.url()).pathname) && response.request().method() === 'GET',
  )
  await audit.dialog.getByRole('button', { name: /Você joga/ }).first().click()
  await expectHttpSuccess(replay)
  const hand = audit.dialog.getByRole('button', { name: /Mão #\d+/ }).first()
  await expect(hand).toBeVisible()
  await hand.click()
  await expect(hand).toHaveAttribute('aria-expanded', 'true')
  await audit.dialog.getByRole('button', { name: 'Voltar à lista de partidas' }).click()
  await expect(audit.dialog.getByText(/Você joga/).first()).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(audit.trigger).toBeFocused()

  await page.getByRole('button', { name: 'Sair da mesa' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Poker Arena' })).toBeVisible()
  assertNoRuntimeFailures()
})

test('WebSocket real, ressincronização 409 e paginação preservam o contrato ponta a ponta', async ({ page, request }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page, [
    /Failed to load resource.*409 \(Conflict\)/,
  ])
  await page.goto('/')
  await page.getByLabel('Quantos bots na mesa?').selectOption('1')

  const created = page.waitForResponse(
    (response) => response.url().endsWith('/tables') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Sentar à mesa' }).click()
  const createdResponse = await expectHttpSuccess(created)
  const initial = (await createdResponse.json()) as { table_id: string; version: number }
  const tablePath = `/tables/${initial.table_id}`

  const socketMutation = await page.evaluate(
    ({ tableId }) =>
      new Promise<{ initialVersion: number; finalVersion: number }>((resolve, reject) => {
        const socket = new WebSocket(`ws://127.0.0.1:8765/tables/${encodeURIComponent(tableId)}/ws`)
        let initialVersion: number | null = null
        const timeout = window.setTimeout(() => {
          socket.close()
          reject(new Error('WebSocket E2E não respondeu em 10 s.'))
        }, 10_000)
        const fail = (message: string) => {
          window.clearTimeout(timeout)
          socket.close()
          reject(new Error(message))
        }
        socket.addEventListener('error', () => fail('WebSocket E2E falhou.'))
        socket.addEventListener('message', (event) => {
          let payload: Record<string, unknown>
          try {
            payload = JSON.parse(String(event.data)) as Record<string, unknown>
          } catch {
            fail('WebSocket E2E devolveu JSON inválido.')
            return
          }
          if (typeof payload.error === 'string') {
            fail(`WebSocket E2E devolveu erro: ${payload.error}`)
            return
          }
          if (typeof payload.version !== 'number') {
            fail('WebSocket E2E não devolveu versão numérica.')
            return
          }
          if (initialVersion === null) {
            initialVersion = payload.version
            socket.send(JSON.stringify({
              type: 'fold',
              amount: 0,
              command_id: 'e2e-websocket-fold',
              expected_version: initialVersion,
            }))
            return
          }
          if (payload.version <= initialVersion) {
            fail('WebSocket E2E não avançou a versão.')
            return
          }
          window.clearTimeout(timeout)
          socket.close()
          resolve({ initialVersion, finalVersion: payload.version })
        })
      }),
    { tableId: initial.table_id },
  )
  expect(socketMutation.initialVersion).toBe(initial.version)
  expect(socketMutation.finalVersion).toBe(initial.version + 1)

  const conflict = page.waitForResponse(
    (response) => new URL(response.url()).pathname === `${tablePath}/actions`
      && response.request().method() === 'POST'
      && response.status() === 409,
  )
  const refreshed = page.waitForResponse(
    (response) => new URL(response.url()).pathname === tablePath
      && response.request().method() === 'GET'
      && response.status() === 200,
  )
  await page.getByRole('button', { name: 'Desistir' }).click()
  await conflict
  await refreshed
  await expect(page.getByRole('alert')).toContainText(
    `Estado ressincronizado na versão ${socketMutation.finalVersion}`,
  )
  await expect(page.getByRole('button', { name: /Próxima mão/ })).toBeVisible()

  const nextHand = page.waitForResponse(
    (response) => new URL(response.url()).pathname === `${tablePath}/next-hand`
      && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /Próxima mão/ }).click()
  const nextHandResponse = await expectHttpSuccess(nextHand)
  const nextHandState = (await nextHandResponse.json()) as { phase: string }
  if (nextHandState.phase === 'human_turn') {
    await expect(page.getByRole('button', { name: 'Desistir' })).toBeVisible()
    const secondFold = page.waitForResponse(
      (response) => new URL(response.url()).pathname === `${tablePath}/actions`
        && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Desistir' }).click()
    await expectHttpSuccess(secondFold)
  } else {
    // Em heads-up o bot pode desistir antes de o humano agir; isso também conclui
    // legitimamente a segunda mão e deve permanecer aceito pelo teste integrado.
    expect(nextHandState.phase).toBe('hand_over')
  }
  await expect(page.getByRole('button', { name: /Próxima mão/ })).toBeVisible()

  const extra = await request.post(`${API_ORIGIN}/tables`, {
    headers: { 'Idempotency-Key': 'e2e-pagination-extra-table' },
    data: {
      human_name: 'EXTRA E2E',
      bots: [{ name: 'BOT EXTRA', level: 'random' }],
      starting_stack: 1000,
      small_blind: 10,
      big_blind: 20,
      mode: 'play',
      seed: 7123,
    },
  })
  expect(extra.status()).toBe(201)

  await page.route(/\/games\?offset=0&limit=50$/, async (route) => {
    const url = new URL(route.request().url())
    url.searchParams.set('limit', '1')
    await route.continue({ url: url.toString() })
  }, { times: 1 })
  const firstGamesPage = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/games'
      && new URL(response.url()).searchParams.get('limit') === '1',
  )
  const audit = await openDialog(page, 'Auditoria de partidas', /Auditoria de partidas/)
  await expectHttpSuccess(firstGamesPage)
  const moreGames = audit.dialog.getByRole('button', { name: /Carregar mais partidas/ })
  await expect(moreGames).toBeVisible()
  const secondGamesPage = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === '/games'
      && url.searchParams.get('offset') === '1'
      && url.searchParams.get('limit') === '1'
  })
  await moreGames.click()
  await expectHttpSuccess(secondGamesPage)
  await expect(audit.dialog.locator('.audit-game')).toHaveCount(2)

  await page.route(new RegExp(`/games/${initial.table_id}\\?offset=0&limit=100$`), async (route) => {
    const url = new URL(route.request().url())
    url.searchParams.set('limit', '1')
    await route.continue({ url: url.toString() })
  }, { times: 1 })
  const firstHandsPage = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === `/games/${initial.table_id}`
      && url.searchParams.get('limit') === '1'
  })
  await audit.dialog.locator('.audit-game').filter({ hasText: '2 mãos' }).click()
  await expectHttpSuccess(firstHandsPage)
  await expect(audit.dialog.locator('.audit-hand')).toHaveCount(1)
  const moreHands = audit.dialog.getByRole('button', { name: /Carregar mais mãos/ })
  await expect(moreHands).toBeVisible()
  const secondHandsPage = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === `/games/${initial.table_id}`
      && url.searchParams.get('offset') === '1'
      && url.searchParams.get('limit') === '1'
  })
  await moreHands.click()
  await expectHttpSuccess(secondHandsPage)
  await expect(audit.dialog.locator('.audit-hand')).toHaveCount(2)
  const handLabels = await audit.dialog.locator('.audit-hand-n').allTextContents()
  expect(new Set(handLabels).size).toBe(2)
  assertNoRuntimeFailures()
})

test('mesa completa permanece navegável e contida em viewport móvel', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  const created = page.waitForResponse(
    (response) => response.url().endsWith('/tables') && response.request().method() === 'POST',
  )
  // O padrão tem humano + 3 bots e cobre os assentos laterais que antes vazavam.
  await page.getByRole('button', { name: 'Sentar à mesa' }).click()
  await expectHttpSuccess(created)
  await expect(page.locator('.seat-plate')).toHaveCount(4)

  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }))
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport + 1)
  expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport + 1)

  const seatBounds = await page.locator('.seat-plate').evaluateAll((nodes) =>
    nodes.map((node) => {
      const bounds = node.getBoundingClientRect()
      return { left: bounds.left, right: bounds.right }
    }),
  )
  for (const bounds of seatBounds) {
    expect(bounds.left).toBeGreaterThanOrEqual(-1)
    expect(bounds.right).toBeLessThanOrEqual(391)
  }

  const tools = page.getByRole('navigation', { name: 'Ferramentas da mesa' })
  await expect(tools).toBeVisible()
  await tools.getByRole('button', { name: 'Sair da mesa' }).scrollIntoViewIfNeeded()
  await expect(tools.getByRole('button', { name: 'Sair da mesa' })).toBeVisible()
  await expectBasicAccessibility(page.locator('body'))
  assertNoRuntimeFailures()
})

test('falha HTTP é explicada sem abandonar a tela de configuração', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page, [
    /Failed to load resource.*503 \(Service Unavailable\)/,
  ])
  await page.route('**/tables', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'manutenção programada' }),
    })
  })
  await page.goto('/')
  await page.getByLabel('Quantos bots na mesa?').selectOption('1')
  await page.getByRole('button', { name: 'Sentar à mesa' }).click()

  await expect(page.getByRole('alert')).toContainText('HTTP 503: manutenção programada')
  await expect(page.getByRole('heading', { level: 1, name: 'Poker Arena' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sentar à mesa' })).toBeEnabled()
  assertNoRuntimeFailures()
})

test('Swagger e ReDoc renderizam o contrato completo sem dependências externas', async ({ page }) => {
  const assertNoRuntimeFailures = captureRuntimeFailures(page)

  await page.goto(`${API_ORIGIN}/docs`)
  await expect(page.locator('.swagger-ui')).toBeVisible()
  await expect(page.locator('.opblock')).toHaveCount(17)

  await page.goto(`${API_ORIGIN}/redoc`)
  await expect(page.locator('.redoc-wrap')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: /Poker Arena API/ })).toBeVisible()

  assertNoRuntimeFailures()
})

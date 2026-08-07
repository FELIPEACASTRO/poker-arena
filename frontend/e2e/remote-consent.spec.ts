import { expect, test, type Page } from '@playwright/test'

declare const process: { env: Record<string, string | undefined> }

function captureRuntimeFailures(page: Page) {
  const failures: string[] = []
  page.on('pageerror', (error) => failures.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (
      message.type() === 'error'
      && !/Failed to load resource.*401 \(Unauthorized\)/.test(message.text())
    ) {
      failures.push(`console: ${message.text()}`)
    }
  })
  return () => expect(failures, 'a página protegida não deve emitir erros inesperados').toEqual([])
}

test('consentimento remoto autenticado é criado e revogado pela captura supervisionada', async ({ page }) => {
  const token = process.env.POKER_E2E_API_TOKEN
  if (!token) throw new Error('POKER_E2E_API_TOKEN ausente no perfil protegido.')
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
        if (!context) throw new Error('Canvas 2D indisponível no perfil E2E.')
        context.fillStyle = '#07543d'
        context.fillRect(0, 0, canvas.width, canvas.height)
        context.fillStyle = '#ffffff'
        context.fillRect(245, 170, 70, 100)
        context.fillRect(325, 170, 70, 100)
        canvases.push(canvas)
        ;(window as unknown as { __pokerE2eCanvases?: HTMLCanvasElement[] }).__pokerE2eCanvases = canvases
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

  await page.goto('/')
  const authorized = page.waitForResponse(
    (response) => response.url().endsWith('/levels') && response.status() === 200,
  )
  await page.getByLabel('Token da API (opcional)').fill(token)
  await authorized
  await page.getByLabel('Quantos bots na mesa?').selectOption('1')

  const created = page.waitForResponse(
    (response) => response.url().endsWith('/tables')
      && response.request().method() === 'POST'
      && response.status() === 201,
  )
  await page.getByRole('button', { name: 'Sentar à mesa' }).click()
  await created

  await page.getByRole('button', { name: 'Abrir captura supervisionada' }).click()
  const dialog = page.getByRole('dialog', { name: /Captura supervisionada/ })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel(/Autorizo a captura desta tela/).check()
  await dialog.getByText('Opções avançadas e contexto manual').click()
  await dialog.getByLabel(/Também autorizo/).check()
  await dialog.getByLabel('Ler a cada').selectOption('1500')

  const issued = page.waitForResponse(
    (response) => response.url().endsWith('/copilot/remote-vlm/consent-sessions')
      && response.request().method() === 'POST',
  )
  const readFrame = page.waitForResponse(
    (response) => response.url().endsWith('/copilot/from-image')
      && response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: 'Selecionar janela do jogo' }).click()
  await expect(dialog.getByText(/Nenhum quadro será enviado antes de confirmar/)).toBeVisible()
  await dialog.getByRole('button', { name: 'Confirmar e iniciar análise' }).click()
  const issuedResponse = await issued
  expect(issuedResponse.status()).toBe(201)
  const issuedBody = (await issuedResponse.json()) as {
    session_id: string
    expires_in_seconds: number
  }
  expect(issuedBody.session_id).toMatch(/^[A-Za-z0-9_-]{20,128}$/)
  expect(issuedBody.expires_in_seconds).toBeGreaterThan(0)
  await expect(dialog.getByRole('button', { name: 'Encerrar compartilhamento' })).toBeVisible()

  const frameResponse = await readFrame
  expect(frameResponse.status()).toBe(200)
  const frameBody = (await frameResponse.json()) as {
    engine: string
    detected: { hole: string[]; board: string[]; confidence: number }
    sanity: { ok: boolean; problems: string[] }
    decision: unknown | null
  }
  expect(frameBody.engine).toBe('F3-vlm')
  expect(frameBody.detected.hole).toEqual(['As', 'Kd'])
  expect(frameBody.detected.board).toEqual(['2h', '6c', 'Tc'])
  expect(frameBody.detected.confidence).toBe(0)
  expect(frameBody.sanity.ok).toBe(false)
  expect(frameBody.sanity.problems.some(
    (problem) => problem.includes('proposta VLM remota') && problem.includes('calibrada'),
  )).toBe(true)
  expect(frameBody.decision).toBeNull()

  const revoked = page.waitForResponse(
    (response) => response.url().endsWith('/copilot/remote-vlm/consent-sessions')
      && response.request().method() === 'DELETE',
  )
  await dialog.getByRole('button', { name: 'Encerrar compartilhamento' }).click()
  const revokedResponse = await revoked
  expect(revokedResponse.status()).toBe(200)
  expect(await revokedResponse.json()).toEqual({ revoked: true })
  await expect(dialog.getByRole('button', { name: 'Selecionar janela do jogo' })).toBeEnabled()

  expect(page.url()).not.toContain(token)
  expect(await page.evaluate(async () => ({
    cacheKeys: await caches.keys(),
    cookies: document.cookie,
    databases: typeof indexedDB.databases === 'function'
      ? (await indexedDB.databases()).map((database) => database.name ?? '')
      : [],
    local: localStorage.length,
    session: sessionStorage.length,
  }))).toEqual({ cacheKeys: [], cookies: '', databases: [], local: 0, session: 0 })
  assertNoRuntimeFailures()
})

import path from 'node:path'
import { defineConfig } from '@playwright/test'

const host = '127.0.0.1'
const apiPort = 8765
const uiPort = 4177
const root = path.resolve(import.meta.dirname, '..')
const python = path.join(root, 'backend', '.venv', 'Scripts', 'python.exe')
const reuseExistingServer = process.env.PW_REUSE_EXISTING_SERVER === '1'

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} ausente; use npm run test:e2e`)
  return value
}

if (!reuseExistingServer) throw new Error('Playwright direto é bloqueado; use npm run test:e2e')
const backendLogDir = requiredEnvironment('POKER_LOG_DIR')
const frontendDist = requiredEnvironment('POKER_E2E_DIST_DIR')
const playwrightOutput = requiredEnvironment('PLAYWRIGHT_OUTPUT_DIR')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list']],
  outputDir: playwrightOutput,
  // O fluxo integrado atravessa API, renderização e vários diálogos. Em hosts
  // Windows/CI lentos, 45 s transformava contenção de CPU em falso negativo antes
  // mesmo do primeiro clique. O limite continua finito e por teste.
  expect: { timeout: 15_000 },
  timeout: 120_000,
  use: {
    baseURL: `http://${host}:${uiPort}`,
    channel: process.env.PLAYWRIGHT_CHANNEL ?? 'msedge',
    headless: true,
    locale: 'pt-BR',
    // Aciona o contrato CSS de acessibilidade e elimina a espera de "stable" causada
    // por animações, sem forçar cliques nem contornar actionability checks.
    reducedMotion: 'reduce',
    timezoneId: 'America/Sao_Paulo',
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  webServer: [
    {
      command: `.\\.venv\\Scripts\\python.exe -m uvicorn poker_arena.api.app:app --host ${host} --port ${apiPort}`,
      cwd: path.join(root, 'backend'),
      env: {
        POKER_LOG_DIR: backendLogDir,
        POKER_WARMUP: '0',
      },
      url: `http://${host}:${apiPort}/ready`,
      reuseExistingServer,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `"${python}" -m http.server ${uiPort} --bind ${host}`,
      cwd: frontendDist,
      url: `http://${host}:${uiPort}`,
      reuseExistingServer,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})

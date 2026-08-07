import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { configDefaults, defineConfig } from 'vitest/config'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    plugins: [react()],
    cacheDir: env.VITE_CACHE_DIR || 'node_modules/.vite',
    build: { outDir: env.VITE_OUT_DIR || 'dist' },
    server: { port: 5173 },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      exclude: [...configDefaults.exclude, 'e2e/**'],
      css: false,
    },
  }
})

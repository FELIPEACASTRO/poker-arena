import type { FromImageResult } from './types'

export const isVisionExpired = (
  lastSuccessAt: number,
  now: number,
  intervalMs: number,
) => lastSuccessAt > 0 && now - lastSuccessAt > Math.max(4_000, intervalMs * 3)

export const actionableDecision = (vision: FromImageResult | null, stale: boolean) =>
  stale ? null : (vision?.decision ?? null)

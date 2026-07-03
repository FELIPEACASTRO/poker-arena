// Metadados de exibição de cada PERFIL (nível de IA) — FONTE ÚNICA.
// Antes esse mapa estava duplicado em ~8 componentes (risco de drift); agora todos
// importam daqui. Mudou um rótulo/cor? mexe só aqui.
export const LEVELS: Record<string, { name: string; color: string }> = {
  human: { name: 'Você', color: 'var(--accent)' },
  random: { name: 'Iniciante', color: 'var(--lvl-random)' },
  heuristic: { name: 'Amador', color: 'var(--lvl-heuristic)' },
  montecarlo: { name: 'Intermediário', color: 'var(--lvl-montecarlo)' },
  adaptive: { name: 'Adaptativo', color: 'var(--lvl-adaptive)' },
  expert: { name: 'Expert', color: 'var(--lvl-expert)' },
}

/** Nome amigável de um nível (ex.: 'montecarlo' -> 'Intermediário'). */
export const levelName = (id: string): string => LEVELS[id]?.name ?? id

/** Cor (CSS var) de um nível; cinza discreto se desconhecido. */
export const levelColor = (id: string): string => LEVELS[id]?.color ?? 'var(--text-dim)'

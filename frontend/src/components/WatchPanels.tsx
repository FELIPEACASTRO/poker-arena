import { Activity, Gauge, TrendingUp, Trophy } from 'lucide-react'
import { levelName } from '../levels'
import { useGame } from '../store'
import type { BotStat, WatchStats } from '../types'

const pct = (x: number) => `${Math.round(x * 100)}%`
const num = (x: number) => x.toLocaleString('pt-BR')
const POS_PT: Record<string, string> = {
  early: 'cedo',
  middle: 'meio',
  late: 'tarde',
  blinds: 'blinds',
}

function useWatch(): WatchStats | null {
  const { state } = useGame()
  return state?.watch_stats ?? null
}
function useColors(): Record<string, string> {
  return useGame((s) => s.colors)
}
const DIM = 'var(--text-dim)'

function styleTag(b: BotStat): string {
  const loose = b.vpip >= 0.55
  const tight = b.vpip <= 0.35
  const aggr = b.aggression >= 0.35
  if (loose && aggr) return 'Maníaco 🔥'
  if (loose && !aggr) return 'Paga-tudo'
  if (tight && aggr) return 'Sólido (TAG)'
  if (tight && !aggr) return 'Apertado'
  return 'Equilibrado'
}

/** Placar — fichas, lucro e mãos ganhas de cada IA (ranqueado). */
export function LeaderboardPanel() {
  const ws = useWatch()
  const colors = useColors()
  if (!ws) return null
  const max = Math.max(...ws.bots.map((b) => b.stack), 1)
  return (
    <div className="apanel">
      <div className="apanel-h">
        <Trophy size={14} /> Placar do laboratório
      </div>
      <div className="lb-list">
        {ws.bots.map((b, i) => (
          <div key={b.seat} className="lb-row">
            <span className="lb-rank">{i + 1}</span>
            <span className="lb-dot" style={{ background: colors[b.name] ?? DIM }} />
            <span className="lb-name">
              {b.name}
              <small>
                {levelName(b.level)} · {b.hands_won} vit.
              </small>
            </span>
            <div className="lb-bar">
              <span style={{ width: pct(b.stack / max), background: colors[b.name] ?? DIM }} />
            </div>
            <span className="lb-stack">{num(b.stack)}</span>
            <span className={'lb-delta ' + (b.delta >= 0 ? 'pos' : 'neg')}>
              {b.delta >= 0 ? '+' : ''}
              {num(b.delta)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Estilo de cada IA — VPIP e agressão revelam a personalidade do paradigma. */
export function StylePanel() {
  const ws = useWatch()
  const colors = useColors()
  if (!ws) return null
  return (
    <div className="apanel">
      <div className="apanel-h">
        <Gauge size={14} /> Estilo de cada IA
      </div>
      <p className="council-sub">o comportamento que emerge do jogo real</p>
      <div className="style-list">
        {ws.bots.map((b) => (
          <div key={b.seat} className="style-row">
            <div className="style-top">
              <span className="style-name" style={{ color: colors[b.name] ?? 'var(--text)' }}>
                <span className="lb-dot" style={{ background: colors[b.name] ?? DIM }} />
                {b.name}
              </span>
              <span className="style-tag">{styleTag(b)}</span>
            </div>
            <div className="style-metric">
              <span className="sm-k" title="VPIP: % de mãos em que entrou voluntariamente no pote">
                entra em <b>{pct(b.vpip)}</b> das mãos
              </span>
              <div className="sm-bar">
                <span style={{ width: pct(b.vpip), background: 'var(--accent)' }} />
              </div>
            </div>
            <div className="style-metric">
              <span
                className="sm-k"
                title="PFR: % de mãos que ABRIU aumentando no pré-flop. Gap grande entre VPIP e PFR = entra muito mas só pagando (passivo)"
              >
                abre aumentando <b>{pct(b.pfr)}</b>
              </span>
              <div className="sm-bar">
                <span style={{ width: pct(b.pfr), background: 'var(--lvl-heuristic)' }} />
              </div>
            </div>
            <div className="style-metric">
              <span className="sm-k" title="% das ações que são aposta/aumento">
                agressão <b>{pct(b.aggression)}</b>
              </span>
              <div className="sm-bar">
                <span style={{ width: pct(b.aggression), background: 'var(--lvl-expert)' }} />
              </div>
            </div>
            <div className="style-extra">
              <span title="WTSD: viu o flop e foi até o showdown — alto = paga-tudo">
                showdown {pct(b.wtsd)}
              </span>
              <span title="W$SD: % dos showdowns que venceu — qualidade das mãos que mostra">
                vence lá {pct(b.wsd)}
              </span>
              {b.positions
                .filter((p) => p.hands >= 3)
                .map((p) => (
                  <span
                    key={p.bucket}
                    title={`VPIP na região (${p.hands} mãos): disciplina posicional — cedo joga menos, tarde joga mais`}
                  >
                    {POS_PT[p.bucket] ?? p.bucket} {pct(p.vpip)}
                  </span>
                ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Números gerais da sessão automática. */
export function SessionStatsPanel() {
  const ws = useWatch()
  if (!ws) return null
  return (
    <div className="apanel">
      <div className="apanel-h">
        <Activity size={14} /> Estatísticas da sessão
      </div>
      <div className="sess-grid">
        <div>
          <span className="hk">Mãos jogadas</span>
          <span className="hv">{ws.hands}</span>
        </div>
        <div>
          <span className="hk">Showdowns</span>
          <span className="hv">{ws.showdowns}</span>
        </div>
        <div>
          <span className="hk">Maior pote</span>
          <span className="hv">{num(ws.biggest_pot)}</span>
        </div>
        <div>
          <span className="hk">Levado por</span>
          <span className="hv">{ws.biggest_pot_winner ?? '—'}</span>
        </div>
      </div>
    </div>
  )
}

/** Corrida das fichas — stack de cada IA mão a mão (gráfico de linhas). */
export function ChipRacePanel() {
  const ws = useWatch()
  const colors = useColors()
  if (!ws || ws.hands < 2) return null
  const W = 240
  const H = 92
  const pad = 6
  const flat = ws.series.flatMap((s) => s.points).filter((v): v is number => v != null)
  const hi = Math.max(...flat, 1)
  const lo = Math.min(...flat, 0)
  const range = Math.max(hi - lo, 1) // escala entre mín e máx -> disputa visível
  const n = ws.hands
  const x = (i: number) => pad + (i / Math.max(n - 1, 1)) * (W - 2 * pad)
  const y = (v: number) => H - pad - ((v - lo) / range) * (H - 2 * pad)
  // monta o path pulando buracos (null = mãos antes do jogador entrar)
  const pathOf = (pts: (number | null)[]) =>
    pts
      .map((v, i) => {
        if (v == null) return ''
        const start = i === 0 || pts[i - 1] == null
        return `${start ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`
      })
      .join(' ')
      .trim()
  return (
    <div className="apanel">
      <div className="apanel-h">
        <TrendingUp size={14} /> Corrida das fichas
      </div>
      <svg className="race" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {ws.series.map((s) => {
          const d = pathOf(s.points)
          if (!d) return null
          return (
            <path
              key={s.seat}
              d={d}
              fill="none"
              stroke={colors[s.name] ?? DIM}
              strokeWidth={2}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          )
        })}
      </svg>
      <div className="race-legend">
        {ws.series.map((s) => (
          <span key={s.seat} className="rl">
            <i style={{ background: colors[s.name] ?? DIM }} />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  )
}

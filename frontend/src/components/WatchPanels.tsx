import { Activity, Gauge, TrendingUp, Trophy } from 'lucide-react'
import { levelName } from '../levels'
import { boundedPoints } from '../series'
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
const MIN_STYLE_HANDS = 30
const MIN_POSITION_HANDS = 20
const CI_BASE_KEYS = [
  'preflop_open_raise',
  'preflop_limp',
  'preflop_isolation_raise',
  'preflop_three_bet',
  'preflop_call_vs_raise',
  'preflop_squeeze',
  'preflop_four_bet',
  'postflop_fold_to_bet',
  'postflop_aggression_ip',
  'postflop_aggression_oop',
]

function competitiveKeys(bot: BotStat): string[] {
  const keys = [
    `position_exact_${bot.position}_vpip`,
    `position_exact_${bot.position}_pfr`,
    ...CI_BASE_KEYS,
  ]
  if (['CO', 'BTN', 'SB'].includes(bot.position)) keys.push('late_position_steal')
  if (['SB', 'BB'].includes(bot.position)) keys.push('blind_defense', 'blind_fold_to_steal')
  if (bot.position === 'SB') keys.push('blind_vs_blind_sb_open')
  if (bot.position === 'BB') keys.push('blind_vs_blind_bb_defense')
  return keys
}

function ciPct(value: number | null): string {
  return value == null ? '—' : pct(value)
}

function recencyLabel(direction: string): string {
  if (direction === 'more_aggressive') return 'mais agressivo recentemente'
  if (direction === 'more_passive') return 'mais passivo recentemente'
  if (direction === 'stable') return 'sem desvio recente relevante'
  return 'recência ainda sem amostra'
}

function CompetitiveProfileBlock({ bot }: { bot: BotStat }) {
  const profile = bot.competitive_profile
  if (!profile) return null
  const signals = competitiveKeys(bot).map((key) => profile.signals.find((signal) => signal.key === key)).filter(
    (signal) => signal != null,
  )
  return (
    <details className="ci-details">
      <summary>
        Inteligência contextual <b>{bot.position || 'posição pendente'}</b>
      </summary>
      <p className="ci-scope">Sessão local · somente descritivo · nenhuma ação recomendada</p>
      <div className="ci-grid">
        {signals.map((signal) => (
          <div className={'ci-signal ' + (signal.ready ? 'ready' : 'waiting')} key={signal.key}>
            <span>{signal.label}</span>
            {signal.ready ? (
              <b>
                {ciPct(signal.posterior_mean)}{' '}
                <small>
                  IC95 {ciPct(signal.interval95_low)}–{ciPct(signal.interval95_high)} · n=
                  {signal.opportunities}
                </small>
              </b>
            ) : (
              <b>
                abstém{' '}
                <small>
                  n={signal.opportunities}/{profile.minimum_opportunities}
                </small>
              </b>
            )}
          </div>
        ))}
      </div>
      <p className="ci-recency">
        Recência EWMA: {recencyLabel(profile.recency.direction)} · {profile.recency.actions} ações
      </p>
      <p className="ci-method">
        Média {profile.posterior_method}; {profile.interval_method}. Frequência não prova causa nem
        força estratégica.
      </p>
    </details>
  )
}

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

/** Placar — fichas, resultado líquido e mãos ganhas de cada IA (ranqueado). */
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
          <div key={b.player_id} className="lb-row">
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
            <span
              className={'lb-delta ' + (b.delta >= 0 ? 'pos' : 'neg')}
              title={`Resultado líquido após ${num(b.buy_in_total)} fichas em buy-ins/recompras`}
            >
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
      <p className="council-sub">estimativas descritivas desta sessão</p>
      <div className="style-list">
        {ws.bots.map((b) => (
          <div key={b.player_id} className="style-row">
            <div className="style-top">
              <span className="style-name" style={{ color: colors[b.name] ?? 'var(--text)' }}>
                <span className="lb-dot" style={{ background: colors[b.name] ?? DIM }} />
                {b.name}
              </span>
              <span className="style-tag">
                {b.hands_dealt < MIN_STYLE_HANDS
                  ? `amostra insuficiente (${b.hands_dealt}/${MIN_STYLE_HANDS})`
                  : styleTag(b)}
              </span>
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
                title="PFR: % de mãos em que aumentou no pré-flop. Gap grande entre VPIP e PFR = entra muito mas só pagando (passivo)"
              >
                aumenta pré-flop <b>{pct(b.pfr)}</b>
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
                .filter((p) => p.hands >= MIN_POSITION_HANDS)
                .map((p) => (
                  <span
                    key={p.bucket}
                    title={`VPIP na região (${p.hands} mãos): disciplina posicional — cedo joga menos, tarde joga mais`}
                  >
                    {POS_PT[p.bucket] ?? p.bucket} {pct(p.vpip)}
                  </span>
                ))}
            </div>
            <CompetitiveProfileBlock bot={b} />
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
  const series = ws.series.map((item) => ({ ...item, points: boundedPoints(item.points) }))
  const flat = series.flatMap((s) => s.points).filter((v): v is number => v != null)
  const hi = flat.reduce((highest, value) => Math.max(highest, value), 1)
  const lo = flat.reduce((lowest, value) => Math.min(lowest, value), 0)
  const range = Math.max(hi - lo, 1) // escala entre mín e máx -> disputa visível
  const n = Math.max(...series.map((item) => item.points.length), 1)
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
      {ws.series_truncated && (
        <p className="council-sub">
          janela ao vivo desde a mão {ws.series_start_hand}; o histórico completo permanece na Auditoria
        </p>
      )}
      <svg className="race" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {series.map((s) => {
          const d = pathOf(s.points)
          if (!d) return null
          return (
            <path
              key={s.player_id}
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
          <span key={s.player_id} className="rl">
            <i style={{ background: colors[s.name] ?? DIM }} />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  )
}

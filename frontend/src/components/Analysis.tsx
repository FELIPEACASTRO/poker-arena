import type { CSSProperties } from 'react'
import { Brain, Coins, Eye, Sigma, Target, Users } from 'lucide-react'
import { levelColor, levelName } from '../levels'
import { useGame } from '../store'
import type { Analysis } from '../types'

const HAND_PT: Record<string, string> = {
  'High Card': 'Carta alta',
  Pair: 'Par',
  'Two Pair': 'Dois pares',
  'Three of a Kind': 'Trinca',
  Straight: 'Sequência',
  Flush: 'Flush',
  'Full House': 'Full house',
  'Four of a Kind': 'Quadra',
  'Straight Flush': 'Straight flush',
}
const pt = (h: string | null) => (h ? (HAND_PT[h] ?? h) : '—')
const pctOf = (x: number) => `${Math.round(x * 100)}%`

function useAnalysis(): Analysis | null {
  const { state } = useGame()
  return state?.analysis ?? null
}
function seatName(seat: number): string {
  const { state } = useGame.getState()
  return state?.seats.find((s) => s.seat === seat)?.name ?? `#${seat}`
}

function Donut({ pct }: { pct: number }) {
  const r = 30
  const c = 2 * Math.PI * r
  return (
    <svg viewBox="0 0 80 80" width="78" height="78" className="donut">
      <circle cx="40" cy="40" r={r} fill="none" stroke="var(--surface-3)" strokeWidth="8" />
      <circle
        cx="40"
        cy="40"
        r={r}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="8"
        strokeDasharray={`${c * pct} ${c}`}
        strokeLinecap="round"
        transform="rotate(-90 40 40)"
      />
      <text x="40" y="45" textAnchor="middle" fontSize="18" fontWeight="600" fill="var(--text)">
        {Math.round(pct * 100)}%
      </text>
    </svg>
  )
}

// ---------- Equity + Win Probability ----------
export function EquityPanel() {
  const a = useAnalysis()
  if (!a) return null
  return (
    <div className="apanel">
      <div className="apanel-h">
        <Target size={15} /> Equity & vitória
      </div>
      <div className="equity-row">
        <Donut pct={a.equity} />
        <div className="winprobs">
          {a.win_probs.map((w) => (
            <div key={w.seat} className="winprob">
              <span className="wp-name">{seatName(w.seat)}</span>
              <span className="wp-bar">
                <span style={{ width: pctOf(w.prob), background: 'var(--accent)' }} />
              </span>
              <span className="wp-pct mono">{pctOf(w.prob)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ---------- Sua mão (decision engine) ----------
export function HandPanel() {
  const a = useAnalysis()
  if (!a) return null
  const need = a.pot_odds
  const good = a.equity >= need
  return (
    <div className="apanel">
      <div className="apanel-h">
        <Sigma size={15} /> Sua mão
      </div>
      <div className="hand-grid">
        <div>
          <span className="hk">Mão</span>
          <span className="hv">{pt(a.hand_name)}</span>
        </div>
        <div>
          <span className="hk">Outs</span>
          <span className="hv mono">{a.outs}</span>
        </div>
        <div>
          <span className="hk">A nut é</span>
          <span className="hv">{pt(a.nut)}</span>
        </div>
        <div>
          <span className="hk">Board</span>
          <span className="hv">{a.texture ?? '—'}</span>
        </div>
        <div>
          <span className="hk">Posição</span>
          <span className="hv">{a.position}</span>
        </div>
        <div>
          <span className="hk">SPR</span>
          <span className="hv mono">{a.spr ?? '—'}</span>
        </div>
      </div>
      {a.draws.length > 0 && <p className="hand-draws">🎯 {a.draws.join(' · ')}</p>}
      {(a.blockers ?? []).map((b, i) => (
        <p key={i} className="hand-draws" title="Blocker: uma carta sua remove combinações das mãos mais fortes possíveis do vilão">
          🧱 {b}
        </p>
      ))}
      <div className={'potodds ' + (good ? 'is-good' : 'is-bad')}>
        Pot odds: precisa de <b className="mono">{pctOf(need)}</b>, você tem{' '}
        <b className="mono">{pctOf(a.equity)}</b> → {good ? 'pagar é +EV ✅' : 'pagar é −EV ⚠️'}
      </div>
      {a.mdf != null && (
        <p
          className="hand-gto"
          title="MDF (frequência mínima de defesa): pela teoria GTO, contra essa aposta você precisa continuar (pagar/aumentar) pelo menos essa fração das vezes — desistir mais que isso te deixa explorável por blefes. Referência teórica (heads-up/river)."
        >
          🛡️ Defesa mínima (MDF): continue <b className="mono">{pctOf(a.mdf)}</b> das vezes
          contra esse tamanho de aposta.
        </p>
      )}
      {a.realization && (
        <p
          className="hand-gto"
          title="Equity Realization: equity é a chance no showdown, mas quanto dela vira EV depende da posição — quem fecha a ação realiza mais; fora de posição realiza menos."
        >
          {a.realization === 'alta' ? '📈' : a.realization === 'baixa' ? '📉' : '➖'} Realização
          da equity <b>{a.realization}</b>
          {a.realization_why ? ` — ${a.realization_why}` : ''}
        </p>
      )}
    </div>
  )
}

// ---------- Expected Value (recomendação do Expert) ----------
export function EVPanel() {
  const a = useAnalysis()
  if (!a || !a.best_action) return null
  return (
    <div className="apanel apanel-ev">
      <div className="apanel-h">
        <Coins size={15} /> Valor esperado
      </div>
      <div className="ev-best">
        <span className="ev-k">Melhor jogada</span>
        <span className="ev-v" style={{ color: 'var(--accent)' }}>
          {a.best_action}
          {a.best_amount ? ` ${a.best_amount}` : ''}
        </span>
      </div>
      <div className="ev-best">
        <span className="ev-k">EV de pagar</span>
        <span className={'ev-v mono ' + (a.ev_call >= 0 ? 'pos' : 'neg')}>
          {a.ev_call >= 0 ? '+' : ''}
          {a.ev_call} fichas
        </span>
      </div>
      {a.confidence != null && (
        <div className="ev-conf">
          <span className="ev-k">Confiança do Expert</span>
          <span className="ev-conf-bar">
            <span style={{ width: pctOf(a.confidence), background: 'var(--accent)' }} />
          </span>
          <span className="mono">{pctOf(a.confidence)}</span>
        </div>
      )}
    </div>
  )
}

// ---------- Conselho das IAs ----------
export function CouncilPanel() {
  const a = useAnalysis()
  if (!a || a.council.length === 0) return null
  return (
    <div className="apanel">
      <div className="apanel-h">
        <Users size={15} /> Conselho das IAs
      </div>
      <p className="council-sub">o que cada cérebro faria na SUA mão:</p>
      <div className="council-list">
        {a.council.map((c) => (
          <div
            key={c.level}
            className="council-row"
            style={{ '--c': levelColor(c.level) } as unknown as CSSProperties}
          >
            <span className="council-dot" />
            <span className="council-name">{levelName(c.level)}</span>
            <span className="council-act">
              {c.action}
              {c.amount ? ` ${c.amount}` : ''}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------- Você pelos olhos da IA ----------
export function ProfilePanel() {
  const a = useAnalysis()
  if (!a) return null
  const learned = a.your_profile_samples >= 8
  return (
    <div className="apanel">
      <div className="apanel-h">
        <Eye size={15} /> Você pelos olhos da IA
      </div>
      {!learned ? (
        <p className="profile-empty">
          <Brain size={14} /> ainda te observando ({a.your_profile_samples} jogadas)…
        </p>
      ) : (
        <p className="profile-txt">
          A IA aprendeu: você desiste <b className="mono">{pctOf(a.your_profile_fold)}</b> diante de
          apostas e joga{' '}
          <b>{a.your_profile_aggr > 0.55 ? 'agressivo' : a.your_profile_aggr < 0.45 ? 'passivo' : 'equilibrado'}</b>
          . {a.your_profile_fold > 0.55 ? 'O Adaptativo vai te blefar mais.' : ''}
        </p>
      )}
    </div>
  )
}

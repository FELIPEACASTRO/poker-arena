import { useState } from 'react'
import { motion } from 'framer-motion'
import { Compass, Lightbulb, Sparkles, X } from 'lucide-react'
import { api } from '../api'
import { levelColor, levelName } from '../levels'
import type { CopilotResult } from '../types'

const VERDICT: Record<string, { c: string; icon: string }> = {
  good: { c: 'var(--pos)', icon: '✅' },
  ok: { c: 'var(--warn)', icon: '⚠️' },
  bad: { c: 'var(--neg)', icon: '⛔' },
}

const cards = (s: string) => s.trim().split(/[\s,]+/).filter(Boolean)

export default function CopilotScreen({ onClose }: { onClose: () => void }) {
  const [hole, setHole] = useState('As Ks')
  const [board, setBoard] = useState('Qs Js 2h')
  const [pot, setPot] = useState(100)
  const [toCall, setToCall] = useState(40)
  const [stack, setStack] = useState(1000)
  const [opp, setOpp] = useState(1)
  const [inPos, setInPos] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [res, setRes] = useState<CopilotResult | null>(null)

  async function analyze() {
    setBusy(true)
    setError(null)
    try {
      const r = await api.copilot({
        hole: cards(hole),
        board: cards(board),
        pot,
        to_call: toCall,
        my_stack: stack,
        num_opponents: opp,
        in_position: inPos,
      })
      setRes(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao analisar o spot')
      setRes(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.div
      className="guide-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        className="guide-modal copilot-modal"
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: 'spring', stiffness: 260, damping: 26 }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="guide-head">
          <h1>
            <Sparkles size={20} /> Copiloto de mãos
            <span className="guide-sub">revisão pós-jogo · 100% offline</span>
          </h1>
          <button className="ico-btn" onClick={onClose} aria-label="Fechar">
            <X size={18} />
          </button>
        </header>

        <p className="guide-intro">
          Descreva um spot que você jogou (ou quer estudar) — suas cartas, o board, o pote e o
          preço — e o copiloto te dá a <b>leitura completa</b> e <b>o que fazer</b>, com o veredito
          de cada jogada. É o motor da Arena aplicado a qualquer situação. 🧭
        </p>

        <div className="copilot-form">
          <label className="cp-field cp-wide">
            <span>Suas 2 cartas</span>
            <input value={hole} onChange={(e) => setHole(e.target.value)} placeholder="As Ks" />
          </label>
          <label className="cp-field cp-wide">
            <span>Board (0/3/4/5 cartas)</span>
            <input value={board} onChange={(e) => setBoard(e.target.value)} placeholder="Qs Js 2h" />
          </label>
          <label className="cp-field">
            <span>Pote</span>
            <input type="number" min={0} value={pot} onChange={(e) => setPot(+e.target.value)} />
          </label>
          <label className="cp-field">
            <span>Custa pagar</span>
            <input type="number" min={0} value={toCall} onChange={(e) => setToCall(+e.target.value)} />
          </label>
          <label className="cp-field">
            <span>Seu stack</span>
            <input type="number" min={1} value={stack} onChange={(e) => setStack(+e.target.value)} />
          </label>
          <label className="cp-field">
            <span>Oponentes</span>
            <input type="number" min={1} max={8} value={opp} onChange={(e) => setOpp(+e.target.value)} />
          </label>
          <label className="cp-field cp-check">
            <input type="checkbox" checked={inPos} onChange={(e) => setInPos(e.target.checked)} />
            <span>Em posição (ajo por último)</span>
          </label>
          <button className="btn btn-accent cp-go" onClick={analyze} disabled={busy}>
            {busy ? 'Analisando…' : 'Analisar spot'}
          </button>
        </div>
        <p className="cp-hint">
          Formato das cartas: <code>As</code> (Ás de espadas), <code>Kh</code> (Rei de copas),{' '}
          <code>Td</code> (10 de ouros), <code>7c</code> (7 de paus).
        </p>

        {error && <div className="cp-error">⚠️ {error}</div>}

        {res && (
          <div className="cp-result">
            <div className="cp-headline">
              <Lightbulb size={18} /> {res.headline}
            </div>

            <div className="cp-grid">
              <div><span>Mão</span><b>{res.hand_label ?? '—'}</b></div>
              <div><span>Chance real (equity)</span><b className="mono">{res.equity_pct}%</b></div>
              <div><span>Preço (pot odds)</span><b className="mono">{res.pot_odds_pct}%</b></div>
              <div><span>EV de pagar</span><b className="mono">{res.ev_call >= 0 ? '+' : ''}{res.ev_call}</b></div>
              {res.mdf_pct != null && <div><span>Defesa mín. (MDF)</span><b className="mono">{res.mdf_pct}%</b></div>}
              <div><span>Outs</span><b className="mono">{res.outs}</b></div>
              {res.nut && <div><span>A nut é</span><b>{res.nut}</b></div>}
              {res.texture && <div><span>Board</span><b>{res.texture}</b></div>}
              {res.spr != null && <div><span>SPR</span><b className="mono">{res.spr}</b></div>}
              <div><span>Realização</span><b>{res.realization}</b></div>
            </div>

            {res.draws.length > 0 && <p className="cp-draws">🎯 {res.draws.join(' · ')}</p>}
            {res.blockers.map((b, i) => (
              <p className="cp-draws" key={i}>🧱 {b}</p>
            ))}

            <h3 className="cp-h3">As jogadas, avaliadas</h3>
            <div className="cp-options">
              {res.options.map((o) => (
                <div
                  className={'cp-opt' + (o.chosen ? ' is-rec' : '')}
                  key={o.action}
                  style={{ '--vc': VERDICT[o.verdict]?.c } as React.CSSProperties}
                >
                  <div className="cp-opt-top">
                    <span className="cp-opt-label">
                      {VERDICT[o.verdict]?.icon} {o.label}
                    </span>
                    {o.chosen && <span className="cp-rec-badge">recomendada</span>}
                  </div>
                  <p>{o.reason}</p>
                </div>
              ))}
            </div>

            <h3 className="cp-h3">O que cada IA faria aqui</h3>
            <div className="cp-council">
              {res.council.map((c) => (
                <div className="cp-vote" key={c.level} style={{ borderColor: levelColor(c.level) }}>
                  <span className="cp-vote-lvl" style={{ color: levelColor(c.level) }}>
                    {levelName(c.level)}
                  </span>
                  <span className="cp-vote-act">
                    {c.action} {c.amount ? c.amount : ''}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="cp-ethic">
          <Compass size={15} /> Isto é um <b>treinador de estudo</b> — analisa spots que você
          descreve, offline. Usar assistência assim <b>durante</b> uma partida valendo em qualquer
          site é proibido (RTA); aqui é como revisar uma partida de xadrez com o motor <i>depois</i>.
        </div>

        <button className="btn btn-ghost guide-back" onClick={onClose}>
          Fechar
        </button>
      </motion.div>
    </motion.div>
  )
}

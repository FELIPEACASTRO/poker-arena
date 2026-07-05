import { useState } from 'react'
import { motion } from 'framer-motion'
import { Compass, Lightbulb, Sparkles, X } from 'lucide-react'
import { api } from '../api'
import { levelColor, levelName } from '../levels'
import type { CopilotResult, FromImageResult, HandReviewResult } from '../types'

const VERDICT: Record<string, { c: string; icon: string }> = {
  good: { c: 'var(--pos)', icon: '✅' },
  ok: { c: 'var(--warn)', icon: '⚠️' },
  bad: { c: 'var(--neg)', icon: '⛔' },
}

const cards = (s: string) => s.trim().split(/[\s,]+/).filter(Boolean)

export default function CopilotScreen({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<'spot' | 'hand' | 'image'>('spot')
  const [hole, setHole] = useState('As Ks')
  const [board, setBoard] = useState('Qs Js 2h')
  const [pot, setPot] = useState(100)
  const [toCall, setToCall] = useState(40)
  const [stack, setStack] = useState(1000)
  const [opp, setOpp] = useState(1)
  const [inPos, setInPos] = useState(true)
  const [position, setPosition] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [res, setRes] = useState<CopilotResult | null>(null)
  // aba "colar mão" (histórico PHH)
  const [phh, setPhh] = useState('')
  const [player, setPlayer] = useState(1)
  const [review, setReview] = useState<HandReviewResult | null>(null)
  // aba "da imagem" (visão computacional)
  const [imgPreview, setImgPreview] = useState<string | null>(null)
  const [vision, setVision] = useState<FromImageResult | null>(null)

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
        position: position || null,
      })
      setRes(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao analisar o spot')
      setRes(null)
    } finally {
      setBusy(false)
    }
  }

  async function analyzeHand() {
    setBusy(true)
    setError(null)
    try {
      setReview(await api.reviewHand(phh, player))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao revisar a mão')
      setReview(null)
    } finally {
      setBusy(false)
    }
  }

  async function analyzeImage(file: File) {
    setImgPreview(URL.createObjectURL(file))
    setBusy(true)
    setError(null)
    setVision(null)
    try {
      setVision(
        await api.fromImage(file, {
          to_call: toCall,
          my_stack: stack,
          num_opponents: opp,
          in_position: inPos,
          position: position || undefined,
        }),
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao ler a imagem')
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
          Duas formas de usar: descreva <b>um spot</b> à mão, ou <b>cole o histórico</b> de uma mão
          inteira (o texto que o jogo exporta no fim) e revise todas as suas decisões de uma vez. 🧭
        </p>

        <div className="cp-tabs">
          <button className={mode === 'spot' ? 'is-on' : ''} onClick={() => setMode('spot')}>
            Spot único
          </button>
          <button className={mode === 'hand' ? 'is-on' : ''} onClick={() => setMode('hand')}>
            Colar mão (histórico)
          </button>
          <button className={mode === 'image' ? 'is-on' : ''} onClick={() => setMode('image')}>
            Da imagem (visão)
          </button>
        </div>

        {mode === 'image' && (
          <div className="cp-hand">
            <p className="cp-hint">
              Envie um <b>screenshot 2D</b> da mesa — a visão lê suas cartas, o board e o pote,
              valida (regras de poker) e o Copiloto decide. Estudo pós-jogo, offline.
            </p>
            <div className="copilot-form">
              <label className="cp-field cp-wide cp-upload">
                <span>Screenshot da mesa (PNG/JPG)</span>
                <input
                  type="file"
                  accept="image/*"
                  onChange={(e) => e.target.files?.[0] && analyzeImage(e.target.files[0])}
                />
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
                <span>Em posição</span>
              </label>
            </div>

            {error && <div className="cp-error">⚠️ {error}</div>}
            {imgPreview && <img className="cp-imgprev" src={imgPreview} alt="mesa enviada" />}

            {vision && (
              <div className="cp-review">
                <div className="cp-review-sum">
                  👁️ Detectado <span className="cp-engine">{vision.engine === 'F2-onnx' ? 'IA treinada' : 'baseline'}</span>: <b>{vision.detected.hole.join(' ') || '—'}</b>
                  {vision.detected.board.length > 0 && <> · board <b>{vision.detected.board.join(' ')}</b></>}
                  {vision.detected.pot != null && (
                    <> · pote <b>{vision.detected.pot}</b>
                    {vision.detected.pot_source === 'ocr' && <sup className="cp-ocr"> OCR</sup>}</>
                  )}
                  {vision.detected.n_players > 0 && <> · <b>{vision.detected.n_players}</b> jogadores</>}
                  {vision.detected.position && <> · posição <b>{vision.detected.position}</b></>}
                  {Object.keys(vision.detected.stacks ?? {}).length > 0 && (
                    <> · stacks <b>{Object.values(vision.detected.stacks).join(', ')}</b></>
                  )}{' '}
                  <small>(confiança {Math.round(vision.detected.confidence * 100)}%)</small>
                </div>
                {!vision.sanity.ok && (
                  <div className="cp-error">
                    🛡️ Abstive: {vision.sanity.problems.join('; ')} — leitura implausível, não decido com lixo.
                  </div>
                )}
                {vision.sanity.warnings.length > 0 && (
                  <p className="cp-hint">⚠️ {vision.sanity.warnings.join(' · ')}</p>
                )}
                {vision.decision && (
                  <div className="cp-headline">
                    <Lightbulb size={18} /> {vision.decision.headline}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {mode === 'hand' && (
          <div className="cp-hand">
            <label className="cp-field cp-wide">
              <span>Cole o histórico da mão (formato PHH)</span>
              <textarea
                value={phh}
                onChange={(e) => setPhh(e.target.value)}
                rows={7}
                placeholder={"variant = 'NT'\nblinds_or_straddles = [50, 100, 0, 0, 0, 0]\nstarting_stacks = [10000, ...]\nactions = ['d dh p1 AsKh', ...]\nplayers = ['Você', ...]"}
              />
            </label>
            <div className="cp-hand-go">
              <label className="cp-field">
                <span>Qual jogador é você?</span>
                <input
                  type="number"
                  min={1}
                  max={9}
                  value={player}
                  onChange={(e) => setPlayer(+e.target.value)}
                />
              </label>
              <button className="btn btn-accent" onClick={analyzeHand} disabled={busy || !phh.trim()}>
                {busy ? 'Revisando…' : 'Revisar minhas decisões'}
              </button>
            </div>
            <p className="cp-hint">
              O PHH é o padrão de pesquisa (ex.: as mãos do dataset do Pluribus). Só analisa mãos em
              que suas cartas aparecem — é <b>estudo pós-jogo</b>, como rever um PGN de xadrez.
            </p>

            {error && <div className="cp-error">⚠️ {error}</div>}

            {review && (
              <div className="cp-review">
                <div className="cp-review-sum">
                  Revisando <b>{review.hero}</b>: <b>{review.matched}/{review.total}</b> das suas
                  jogadas bateram com a recomendação do copiloto.
                </div>
                {review.decisions.map((d, i) => (
                  <div className={'cp-dec' + (d.matched ? ' is-ok' : ' is-diff')} key={i}>
                    <div className="cp-dec-top">
                      <span className="cp-dec-street">{d.street}</span>
                      <span className="cp-dec-cards">
                        {d.hole.join(' ')} {d.board.length > 0 && `· ${d.board.join(' ')}`}
                      </span>
                      <span className="cp-dec-eq mono">equity {d.equity_pct}%</span>
                    </div>
                    <div className="cp-dec-verdict">
                      Você: <b>{d.your_action}</b> · Copiloto: <b>{d.recommendation_label}</b>{' '}
                      {d.matched ? '✅' : '⚠️ diferente'}
                    </div>
                    <p className="cp-dec-why">{d.headline}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {mode === 'spot' && (
        <>
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
          <label className="cp-field">
            <span>Sua posição (opcional)</span>
            <select value={position} onChange={(e) => setPosition(e.target.value)}>
              <option value="">— não sei —</option>
              {['UTG', 'UTG+1', 'MP1', 'MP2', 'DJ', 'HJ', 'BTN', 'SB', 'BB'].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
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
              {res.position && <div><span>Posição</span><b>{res.position}</b></div>}
              {res.num_players ? <div><span>Participantes</span><b className="mono">{res.num_players}</b></div> : null}
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
        </>
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

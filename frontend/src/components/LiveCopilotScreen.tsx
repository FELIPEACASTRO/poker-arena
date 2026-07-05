import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Lightbulb, MonitorPlay, Square, X } from 'lucide-react'
import { api } from '../api'
import type { FromImageResult } from '../types'

/**
 * Copiloto AO VIVO — a própria solução captura a tela do jogo (getDisplayMedia),
 * manda cada quadro pro motor (/copilot/from-image) e mostra o que fazer em tempo real.
 * Uso no demo: janela 1 = o jogo; janela 2 (esta) = o copiloto capturando + analisando.
 */
export default function LiveCopilotScreen({ onClose }: { onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const inFlight = useRef(false)
  const [capturing, setCapturing] = useState(false)
  const [everyMs, setEveryMs] = useState(1500)
  const [toCall, setToCall] = useState(0)
  const [stack, setStack] = useState(1000)
  const [error, setError] = useState<string | null>(null)
  const [vision, setVision] = useState<FromImageResult | null>(null)
  const [frames, setFrames] = useState(0)

  async function start() {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 2 },
        audio: false,
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      // se o usuário parar o compartilhamento pela barra do navegador
      stream.getVideoTracks()[0].addEventListener('ended', stop)
      setCapturing(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Não foi possível capturar a tela')
    }
  }

  function stop() {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    setCapturing(false)
  }

  // loop de captura: desenha o quadro num canvas -> PNG -> motor
  useEffect(() => {
    if (!capturing) return
    const canvas = document.createElement('canvas')
    const id = window.setInterval(async () => {
      const v = videoRef.current
      if (!v || !v.videoWidth || inFlight.current) return
      canvas.width = v.videoWidth
      canvas.height = v.videoHeight
      canvas.getContext('2d')?.drawImage(v, 0, 0)
      const blob: Blob | null = await new Promise((r) => canvas.toBlob(r, 'image/png'))
      if (!blob) return
      inFlight.current = true
      try {
        const file = new File([blob], 'frame.png', { type: 'image/png' })
        const r = await api.fromImage(file, {
          to_call: toCall,
          my_stack: stack,
          num_opponents: 1,
          in_position: true,
        })
        setVision(r)
        setFrames((n) => n + 1)
        setError(null)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Erro ao ler o quadro')
      } finally {
        inFlight.current = false
      }
    }, everyMs)
    return () => window.clearInterval(id)
  }, [capturing, everyMs, toCall, stack])

  useEffect(() => () => stop(), []) // limpa ao fechar

  const d = vision?.decision ?? null
  const det = vision?.detected ?? null
  const abstain = vision != null && !vision.sanity.ok

  return (
    <motion.div
      className="guide-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        className="guide-modal copilot-modal cp-live"
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: 'spring', stiffness: 260, damping: 26 }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="guide-head">
          <h1>
            <MonitorPlay size={20} /> Copiloto ao Vivo
            <span className="guide-sub">captura a tela do jogo e diz o que fazer</span>
          </h1>
          <button className="ico-btn" onClick={onClose} aria-label="Fechar">
            <X size={18} />
          </button>
        </header>
        <p className="guide-intro">
          A solução <b>captura a tela do jogo sozinha</b> e mostra o que fazer em tempo real.
          Abra o jogo numa janela, clique em <b>Capturar</b> e escolha a janela do jogo. 🖥️
        </p>

        <div className="cp-live-controls">
          {!capturing ? (
            <button className="btn btn-primary" onClick={start}>
              <MonitorPlay size={16} /> Capturar tela do jogo
            </button>
          ) : (
            <button className="btn btn-ghost" onClick={stop}>
              <Square size={16} /> Parar
            </button>
          )}
          <label className="cp-field">
            <span>Ler a cada</span>
            <select value={everyMs} onChange={(e) => setEveryMs(Number(e.target.value))}>
              <option value={1000}>1s</option>
              <option value={1500}>1,5s</option>
              <option value={2500}>2,5s</option>
              <option value={4000}>4s</option>
            </select>
          </label>
          <label className="cp-field">
            <span>A pagar</span>
            <input type="number" value={toCall} onChange={(e) => setToCall(Number(e.target.value))} />
          </label>
          <label className="cp-field">
            <span>Seu stack</span>
            <input type="number" value={stack} onChange={(e) => setStack(Number(e.target.value))} />
          </label>
          {capturing && <span className="cp-live-dot">● lendo ({frames})</span>}
        </div>

        {error && <div className="cp-error">⚠️ {error}</div>}

        <div className="cp-live-grid">
          <div className="cp-live-preview">
            <video ref={videoRef} muted playsInline className="cp-live-video" />
            {!capturing && <div className="cp-live-hint">a captura aparece aqui</div>}
          </div>

          <div className="cp-live-read">
            {det && (
              <div className="cp-review-sum">
                👁️ <span className="cp-engine">{vision?.engine === 'F2-onnx' ? 'IA treinada' : 'baseline'}</span>{' '}
                <b>{det.hole.join(' ') || '—'}</b>
                {det.board.length > 0 && <> · board <b>{det.board.join(' ')}</b></>}
                {det.pot != null && <> · pote <b>{det.pot}</b></>}
                {det.n_players > 0 && <> · <b>{det.n_players}</b> jog.</>}
                {det.position && <> · <b>{det.position}</b></>}{' '}
                <small>(conf {Math.round(det.confidence * 100)}%)</small>
              </div>
            )}
            {abstain && (
              <div className="cp-error">
                🛡️ Aguardando leitura confiável… (abstém em vez de arriscar) —{' '}
                {vision?.sanity.problems.join('; ')}
              </div>
            )}
            {d && (
              <>
                <div className="cp-headline">
                  <Lightbulb size={18} /> {d.headline}
                </div>
                <div className="cp-grid">
                  <div><span>Recomendação</span><b>{d.recommendation_label}</b></div>
                  <div><span>Chance (equity)</span><b className="mono">{d.equity_pct}%</b></div>
                  <div><span>Pot odds</span><b className="mono">{d.pot_odds_pct}%</b></div>
                  <div><span>EV de pagar</span><b className="mono">{Math.round(d.ev_call)}</b></div>
                </div>
                <div className="cp-options">
                  {d.options.map((o) => (
                    <div key={o.action} className={`cp-opt v-${o.verdict}${o.chosen ? ' is-chosen' : ''}`}>
                      <b>{o.label}</b> <small>{o.reason}</small>
                    </div>
                  ))}
                </div>
              </>
            )}
            {!vision && capturing && <div className="cp-live-hint">lendo o primeiro quadro…</div>}
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Lightbulb, MonitorPlay, Play, Square, X } from 'lucide-react'
import { API_BASE, api } from '../api'
import { fitWithin } from '../capture'
import { actionableDecision, isVisionExpired } from '../liveVision'
import type { FromImageResult } from '../types'
import { useDialogA11y } from '../useDialogA11y'
import VisionDiagnostics from './VisionDiagnostics'

const isAbort = (caught: unknown) => caught instanceof DOMException && caught.name === 'AbortError'
const errorMessage = (caught: unknown, fallback: string) => {
  if (caught && typeof caught === 'object' && 'message' in caught) {
    const message = String((caught as { message?: unknown }).message ?? '').trim()
    if (message) return message
  }
  return fallback
}
const safeNumber = (value: number, current: number, min: number) =>
  Number.isFinite(value) ? Math.max(min, value) : current
type DisplaySurface = 'window' | 'monitor' | 'browser' | 'unknown'
type CaptureLayout = 'same-monitor' | 'second-monitor'
type WindowOnlyDisplayMediaOptions = DisplayMediaStreamOptions & {
  monitorTypeSurfaces: 'exclude'
  preferCurrentTab: false
  selfBrowserSurface: 'exclude'
  surfaceSwitching: 'exclude'
}
const WINDOW_ONLY_CAPTURE_OPTIONS: WindowOnlyDisplayMediaOptions = {
  video: { displaySurface: 'window', frameRate: { ideal: 2, max: 2 } },
  audio: false,
  monitorTypeSurfaces: 'exclude',
  preferCurrentTab: false,
  selfBrowserSurface: 'exclude',
  surfaceSwitching: 'exclude',
}
const layoutTarget = (layout: CaptureLayout) => layout === 'second-monitor'
  ? 'no outro monitor'
  : 'neste mesmo monitor'
const sourceLabel = (surface: DisplaySurface) => ({
  window: 'Janela selecionada', monitor: 'Tela inteira selecionada',
  browser: 'Guia do navegador selecionada', unknown: 'Fonte não verificável (tipo não informado)',
})[surface]
const isApprovedSurface = (surface: DisplaySurface | null): surface is 'window' => surface === 'window'
const FRAME_REQUEST_TIMEOUT_MS = 15_000

/** Captura supervisionada para estudo em uma mesa própria ou explicitamente autorizada. */
export default function LiveCopilotScreen({ onClose, standalone = false }: {
  onClose: () => void
  standalone?: boolean
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const endedHandlerRef = useRef<(() => void) | null>(null)
  const uploadController = useRef<AbortController | null>(null)
  const contextGenerationRef = useRef(0)
  const consentRef = useRef(false)
  const remoteConsentRef = useRef(false)
  const remoteConsentSessionRef = useRef<string | null>(null)
  const remoteConsentExpiryTimerRef = useRef<number | null>(null)
  const inFlight = useRef(false)
  const startingRef = useRef(false)
  const mountedRef = useRef(true)
  const nextAllowedReadRef = useRef(0)
  const consecutiveErrorsRef = useRef(0)
  const lastVisionSuccessAtRef = useRef(0)
  const [capturing, setCapturing] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [starting, setStarting] = useState(false)
  const [consented, setConsented] = useState(false)
  const [remoteConsented, setRemoteConsented] = useState(false)
  const [everyMs, setEveryMs] = useState(1500)
  const [toCall, setToCall] = useState(0)
  const [stack, setStack] = useState(1000)
  const [effectiveStack, setEffectiveStack] = useState(1000)
  const [heroCurrentBet, setHeroCurrentBet] = useState(0)
  const [minRaiseIncrement, setMinRaiseIncrement] = useState(20)
  const [raiseReopened, setRaiseReopened] = useState(true)
  const [opponents, setOpponents] = useState(1)
  const [inPosition, setInPosition] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [vision, setVision] = useState<FromImageResult | null>(null)
  const [visionStale, setVisionStale] = useState(false)
  const [visionLatencyMs, setVisionLatencyMs] = useState<number | null>(null)
  const [frames, setFrames] = useState(0)
  const [captureSource, setCaptureSource] = useState<string | null>(null)
  const [displaySurface, setDisplaySurface] = useState<DisplaySurface | null>(null)
  const [captureLayout, setCaptureLayout] = useState<CaptureLayout>('second-monitor')
  const [stageStatus, setStageStatus] = useState('Etapa 1 de 4: escolha a configuração de monitores e autorize a captura local.')

  const invalidateLiveContext = useCallback(() => {
    contextGenerationRef.current += 1
    uploadController.current?.abort()
    uploadController.current = null
    inFlight.current = false
    nextAllowedReadRef.current = 0
    lastVisionSuccessAtRef.current = 0
    setVision(null)
    setVisionStale(false)
    setVisionLatencyMs(null)
  }, [])

  const stop = useCallback((updateState = true, preserveConsent = false) => {
    uploadController.current?.abort()
    uploadController.current = null
    inFlight.current = false
    nextAllowedReadRef.current = 0
    consecutiveErrorsRef.current = 0
    lastVisionSuccessAtRef.current = 0
    const stream = streamRef.current
    const track = stream?.getVideoTracks()[0]
    if (track && endedHandlerRef.current) track.removeEventListener('ended', endedHandlerRef.current)
    stream?.getTracks().forEach((item) => item.stop())
    streamRef.current = null
    endedHandlerRef.current = null
    if (remoteConsentExpiryTimerRef.current !== null) {
      window.clearTimeout(remoteConsentExpiryTimerRef.current)
      remoteConsentExpiryTimerRef.current = null
    }
    const remoteSession = remoteConsentSessionRef.current
    remoteConsentSessionRef.current = null
    if (remoteSession) void api.revokeRemoteVlmConsent(remoteSession).catch(() => undefined)
    if (videoRef.current) videoRef.current.srcObject = null
    startingRef.current = false
    if (!preserveConsent) {
      consentRef.current = false
      remoteConsentRef.current = false
    }
    if (updateState && mountedRef.current) {
      setStarting(false)
      setCapturing(false)
      setAnalyzing(false)
      setVision(null)
      setVisionStale(false)
      setVisionLatencyMs(null)
      setCaptureSource(null)
      setDisplaySurface(null)
      if (!preserveConsent) {
        setConsented(false)
        setRemoteConsented(false)
        setStageStatus('Etapa 1 de 4: autorize a captura local.')
      } else {
        setStageStatus('Etapa 2 de 4: selecione somente a janela autorizada.')
      }
    }
  }, [])

  const close = useCallback(() => { stop(); onClose() }, [onClose, stop])
  const workspaceRef = useDialogA11y(close, !standalone)
  useEffect(() => { if (standalone) workspaceRef.current?.focus() }, [standalone, workspaceRef])

  const selectSource = async () => {
    if (!consented || !consentRef.current || startingRef.current || streamRef.current) return
    startingRef.current = true
    setStarting(true)
    setError(null)
    setVision(null)
    setVisionStale(false)
    setVisionLatencyMs(null)
    setFrames(0)
    setStageStatus(`Etapa 2 de 4: no seletor, escolha a categoria Janela e a fonte ${layoutTarget(captureLayout)}.`)
    let acquiredStream: MediaStream | null = null
    try {
      if (!navigator.mediaDevices?.getDisplayMedia) throw new Error('Este navegador não oferece captura de tela.')
      const stream = await navigator.mediaDevices.getDisplayMedia(WINDOW_ONLY_CAPTURE_OPTIONS)
      acquiredStream = stream
      if (!mountedRef.current || !consentRef.current) {
        stream.getTracks().forEach((item) => item.stop())
        return
      }
      streamRef.current = stream
      const reported = stream.getVideoTracks()[0]?.getSettings?.().displaySurface
      const surface: DisplaySurface = reported === 'window' || reported === 'monitor' || reported === 'browser'
        ? reported : 'unknown'
      setDisplaySurface(surface)
      setCaptureSource(sourceLabel(surface))
      const ended = () => {
        stop(true, true)
        if (mountedRef.current) {
          setError('O compartilhamento foi encerrado pelo navegador. Selecione novamente a janela autorizada.')
          setStageStatus('Compartilhamento encerrado. Nenhum quadro está sendo analisado.')
        }
      }
      endedHandlerRef.current = ended
      stream.getVideoTracks()[0]?.addEventListener('ended', ended)
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      if (!mountedRef.current || !consentRef.current || streamRef.current !== stream) {
        stop(false)
        return
      }
      setCapturing(true)
      if (!isApprovedSurface(surface)) {
        setError('Fonte bloqueada por privacidade. Somente uma fonte confirmada pelo navegador como Janela pode ser analisada.')
        setStageStatus('Etapa 3 de 4: fonte não autorizada ou não verificável; escolha outra janela.')
      } else {
        setStageStatus(`Etapa 3 de 4: confirme na prévia se esta é a janela correta ${layoutTarget(captureLayout)}.`)
      }
    } catch (caught) {
      if (acquiredStream && streamRef.current !== acquiredStream) acquiredStream.getTracks().forEach((item) => item.stop())
      stop()
      if (!isAbort(caught) && mountedRef.current) setError(errorMessage(caught, 'Não foi possível selecionar a janela'))
    } finally {
      startingRef.current = false
      if (mountedRef.current) setStarting(false)
    }
  }

  const confirmAndAnalyze = async () => {
    if (!capturing || analyzing || !streamRef.current || !isApprovedSurface(displaySurface)) return
    setStarting(true)
    setError(null)
    try {
      if (remoteConsentRef.current) {
        const remoteSession = await api.createRemoteVlmConsent()
        if (!mountedRef.current || !consentRef.current || !remoteConsentRef.current || !streamRef.current) {
          void api.revokeRemoteVlmConsent(remoteSession.session_id).catch(() => undefined)
          return
        }
        remoteConsentSessionRef.current = remoteSession.session_id
        remoteConsentExpiryTimerRef.current = window.setTimeout(() => {
          if (remoteConsentSessionRef.current !== remoteSession.session_id) return
          remoteConsentSessionRef.current = null
          remoteConsentRef.current = false
          remoteConsentExpiryTimerRef.current = null
          void api.revokeRemoteVlmConsent(remoteSession.session_id).catch(() => undefined)
          if (mountedRef.current) {
            setRemoteConsented(false)
            setError('A autorização do VLM remoto expirou. A análise local continua ativa.')
          }
        }, remoteSession.expires_in_seconds * 1000)
      }
      if (!mountedRef.current || !streamRef.current) return
      setAnalyzing(true)
      setStageStatus('Etapa 4 de 4: análise ativa da janela confirmada.')
    } catch (caught) {
      if (mountedRef.current) setError(errorMessage(caught, 'Não foi possível iniciar a análise'))
    } finally {
      if (mountedRef.current) setStarting(false)
    }
  }

  useEffect(() => {
    if (!capturing || !analyzing) return
    const canvas = document.createElement('canvas')
    const id = window.setInterval(async () => {
      if (vision && isVisionExpired(lastVisionSuccessAtRef.current, performance.now(), everyMs)) {
        setVisionStale(true)
      }
      if (Date.now() < nextAllowedReadRef.current) return
      const video = videoRef.current
      if (!video || !video.videoWidth || !video.videoHeight || inFlight.current) return
      if (!consentRef.current) { stop(); return }
      const remoteSessionId = remoteConsentRef.current ? remoteConsentSessionRef.current : null
      if (remoteConsentRef.current && !remoteSessionId) return
      inFlight.current = true
      const contextGeneration = contextGenerationRef.current
      const size = fitWithin(video.videoWidth, video.videoHeight, 1280)
      canvas.width = size.width
      canvas.height = size.height
      const context = canvas.getContext('2d')
      if (!context) {
        inFlight.current = false
        setError('O navegador não disponibilizou o canvas 2D. A análise foi pausada.')
        setVisionStale(Boolean(vision))
        setAnalyzing(false)
        setStageStatus('Análise pausada por falha no canvas.')
        return
      }
      context.drawImage(video, 0, 0, size.width, size.height)
      let controller: AbortController | null = null
      let requestTimeout: number | null = null
      let requestTimedOut = false
      let startedAt: number | null = null
      try {
        const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.78))
        if (!blob) throw new Error('O navegador não conseguiu codificar o quadro capturado.')
        if (!streamRef.current || contextGeneration !== contextGenerationRef.current) return
        controller = new AbortController()
        uploadController.current = controller
        startedAt = performance.now()
        requestTimeout = window.setTimeout(() => {
          requestTimedOut = true
          controller?.abort()
        }, FRAME_REQUEST_TIMEOUT_MS)
        const result = await api.fromImage(new File([blob], 'frame.jpg', { type: 'image/jpeg' }), {
          to_call: toCall, my_stack: stack, num_opponents: opponents, in_position: inPosition,
          effective_stack: effectiveStack,
          hero_current_bet: heroCurrentBet,
          current_bet: heroCurrentBet + toCall,
          min_raise_increment: minRaiseIncrement,
          raise_reopened: raiseReopened,
          remoteVlmConsent: remoteSessionId ? { granted: true, sessionId: remoteSessionId } : undefined,
        }, controller.signal)
        if (
          !controller.signal.aborted
          && mountedRef.current
          && contextGeneration === contextGenerationRef.current
        ) {
          consecutiveErrorsRef.current = 0
          nextAllowedReadRef.current = 0
          setVision(result)
          setVisionStale(false)
          lastVisionSuccessAtRef.current = performance.now()
          setVisionLatencyMs(Math.max(0, performance.now() - startedAt))
          setFrames((count) => count + 1)
          setError(null)
        }
      } catch (caught) {
        if ((requestTimedOut || !isAbort(caught)) && mountedRef.current) {
          consecutiveErrorsRef.current += 1
          const backoffMs = Math.min(10000, everyMs * (2 ** Math.min(3, consecutiveErrorsRef.current)))
          nextAllowedReadRef.current = Date.now() + backoffMs
          setError(`${requestTimedOut ? 'Tempo limite ao ler o quadro.' : errorMessage(caught, 'Erro ao ler o quadro')} Nova tentativa em ${Math.ceil(backoffMs / 1000)}s.`)
          setVisionStale(Boolean(vision))
          setVisionLatencyMs(startedAt === null ? null : Math.max(0, performance.now() - startedAt))
        }
      } finally {
        if (requestTimeout !== null) window.clearTimeout(requestTimeout)
        if (!controller || uploadController.current === controller) {
          uploadController.current = null
          inFlight.current = false
        }
      }
    }, everyMs)
    return () => {
      window.clearInterval(id)
      contextGenerationRef.current += 1
      uploadController.current?.abort()
      uploadController.current = null
      inFlight.current = false
    }
  }, [
    analyzing, capturing, effectiveStack, everyMs, heroCurrentBet, inPosition,
    minRaiseIncrement, opponents, raiseReopened, stack, stop, toCall, vision,
  ])

  useEffect(() => {
    // StrictMode executa setup → cleanup → setup em desenvolvimento. Restaure o
    // marcador no segundo setup para a verificação não simular unmount permanente.
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      stop(false)
    }
  }, [stop])

  // Diagnóstico histórico pode permanecer visível, mas conselho de um quadro
  // anterior nunca continua acionável depois de erro/timeout em mesa mutável.
  const decision = actionableDecision(vision, visionStale)
  const blockedSource = !isApprovedSurface(displaySurface)
  return (
    <motion.div className={standalone ? 'capture-page' : 'guide-overlay'} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={standalone ? undefined : close}>
      <motion.div
        ref={workspaceRef}
        className={standalone ? 'capture-workspace cp-live' : 'guide-modal copilot-modal cp-live'}
        role={standalone ? 'main' : 'dialog'} aria-modal={standalone ? undefined : true}
        aria-labelledby="live-copilot-title" tabIndex={-1}
        initial={{ opacity: 0, y: 18, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: 'spring', stiffness: 260, damping: 26 }} onClick={(event) => event.stopPropagation()}
      >
        <header className="guide-head">
          <h1 id="live-copilot-title"><MonitorPlay size={20} /> Captura supervisionada <span className="guide-sub">somente mesa própria ou ambiente autorizado</span></h1>
          <button className={standalone ? 'btn btn-ghost' : 'ico-btn'} onClick={close} aria-label={standalone ? 'Voltar para a Arena' : 'Fechar'}><X size={18} /> {standalone && 'Voltar para a Arena'}</button>
        </header>
        <p className="guide-intro">O navegador envia quadros somente após sua confirmação para o backend <code>{API_BASE}</code>. O VLM remoto exige autorização separada. Não use assistência em partidas de terceiros ou onde RTA seja proibido.</p>
        <fieldset className="capture-layout" disabled={capturing || starting}>
          <legend>Onde está a janela que será capturada?</legend>
          <label className={captureLayout === 'second-monitor' ? 'is-selected' : ''}>
            <input type="radio" name="capture-layout" value="second-monitor" checked={captureLayout === 'second-monitor'} onChange={() => {
              setCaptureLayout('second-monitor')
              setStageStatus('Etapa 1 de 4: deixe o painel neste monitor, a janela autorizada visível no outro e confirme a autorização.')
            }} />
            <span><b>Outro monitor (recomendado)</b><small>Painel de captura em uma tela; janela da imagem na outra.</small></span>
          </label>
          <label className={captureLayout === 'same-monitor' ? 'is-selected' : ''}>
            <input type="radio" name="capture-layout" value="same-monitor" checked={captureLayout === 'same-monitor'} onChange={() => {
              setCaptureLayout('same-monitor')
              setStageStatus('Etapa 1 de 4: organize painel e janela autorizada lado a lado, sem minimizar a fonte, e confirme a autorização.')
            }} />
            <span><b>Mesmo monitor</b><small>Organize as duas janelas lado a lado e mantenha a fonte visível.</small></span>
          </label>
        </fieldset>
        <div className={`capture-monitor-map is-${captureLayout}`} role="note" aria-label="Orientação para a configuração de monitores selecionada">
          {captureLayout === 'second-monitor' ? <>
            <div><span>Monitor 1</span><b>Painel de captura</b><small>Este navegador permanece visível.</small></div>
            <strong aria-hidden="true">← janela ←</strong>
            <div><span>Monitor 2</span><b>Janela da imagem</b><small>Visível, restaurada e autorizada.</small></div>
          </> : <div className="capture-same-monitor"><span>Mesmo monitor</span><b>Painel lado a lado com a janela da imagem</b><small>Não sobreponha nem minimize a janela capturada.</small></div>}
          <p>Por privacidade, o navegador não revela o número físico do monitor. Esta opção orienta o fluxo; você confirma a janela efetiva no seletor e na prévia.</p>
        </div>
        {standalone && <ol className="capture-steps" aria-label="Como capturar a solução parceira"><li>Escolha <b>Mesmo monitor</b> ou <b>Outro monitor</b>.</li><li>Confirme a autorização e escolha somente <b>Janela</b>.</li><li>Confira a prévia e confirme a fonte correta.</li><li>Acompanhe percepção, confiança, latência e abstenções.</li></ol>}
        <div className="capture-stage-status" role="status" aria-atomic="true">{stageStatus}</div>

        <label className="cp-consent"><input type="checkbox" checked={consented} disabled={capturing} onChange={(event) => {
          const checked = event.currentTarget.checked
          consentRef.current = checked
          setConsented(checked)
          setStageStatus(checked
            ? `Etapa 2 de 4: selecione somente a janela autorizada ${layoutTarget(captureLayout)}.`
            : 'Etapa 1 de 4: escolha a configuração de monitores e autorize a captura local.')
          if (!checked) stop()
        }} /><span>Autorizo a captura da janela do projeto parceiro, no mesmo monitor ou em outro, e confirmo que seu responsável permitiu o envio dos quadros ao backend informado.</span></label>

        <details className="capture-advanced"><summary>Opções avançadas e contexto manual</summary>
          <label className="cp-consent"><input type="checkbox" checked={remoteConsented} disabled={!consented || capturing || starting} onChange={(event) => {
            const checked = event.currentTarget.checked
            remoteConsentRef.current = checked
            remoteConsentSessionRef.current = null
            setRemoteConsented(checked)
          }} /><span>Também autorizo, somente nesta sessão, o envio de versão redigida ao VLM remoto de terceiro. Retenção efetiva depende do provedor e do túnel.</span></label>
          <div className="cp-live-controls">
            <label className="cp-field"><span>Ler a cada</span><select disabled={analyzing} value={everyMs} onChange={(event) => { invalidateLiveContext(); setEveryMs(Number(event.currentTarget.value)) }}><option value={1000}>1s</option><option value={1500}>1,5s</option><option value={2500}>2,5s</option><option value={4000}>4s</option></select></label>
            <label className="cp-field"><span>A pagar</span><input disabled={analyzing} type="number" min={0} value={toCall} onChange={(event) => { invalidateLiveContext(); setToCall(safeNumber(event.currentTarget.valueAsNumber, toCall, 0)) }} /></label>
            <label className="cp-field"><span>Seu stack</span><input disabled={analyzing} type="number" min={1} value={stack} onChange={(event) => { invalidateLiveContext(); setStack(safeNumber(event.currentTarget.valueAsNumber, stack, 1)) }} /></label>
            <label className="cp-field"><span>Stack efetivo rival</span><input disabled={analyzing} type="number" min={0} value={effectiveStack} onChange={(event) => { invalidateLiveContext(); setEffectiveStack(safeNumber(event.currentTarget.valueAsNumber, effectiveStack, 0)) }} /></label>
            <label className="cp-field"><span>Sua aposta nesta rua</span><input disabled={analyzing} type="number" min={0} value={heroCurrentBet} onChange={(event) => { invalidateLiveContext(); setHeroCurrentBet(safeNumber(event.currentTarget.valueAsNumber, heroCurrentBet, 0)) }} /></label>
            <label className="cp-field"><span>Aposta-alvo atual</span><input disabled type="number" value={heroCurrentBet + toCall} aria-readonly="true" /></label>
            <label className="cp-field"><span>Último aumento completo</span><input disabled={analyzing} type="number" min={1} value={minRaiseIncrement} onChange={(event) => { invalidateLiveContext(); setMinRaiseIncrement(safeNumber(event.currentTarget.valueAsNumber, minRaiseIncrement, 1)) }} /></label>
            <label className="cp-field cp-check"><input disabled={analyzing} type="checkbox" checked={raiseReopened} onChange={(event) => { invalidateLiveContext(); setRaiseReopened(event.currentTarget.checked) }} /><span>Ação reaberta</span></label>
            <label className="cp-field"><span>Oponentes</span><input disabled={analyzing} type="number" min={1} max={8} value={opponents} onChange={(event) => { invalidateLiveContext(); setOpponents(Math.min(8, safeNumber(event.currentTarget.valueAsNumber, opponents, 1))) }} /></label>
            <label className="cp-field"><span>Posição</span><select disabled={analyzing} value={inPosition ? 'in' : 'out'} onChange={(event) => { invalidateLiveContext(); setInPosition(event.currentTarget.value === 'in') }}><option value="out">Fora de posição</option><option value="in">Em posição</option></select></label>
          </div>
        </details>

        <div className="cp-live-controls capture-actions">
          {!capturing && <button className="btn btn-accent" onClick={() => void selectSource()} disabled={!consented || starting}><MonitorPlay size={16} /> {starting ? 'Aguardando escolha da janela…' : standalone ? `Selecionar janela ${layoutTarget(captureLayout)}` : 'Selecionar janela do jogo'}</button>}
          {capturing && !analyzing && <><button className="btn btn-accent" onClick={() => void confirmAndAnalyze()} disabled={starting || blockedSource}><Play size={16} /> {starting ? 'Iniciando análise…' : 'Confirmar e iniciar análise'}</button><button className="btn btn-ghost" onClick={() => stop(true, true)}><Square size={16} /> Escolher outra janela</button></>}
          {capturing && analyzing && <button className="btn btn-ghost" onClick={() => stop(true, true)}><Square size={16} /> Encerrar compartilhamento</button>}
          {captureSource && <span className="capture-source">{captureSource}</span>}
          {analyzing && <span className="cp-live-dot" aria-label={`Análise ativa, ${frames} quadros concluídos`}>● análise ativa · {frames} quadros</span>}
        </div>

        {capturing && !analyzing && !blockedSource && <div className="capture-confirm" role="note"><b>Esta é a janela correta {layoutTarget(captureLayout)}?</b> Nenhum quadro será enviado antes de confirmar.</div>}
        {error && <div className="cp-error" role="alert">⚠️ {error}{visionLatencyMs !== null && <> · última tentativa: {Math.round(visionLatencyMs)} ms</>}</div>}
        <div className="cp-live-grid">
          <div className="cp-live-preview"><video ref={videoRef} muted playsInline className="cp-live-video" aria-label="Prévia da janela compartilhada" />{!capturing && <div className="cp-live-hint">A prévia da janela autorizada aparecerá aqui.</div>}</div>
          <div className="cp-live-read">
            {visionStale && <div className="capture-stale" role="note">Última leitura válida — diagnóstico histórico; recomendação suprimida até um novo quadro válido.</div>}
            {vision && <VisionDiagnostics result={vision} latencyMs={visionLatencyMs} />}
            {standalone && <div className="capture-academic-note">Modo apresentação: estratégia não é exibida durante a captura ao vivo.</div>}
            {!standalone && decision && <><div className="cp-headline"><Lightbulb size={18} /> {decision.headline}</div><div className="cp-grid"><div><span>Recomendação</span><b>{decision.recommendation_label}</b></div><div><span>Equity estimada</span><b className="mono">{decision.equity_pct}%</b></div><div><span>Pot odds</span><b className="mono">{decision.pot_odds_pct}%</b></div><div title="Assume checkdown, sem apostas futuras."><span>EV simplificado (checkdown)</span><b className="mono">{Math.round(decision.ev_call)}</b></div></div><div className="capture-stale" role="note">{decision.decision_note}</div><div className="cp-options">{decision.options.map((option) => <div key={option.action} className={`cp-opt v-${option.verdict}${option.chosen ? ' is-chosen' : ''}`}><b>{option.label}</b> <small>{option.reason}</small></div>)}</div></>}
            {!vision && analyzing && <div className="cp-live-hint">Lendo o primeiro quadro…</div>}
            {!vision && !analyzing && <div className="cp-live-hint">A análise começa somente depois da confirmação.</div>}
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}

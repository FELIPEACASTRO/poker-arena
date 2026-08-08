import { lazy, Suspense, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ClipboardList, Compass, Cpu, FlaskConical, Gamepad2, GraduationCap, LogOut, MonitorPlay, Sparkles, Users } from 'lucide-react'
import ActionBar from './components/ActionBar'
import AIMind from './components/AIMind'
import { CouncilPanel, EquityPanel, EVPanel, HandPanel, ProfilePanel } from './components/Analysis'
import LabHint from './components/LabHint'
import PokerTable from './components/PokerTable'
import ReasoningCard from './components/ReasoningCard'
import SetupScreen from './components/SetupScreen'
import {
  ChipRacePanel,
  LeaderboardPanel,
  SessionStatsPanel,
  StylePanel,
} from './components/WatchPanels'
import WinStats from './components/WinStats'
import { setApiToken as configureApiToken } from './api'
import { useGame } from './store'

const AuditPage = lazy(() => import('./components/AuditPage'))
const CopilotScreen = lazy(() => import('./components/CopilotScreen'))
const LiveCopilotScreen = lazy(() => import('./components/LiveCopilotScreen'))
const GuideScreen = lazy(() => import('./components/GuideScreen'))
const ManageTable = lazy(() => import('./components/ManageTable'))
const PositionsGuide = lazy(() => import('./components/PositionsGuide'))

export default function App() {
  const { state, watch, paused, busy, error, stepDelay, create, act, next, step, togglePause, leave } =
    useGame()
  const [guideOpen, setGuideOpen] = useState(false)
  const [auditOpen, setAuditOpen] = useState(false)
  const [manageOpen, setManageOpen] = useState(false)
  const initialView = new URLSearchParams(window.location.search).get('view')
  const [copilotOpen, setCopilotOpen] = useState(initialView === 'copilot')
  const [liveOpen, setLiveOpen] = useState(initialView === 'capture')
  const [apiToken, setApiToken] = useState('')
  const [positions, setPositions] = useState<false | string>(false)
  const modalOpen =
    guideOpen || auditOpen || manageOpen || copilotOpen || liveOpen || positions !== false

  useEffect(() => () => configureApiToken(null), [])

  // modo laboratório: avança sozinho no ritmo escolhido (dá pra acompanhar e pensar)
  // pausa enquanto um modal está aberto (senão o re-render atrapalha digitar/interagir)
  useEffect(() => {
    if (!state || !watch || paused || error || modalOpen) return
    let t = 0
    if (state.phase === 'bot_turn') {
      t = window.setTimeout(() => void step().catch(() => undefined), stepDelay)
    } else if (state.phase === 'hand_over') {
      t = window.setTimeout(() => void next().catch(() => undefined), stepDelay + 1600)
    }
    return () => clearTimeout(t)
  }, [state, watch, paused, error, modalOpen, step, next, stepDelay])

  const closeStandaloneCapture = () => {
    setLiveOpen(false)
    const url = new URL(window.location.href)
    url.searchParams.delete('view')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }

  if (initialView === 'capture' && liveOpen) {
    return (
      <Suspense fallback={<main className="modal-loading" role="status">Carregando captura…</main>}>
        <LiveCopilotScreen standalone onClose={closeStandaloneCapture} />
      </Suspense>
    )
  }

  const read = state?.opponent_read

  return (
    <>
    <AnimatePresence mode="wait">
      {!state ? (
        <motion.div
          key="setup"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.28 }}
        >
          <SetupScreen
            apiToken={apiToken}
            busy={busy}
            error={error}
            onApiTokenChange={(value) => {
              configureApiToken(value)
              setApiToken(value)
            }}
            onCreate={(config) => void create(config).catch(() => undefined)}
          />
        </motion.div>
      ) : (
        <motion.div
          key="game"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.34, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="lab-shell">
            <header className="lab-header">
              <div className="lab-brand">
                <span className="ico">
                  <Cpu size={20} />
                </span>
                Poker Arena
                <span className="lab-tag">LAB</span>
              </div>
              <div className="lab-header-spacer" />
              <nav className="lab-header-right" aria-label="Ferramentas da mesa">
                <span className="chip mono">mão #{state.hand_number}</span>
                <span className="chip">
                  {watch ? <FlaskConical size={14} /> : <Gamepad2 size={14} />}
                  <span className="chip-mode-label">
                    {watch ? 'Modo laboratório' : 'Você joga'}
                  </span>
                </span>
                <button
                  className="btn btn-ghost guide-open"
                  onClick={() => setManageOpen(true)}
                  title="Gerenciar mesa (entrar/sair de jogadores)"
                  aria-label="Gerenciar mesa"
                >
                  <Users size={16} />
                  <span className="guide-open-label">Mesa</span>
                </button>
                <button
                  className="btn btn-ghost guide-open"
                  onClick={() => setAuditOpen(true)}
                  title="Auditoria de partidas"
                  aria-label="Auditoria de partidas"
                >
                  <ClipboardList size={16} />
                  <span className="guide-open-label">Auditoria</span>
                </button>
                <button
                  className="btn btn-ghost guide-open"
                  onClick={() => setPositions('')}
                  title="Regras de cada posição da mesa"
                  aria-label="Guia de posições"
                >
                  <Compass size={16} />
                  <span className="guide-open-label">Posições</span>
                </button>
                <button
                  className="btn btn-ghost guide-open"
                  onClick={() => setCopilotOpen(true)}
                  title="Copiloto: analisar um spot e revisar PHH no backend configurado"
                  aria-label="Abrir copiloto de estudo"
                >
                  <Sparkles size={16} />
                  <span className="guide-open-label">Copiloto</span>
                </button>
                <button
                  className="btn btn-ghost guide-open"
                  onClick={() => setLiveOpen(true)}
                  title="Captura supervisionada para mesa própria ou autorizada"
                  aria-label="Abrir captura supervisionada"
                >
                  <MonitorPlay size={16} />
                  <span className="guide-open-label">Captura</span>
                </button>
                <button
                  className="btn btn-ghost guide-open"
                  onClick={() => setGuideOpen(true)}
                  title="Guia dos cérebros"
                  aria-label="Guia dos cérebros"
                >
                  <GraduationCap size={16} />
                  <span className="guide-open-label">Cérebros</span>
                </button>
                <button className="ico-btn" onClick={leave} aria-label="Sair da mesa">
                  <LogOut size={16} />
                </button>
              </nav>
            </header>

            <main className="lab-main">
              <LabHint />
              <div className="lab-grid">
                <aside className="lab-col">
                  {watch ? (
                    <>
                      <LeaderboardPanel />
                      <StylePanel />
                    </>
                  ) : (
                    <>
                      <EquityPanel />
                      <HandPanel />
                      <WinStats />
                    </>
                  )}
                </aside>
                <section className="lab-stage">
                  <PokerTable state={state} onPositionClick={(p) => setPositions(p)} />
                </section>
                <aside className="lab-col">
                  {watch ? (
                    <>
                      <ReasoningCard />
                      <SessionStatsPanel />
                      <ChipRacePanel />
                    </>
                  ) : (
                    <>
                      <CouncilPanel />
                      <EVPanel />
                      <AIMind />
                      <ProfilePanel />
                    </>
                  )}
                  <AnimatePresence>
                    {read?.tilt && read.samples >= 30 && (
                      <motion.div
                        className="brain-banner tilt-banner"
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                      >
                        🔥 <b>Alerta heurístico de possível tilt.</b> Sua agressão subiu{' '}
                        <b>{Math.round((read.tilt_delta ?? 0) * 100)} pontos</b> logo após uma
                        perda grande. Isto não é diagnóstico; pause e reavalie o plano.
                      </motion.div>
                    )}
                    {read && read.samples >= 30 && (
                      <motion.div
                        className="brain-banner"
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                      >
                        🧠 <b>Estimativa inicial de estilo</b> ({read.samples} jogadas): você desiste{' '}
                        <b>{Math.round(read.fold_to_bet * 100)}%</b> das vezes diante de apostas
                        {read.fold_to_bet > 0.55
                          ? ' → vou te pressionar e blefar mais.'
                          : read.fold_to_bet < 0.45
                            ? ' → você paga muito, então aposto só com mão forte.'
                            : ' → jogo equilibrado, por enquanto.'}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </aside>
              </div>
              <ActionBar
                state={state}
                busy={busy}
                error={error}
                watch={watch}
                paused={paused}
                onTogglePause={togglePause}
                onAction={(type, amount) => void act(type, amount).catch(() => undefined)}
                onNext={() => void next().catch(() => undefined)}
                onLeave={leave}
              />
            </main>
          </div>

          <Suspense fallback={<div className="modal-loading" role="status">Carregando tela…</div>}>
            <AnimatePresence>
              {guideOpen && <GuideScreen onClose={() => setGuideOpen(false)} />}
              {auditOpen && <AuditPage onClose={() => setAuditOpen(false)} />}
              {manageOpen && <ManageTable onClose={() => setManageOpen(false)} />}
              {copilotOpen && <CopilotScreen onClose={() => setCopilotOpen(false)} />}
              {liveOpen && <LiveCopilotScreen onClose={() => setLiveOpen(false)} />}
              {positions !== false && (
                <PositionsGuide focus={positions || undefined} onClose={() => setPositions(false)} />
              )}
            </AnimatePresence>
          </Suspense>
        </motion.div>
      )}
    </AnimatePresence>
      {!state && copilotOpen && (
        <Suspense fallback={<div className="modal-loading" role="status">Carregando tela…</div>}>
          <AnimatePresence>
            <CopilotScreen onClose={() => setCopilotOpen(false)} />
          </AnimatePresence>
        </Suspense>
      )}
    </>
  )
}

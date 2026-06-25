import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ClipboardList, Cpu, FlaskConical, Gamepad2, GraduationCap, LogOut, Users } from 'lucide-react'
import ActionBar from './components/ActionBar'
import AIMind from './components/AIMind'
import { CouncilPanel, EquityPanel, EVPanel, HandPanel, ProfilePanel } from './components/Analysis'
import AuditPage from './components/AuditPage'
import GuideScreen from './components/GuideScreen'
import ManageTable from './components/ManageTable'
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
import { useGame } from './store'

export default function App() {
  const { state, watch, paused, busy, error, stepDelay, create, act, next, step, togglePause, leave } =
    useGame()
  const [guideOpen, setGuideOpen] = useState(false)
  const [auditOpen, setAuditOpen] = useState(false)
  const [manageOpen, setManageOpen] = useState(false)
  const modalOpen = guideOpen || auditOpen || manageOpen

  // modo laboratório: avança sozinho no ritmo escolhido (dá pra acompanhar e pensar)
  // pausa enquanto um modal está aberto (senão o re-render atrapalha digitar/interagir)
  useEffect(() => {
    if (!state || !watch || paused || error || modalOpen) return
    let t = 0
    if (state.phase === 'bot_turn') t = window.setTimeout(() => step(), stepDelay)
    else if (state.phase === 'hand_over') t = window.setTimeout(() => next(), stepDelay + 1600)
    return () => clearTimeout(t)
  }, [state, watch, paused, error, modalOpen, step, next, stepDelay])

  const read = state?.opponent_read

  return (
    <AnimatePresence mode="wait">
      {!state ? (
        <motion.div
          key="setup"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.28 }}
        >
          <SetupScreen busy={busy} error={error} onCreate={create} />
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
              <div className="lab-header-right">
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
                >
                  <Users size={16} />
                  <span className="guide-open-label">Mesa</span>
                </button>
                <button
                  className="btn btn-ghost guide-open"
                  onClick={() => setAuditOpen(true)}
                  title="Auditoria de partidas"
                >
                  <ClipboardList size={16} />
                  <span className="guide-open-label">Auditoria</span>
                </button>
                <button
                  className="btn btn-ghost guide-open"
                  onClick={() => setGuideOpen(true)}
                  title="Guia dos cérebros"
                >
                  <GraduationCap size={16} />
                  <span className="guide-open-label">Cérebros</span>
                </button>
                <button className="ico-btn" onClick={leave} aria-label="Sair da mesa">
                  <LogOut size={16} />
                </button>
              </div>
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
                  <PokerTable state={state} />
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
                    {read && read.samples >= 8 && (
                      <motion.div
                        className="brain-banner"
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                      >
                        🧠 <b>Aprendi seu estilo</b> ({read.samples} jogadas): você desiste{' '}
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
                onAction={act}
                onNext={next}
                onLeave={leave}
              />
            </main>
          </div>

          <AnimatePresence>
            {guideOpen && <GuideScreen onClose={() => setGuideOpen(false)} />}
            {auditOpen && <AuditPage onClose={() => setAuditOpen(false)} />}
            {manageOpen && <ManageTable onClose={() => setManageOpen(false)} />}
          </AnimatePresence>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

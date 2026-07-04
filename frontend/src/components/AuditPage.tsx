import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { ChevronDown, ChevronLeft, ClipboardList, Trophy, X } from 'lucide-react'
import { api } from '../api'
import { colorMap } from '../colors'
import { levelColor } from '../levels'
import type { GameLog, GameSummary, LogHand } from '../types'

const ACT: Record<string, string> = {
  fold: 'desistiu',
  check: 'passou',
  call: 'pagou',
  raise: 'aumentou p/',
  all_in: 'foi all-in',
}
const STREET: Record<string, string> = { preflop: 'Pré-flop', flop: 'Flop', turn: 'Turn', river: 'River' }
const SUIT: Record<string, string> = { s: '♠', h: '♥', d: '♦', c: '♣' }

function Cards({ codes }: { codes: string[] }) {
  if (!codes || codes.length === 0) return <span className="audit-nocard">—</span>
  return (
    <span className="audit-cards">
      {codes.map((c, i) => {
        const rank = c.slice(0, -1).replace('T', '10')
        const suit = c.slice(-1)
        const red = suit === 'h' || suit === 'd'
        return (
          <span key={i} className="audit-card" style={{ color: red ? '#e0697a' : 'var(--text)' }}>
            {rank}
            {SUIT[suit] ?? suit}
          </span>
        )
      })}
    </span>
  )
}

function HandCard({
  h,
  colors,
  open,
  onToggle,
}: {
  h: LogHand
  colors: Record<string, string>
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="audit-hand">
      <button className="audit-hand-h" onClick={onToggle}>
        <span className="audit-hand-n">Mão #{h.hand}</span>
        <Cards codes={h.board} />
        <span className="audit-hand-pot">pote {h.pot.toLocaleString('pt-BR')}</span>
        <span className="audit-hand-win">
          <Trophy size={12} /> {h.winners.map((w) => w.name).join(', ') || '—'}
        </span>
        <ChevronDown size={16} className={'audit-chev' + (open ? ' is-open' : '')} />
      </button>
      {open && (
        <div className="audit-hand-body">
          {(['preflop', 'flop', 'turn', 'river'] as const).map((st) => {
            const acts = h.actions.filter((a) => a.street === st)
            if (acts.length === 0) return null
            return (
              <div key={st} className="audit-street">
                <div className="audit-street-h">
                  {STREET[st]} <Cards codes={acts[0].board} />
                </div>
                {acts.map((a, i) => (
                  <div key={i} className="audit-act">
                    <span
                      className="audit-dot"
                      style={{ background: colors[a.name] ?? levelColor(a.level) }}
                    />
                    <span className="audit-who">{a.name}</span>
                    <span className="audit-what">
                      {ACT[a.action] ?? a.action}
                      {a.amount ? ` ${a.amount}` : ''}
                    </span>
                    {a.insight && <span className="audit-why">💭 {a.insight.label}</span>}
                  </div>
                ))}
              </div>
            )
          })}
          <div className="audit-result">
            <div className="audit-deltas">
              {h.result.map((r) => (
                <span key={r.seat} className={'audit-delta ' + (r.delta >= 0 ? 'pos' : 'neg')}>
                  {r.name} {r.delta >= 0 ? '+' : ''}
                  {r.delta}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function AuditPage({ onClose }: { onClose: () => void }) {
  const [games, setGames] = useState<GameSummary[] | null>(null)
  const [game, setGame] = useState<GameLog | null>(null)
  const [openHand, setOpenHand] = useState<number | null>(null)

  // cor por competidor calculada a partir dos nomes do próprio jogo (histórico)
  const colors = useMemo(
    () => colorMap(game ? game.hands.flatMap((h) => h.seats.map((s) => s.name)) : []),
    [game],
  )

  useEffect(() => {
    api
      .listGames()
      .then((r) => setGames(r.games))
      .catch(() => setGames([]))
    const h = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (game) setGame(null)
      else onClose()
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [game, onClose])

  return (
    <motion.div className="guide-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
      <motion.div
        className="guide-modal audit-modal"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="guide-head">
          <h1>
            {game ? (
              <button className="audit-back" onClick={() => setGame(null)}>
                <ChevronLeft size={18} />
              </button>
            ) : (
              <ClipboardList size={20} />
            )}
            Auditoria de partidas
            <span className="guide-sub">{game ? game.meta.id as string : 'histórico'}</span>
          </h1>
          <button className="ico-btn" onClick={onClose} aria-label="Fechar">
            <X size={18} />
          </button>
        </header>

        {!game ? (
          games === null ? (
            <p className="audit-info">carregando…</p>
          ) : games.length === 0 ? (
            <p className="audit-info">nenhuma partida gravada ainda — jogue uma mão e ela aparece aqui.</p>
          ) : (
            <div className="audit-games">
              {games.map((g) => (
                <button
                  key={g.id}
                  className="audit-game"
                  onClick={() => {
                    setOpenHand(null)
                    api.getGame(g.id).then(setGame).catch(() => {})
                  }}
                >
                  <span className="audit-game-mode">
                    {g.mode === 'pluribus'
                      ? '🏆 Pluribus — a IA que venceu campeões (Science, 2019)'
                      : g.mode === 'watch'
                        ? '🔬 Modo Laboratório'
                        : '🎮 Você joga'}
                  </span>
                  <span className="audit-game-hands">{g.hands} mãos</span>
                  <span className="audit-game-date">
                    {g.created ? new Date(g.created).toLocaleString('pt-BR') : g.id}
                  </span>
                </button>
              ))}
            </div>
          )
        ) : (
          <div className="audit-hands">
            {game.hands.length === 0 ? (
              <p className="audit-info">esta partida ainda não tem mãos concluídas.</p>
            ) : (
              game.hands.map((h) => (
                <HandCard
                  key={h.hand + '-' + h.ts}
                  h={h}
                  colors={colors}
                  open={openHand === h.hand}
                  onToggle={() => setOpenHand(openHand === h.hand ? null : h.hand)}
                />
              ))
            )}
          </div>
        )}
      </motion.div>
    </motion.div>
  )
}

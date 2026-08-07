import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { ChevronDown, ChevronLeft, ClipboardList, Trophy, X } from 'lucide-react'
import { api } from '../api'
import { colorMap } from '../colors'
import { levelColor } from '../levels'
import type { GameLog, GameSummary, LogHand, PageInfo } from '../types'
import { useDialogA11y } from '../useDialogA11y'

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
      <button className="audit-hand-h" onClick={onToggle} aria-expanded={open}>
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
                <span key={r.player_id ?? r.seat} className={'audit-delta ' + (r.delta >= 0 ? 'pos' : 'neg')}>
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
  const [gamesPage, setGamesPage] = useState<PageInfo | null>(null)
  const [unreadableLogs, setUnreadableLogs] = useState(0)
  const [game, setGame] = useState<GameLog | null>(null)
  const [openHand, setOpenHand] = useState<number | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [gameError, setGameError] = useState<string | null>(null)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingGame, setLoadingGame] = useState(false)
  const listController = useRef<AbortController | null>(null)
  const gameRequest = useRef(0)
  const gameController = useRef<AbortController | null>(null)
  const backToList = useCallback(() => {
    gameRequest.current += 1
    gameController.current?.abort()
    gameController.current = null
    setGame(null)
    setGameError(null)
    setLoadingGame(false)
  }, [])
  const closeOrBack = useCallback(() => {
    if (game) backToList()
    else onClose()
  }, [backToList, game, onClose])
  const dialogRef = useDialogA11y(closeOrBack)

  // cor por competidor calculada a partir dos nomes do próprio jogo (histórico)
  const colors = useMemo(
    () => colorMap(game ? game.hands.flatMap((h) => h.seats.map((s) => s.name)) : []),
    [game],
  )

  useEffect(() => {
    const controller = new AbortController()
    listController.current = controller
    api
      .listGames({ offset: 0, limit: 50, signal: controller.signal })
      .then((response) => {
        setGames(response.games)
        setGamesPage(response.page)
        setUnreadableLogs(response.unreadable_logs)
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setListError(caught instanceof Error ? caught.message : String(caught))
      })
      .finally(() => setLoadingList(false))
    return () => {
      controller.abort()
      gameController.current?.abort()
    }
  }, [])

  const loadMoreGames = () => {
    const currentPage = gamesPage
    const offset = currentPage?.next_offset
    if (offset == null || !currentPage || loadingList) return
    listController.current?.abort()
    const controller = new AbortController()
    listController.current = controller
    setListError(null)
    setLoadingList(true)
    void api.listGames({ offset, limit: currentPage.limit, signal: controller.signal })
      .then((response) => {
        setGames((current) => [...(current ?? []), ...response.games])
        setGamesPage(response.page)
        setUnreadableLogs(response.unreadable_logs)
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setListError(caught instanceof Error ? caught.message : String(caught))
      })
      .finally(() => setLoadingList(false))
  }

  const loadGame = (id: string) => {
    const request = ++gameRequest.current
    gameController.current?.abort()
    const controller = new AbortController()
    gameController.current = controller
    setOpenHand(null)
    setGameError(null)
    setLoadingGame(true)
    void api.getGame(id, { offset: 0, limit: 100, signal: controller.signal }).then((next) => {
      if (request === gameRequest.current) setGame(next)
    }).catch((caught: unknown) => {
      if (request !== gameRequest.current) return
      if (caught instanceof DOMException && caught.name === 'AbortError') return
      setGameError(caught instanceof Error ? caught.message : String(caught))
    }).finally(() => {
      if (request === gameRequest.current) setLoadingGame(false)
    })
  }

  const loadMoreHands = () => {
    const currentGame = game
    const offset = currentGame?.page.next_offset
    const id = currentGame?.meta.id
    if (offset == null || !currentGame || typeof id !== 'string' || loadingGame) return
    const request = ++gameRequest.current
    gameController.current?.abort()
    const controller = new AbortController()
    gameController.current = controller
    setGameError(null)
    setLoadingGame(true)
    void api.getGame(id, { offset, limit: currentGame.page.limit, signal: controller.signal })
      .then((next) => {
        if (request !== gameRequest.current) return
        setGame((current) => current ? {
          meta: next.meta,
          hands: [...current.hands, ...next.hands],
          page: next.page,
        } : next)
      })
      .catch((caught: unknown) => {
        if (request !== gameRequest.current) return
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setGameError(caught instanceof Error ? caught.message : String(caught))
      })
      .finally(() => {
        if (request === gameRequest.current) setLoadingGame(false)
      })
  }

  return (
    <motion.div className="guide-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
      <motion.div
        ref={dialogRef}
        className="guide-modal audit-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="audit-title"
        tabIndex={-1}
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="guide-head">
          <h1 id="audit-title">
            {game ? (
              <button className="audit-back" onClick={backToList} aria-label="Voltar à lista de partidas">
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
          listError && games === null ? (
            <p className="audit-info" role="alert">Falha ao carregar o histórico: {listError}</p>
          ) : games === null ? (
            <p className="audit-info">carregando…</p>
          ) : gameError ? (
            <p className="audit-info" role="alert">Falha ao abrir a partida: {gameError}</p>
          ) : loadingGame ? (
            <p className="audit-info" role="status">carregando partida…</p>
          ) : games.length === 0 ? (
            <p className="audit-info">nenhuma partida gravada ainda — jogue uma mão e ela aparece aqui.</p>
          ) : (
            <div className="audit-games">
              {unreadableLogs > 0 && (
                <p className="audit-info" role="alert">
                  Trilha incompleta: {unreadableLogs} log(s) corrompido(s) ou inacessível(is)
                  foram isolados.
                </p>
              )}
              {listError && <p className="audit-info" role="alert">Falha ao carregar mais partidas: {listError}</p>}
              {games.map((g) => (
                <button
                  key={g.id}
                  className="audit-game"
                  onClick={() => loadGame(g.id)}
                >
                  <span className="audit-game-mode">
                    {g.mode === 'pluribus'
                      ? '🧪 Perfil Pluribus (rótulo registrado no log)'
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
              {gamesPage?.next_offset != null && (
                <button className="btn btn-ghost audit-more" onClick={loadMoreGames} disabled={loadingList}>
                  {loadingList ? 'Carregando…' : `Carregar mais partidas (${games.length}/${gamesPage.total})`}
                </button>
              )}
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
            {gameError && (
              <p className="audit-info" role="alert">Falha ao carregar mais mãos: {gameError}</p>
            )}
            {game.page.next_offset != null && (
              <button className="btn btn-ghost audit-more" onClick={loadMoreHands} disabled={loadingGame}>
                {loadingGame ? 'Carregando…' : `Carregar mais mãos (${game.hands.length}/${game.page.total})`}
              </button>
            )}
          </div>
        )}
      </motion.div>
    </motion.div>
  )
}

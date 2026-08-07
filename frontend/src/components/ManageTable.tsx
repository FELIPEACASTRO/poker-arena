import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Info, UserPlus, Users, X } from 'lucide-react'
import { api } from '../api'
import { levelColor, levelName } from '../levels'
import { useGame } from '../store'
import { useDialogA11y } from '../useDialogA11y'

export default function ManageTable({ onClose }: { onClose: () => void }) {
  const { state, addPlayer, removePlayer, busy, error, colors } = useGame()
  const roster = state?.roster ?? []
  const [levels, setLevels] = useState<string[]>([])
  const [level, setLevel] = useState('montecarlo')
  const [name, setName] = useState('')
  const [levelsError, setLevelsError] = useState<string | null>(null)
  const dialogRef = useDialogA11y(onClose)

  useEffect(() => {
    const controller = new AbortController()
    api
      .getLevels(controller.signal)
      .then((r) => {
        setLevels(r.levels)
        setLevel((cur) => (r.levels.includes(cur) ? cur : (r.levels[0] ?? cur)))
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setLevelsError(caught instanceof Error ? caught.message : String(caught))
      })
    return () => controller.abort()
  }, [])

  const full = roster.length >= 9
  const canRemove = roster.length > 2

  return (
    <motion.div className="guide-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
      <motion.div
        ref={dialogRef}
        className="guide-modal manage-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="manage-title"
        tabIndex={-1}
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="guide-head">
          <h1 id="manage-title">
            <Users size={20} />
            Gerenciar mesa
            <span className="guide-sub">{roster.length}/9 lugares</span>
          </h1>
          <button className="ico-btn" onClick={onClose} aria-label="Fechar">
            <X size={18} />
          </button>
        </header>

        <p className="manage-note">
          <Info size={13} /> As mudanças valem a partir da <b>próxima mão</b> (a mão atual termina normalmente).
        </p>

        <div className="manage-list">
          {roster.map((r) => (
            <div key={r.seat} className="manage-row">
              <span
                className="manage-dot"
                style={{ background: colors[r.name] ?? levelColor(r.level) }}
              />
              <span className="manage-name">
                {r.name}
                {r.is_human && <span className="manage-youtag">você</span>}
              </span>
              <span className="manage-lvl">{levelName(r.level)}</span>
              <span className="manage-stack">{r.stack.toLocaleString('pt-BR')}</span>
              <button
                className="manage-remove"
                disabled={r.is_human || !canRemove || busy}
                title={
                  r.is_human
                    ? 'você não pode se remover'
                    : !canRemove
                      ? 'a mesa precisa de pelo menos 2 jogadores'
                      : 'remover da mesa'
                }
                aria-label={`Remover ${r.name}`}
                onClick={() => void removePlayer(r.seat).catch(() => undefined)}
              >
                <X size={15} />
              </button>
            </div>
          ))}
        </div>

        <div className="manage-add">
          <input
            className="manage-input"
            placeholder="nome (opcional)"
            aria-label="Nome do novo jogador"
            value={name}
            maxLength={16}
            onChange={(e) => setName(e.target.value)}
            disabled={full}
          />
          <select
            className="manage-select"
            aria-label="Nível do novo jogador"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            disabled={full}
          >
            {levels.map((l) => (
              <option key={l} value={l}>
                {levelName(l)}
              </option>
            ))}
          </select>
          <button
            className="btn btn-primary manage-addbtn"
            disabled={full || busy}
            onClick={() => {
              void addPlayer({ level, name: name.trim() || undefined }).catch(() => undefined)
              setName('')
            }}
          >
            <UserPlus size={15} /> Adicionar
          </button>
        </div>

        {full && <p className="manage-hint">A mesa está cheia (9 lugares). Remova alguém para adicionar.</p>}
        {(error || levelsError) && <p className="manage-err" role="alert">{error ?? levelsError}</p>}
      </motion.div>
    </motion.div>
  )
}

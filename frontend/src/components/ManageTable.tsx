import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Info, UserPlus, Users, X } from 'lucide-react'
import { api } from '../api'
import { useGame } from '../store'

const LVL: Record<string, { n: string; c: string }> = {
  human: { n: 'Você', c: 'var(--accent)' },
  random: { n: 'Iniciante', c: 'var(--lvl-random)' },
  heuristic: { n: 'Amador', c: 'var(--lvl-heuristic)' },
  montecarlo: { n: 'Intermediário', c: 'var(--lvl-montecarlo)' },
  adaptive: { n: 'Adaptativo', c: 'var(--lvl-adaptive)' },
  expert: { n: 'Expert', c: 'var(--lvl-expert)' },
}

export default function ManageTable({ onClose }: { onClose: () => void }) {
  const { state, addPlayer, removePlayer, busy, error } = useGame()
  const roster = state?.roster ?? []
  const [levels, setLevels] = useState<string[]>([])
  const [level, setLevel] = useState('montecarlo')
  const [name, setName] = useState('')

  useEffect(() => {
    api
      .getLevels()
      .then((r) => {
        setLevels(r.levels)
        setLevel((cur) => (r.levels.includes(cur) ? cur : (r.levels[0] ?? cur)))
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const full = roster.length >= 6
  const canRemove = roster.length > 2

  return (
    <motion.div className="guide-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
      <motion.div
        className="guide-modal manage-modal"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="guide-head">
          <h1>
            <Users size={20} />
            Gerenciar mesa
            <span className="guide-sub">{roster.length}/6 lugares</span>
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
              <span className="manage-dot" style={{ background: LVL[r.level]?.c ?? 'var(--text-dim)' }} />
              <span className="manage-name">
                {r.name}
                {r.is_human && <span className="manage-youtag">você</span>}
              </span>
              <span className="manage-lvl">{LVL[r.level]?.n ?? r.level}</span>
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
                onClick={() => removePlayer(r.seat)}
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
            value={name}
            maxLength={16}
            onChange={(e) => setName(e.target.value)}
            disabled={full || busy}
          />
          <select
            className="manage-select"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            disabled={full || busy}
          >
            {levels.map((l) => (
              <option key={l} value={l}>
                {LVL[l]?.n ?? l}
              </option>
            ))}
          </select>
          <button
            className="btn btn-primary manage-addbtn"
            disabled={full || busy}
            onClick={() => {
              addPlayer({ level, name: name.trim() || undefined })
              setName('')
            }}
          >
            <UserPlus size={15} /> Adicionar
          </button>
        </div>

        {full && <p className="manage-hint">A mesa está cheia (6 lugares). Remova alguém para adicionar.</p>}
        {error && <p className="manage-err">{error}</p>}
      </motion.div>
    </motion.div>
  )
}

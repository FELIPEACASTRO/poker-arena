import { motion } from 'framer-motion'
import { Brain, Cpu, Dices, Sigma, Target } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { levelColor } from '../levels'
import { useGame } from '../store'

const ICON: Record<string, LucideIcon> = {
  expert: Cpu,
  adaptive: Brain,
  montecarlo: Sigma,
  heuristic: Target,
  random: Dices,
}
const ACTION_PT: Record<string, string> = {
  fold: 'desistiu',
  check: 'deu check',
  call: 'pagou',
  raise: 'aumentou',
  all_in: 'foi all-in',
}
const PROB_LABELS = ['desistir', 'pagar', 'aumentar ½', 'aumentar pote', 'all-in']

export default function AIMind() {
  const { state, colors } = useGame()
  if (!state || state.last_actions.length === 0) return null

  const last = state.last_actions[state.last_actions.length - 1]
  const seat = state.seats.find((s) => s.seat === last.seat)
  const ins = seat?.insight
  if (!seat || !ins) return null // jogada do humano ou bot sem raciocínio

  // cor do competidor (o ícone já indica o paradigma); fallback pra cor do nível
  const color = colors[seat.name] ?? levelColor(ins.kind)
  const Icon = ICON[ins.kind] ?? Brain
  const topIdx = ins.probs ? ins.probs.indexOf(Math.max(...ins.probs)) : -1

  return (
    <motion.div
      className="aimind"
      style={{ borderTopColor: color }}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="aimind-head">
        <span className="aimind-ico" style={{ color }}>
          <Icon size={16} />
        </span>
        <span className="aimind-who" style={{ color }}>
          {seat.name}
        </span>
        <span className="aimind-act">
          {ACTION_PT[last.type] ?? last.type}
          {last.amount ? ` ${last.amount}` : ''}
        </span>
        <span className="aimind-tag">
          <Brain size={12} /> mente da IA
        </span>
      </div>

      {ins.kind === 'expert' && ins.probs ? (
        <div className="aimind-probs">
          {ins.probs.map((p, i) => (
            <div key={i} className={'aimind-prob' + (i === topIdx ? ' is-top' : '')}>
              <span className="aimind-prob-lbl">{PROB_LABELS[i]}</span>
              <span className="aimind-prob-bar">
                <motion.span
                  animate={{ width: `${Math.round(p * 100)}%` }}
                  transition={{ type: 'spring', stiffness: 220, damping: 26 }}
                  style={{ background: i === topIdx ? color : 'var(--text-faint)' }}
                />
              </span>
              <span className="aimind-prob-pct mono">{Math.round(p * 100)}%</span>
            </div>
          ))}
        </div>
      ) : ins.kind === 'random' ? (
        <p className="aimind-note">{ins.label}</p>
      ) : (
        <div className="aimind-single">
          <span className="aimind-gauge">
            <motion.span
              animate={{ width: `${Math.round(ins.confidence * 100)}%` }}
              transition={{ type: 'spring', stiffness: 200, damping: 26 }}
              style={{ background: color }}
            />
          </span>
          <span className="aimind-gauge-pct mono" style={{ color }}>
            {Math.round(ins.confidence * 100)}%
          </span>
          <span className="aimind-label">{ins.label}</span>
        </div>
      )}

      {ins.kind === 'adaptive' && ins.fold_to_bet != null && (
        <p className="aimind-read">
          leitura do humano: desiste <b>{Math.round(ins.fold_to_bet * 100)}%</b> diante de
          apostas
        </p>
      )}
    </motion.div>
  )
}

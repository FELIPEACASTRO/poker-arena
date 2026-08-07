import { useState } from 'react'
import { Lightbulb, X } from 'lucide-react'

const KEY = 'pa_lab_hint_dismissed'

export default function LabHint() {
  const [show, setShow] = useState(() => localStorage.getItem(KEY) !== '1')
  if (!show) return null
  const dismiss = () => {
    localStorage.setItem(KEY, '1')
    setShow(false)
  }
  return (
    <div className="labhint">
      <Lightbulb size={16} className="labhint-ico" />
      <span className="labhint-text">
        <b>Modo Laboratório:</b> cada cérebro tem uma cor. O painel <b>"mente da IA"</b> mostra,
        os sinais declarados por quem acabou de jogar — probabilidades expostas pelo modelo (Expert),
        equity (Intermediário), força da mão (Amador) e a leitura do humano (Adaptativo).
      </span>
      <button className="ico-btn labhint-x" onClick={dismiss} aria-label="Fechar dica">
        <X size={15} />
      </button>
    </div>
  )
}

import { useEffect, useRef, type CSSProperties } from 'react'
import { motion } from 'framer-motion'
import { Compass, Lightbulb, Target, X } from 'lucide-react'

interface PosInfo {
  id: string
  full: string
  color: string
  range: number // 0..100 — quantas mãos jogar nesta posição
  rotulo: string // apertado / médio / solto / obrigatório
  papel: string
  regra: string
  maos: string
  dica: string
}

// ordem = ordem das cadeiras a partir do botão (igual ao que aparece na mesa)
const POSITIONS: PosInfo[] = [
  {
    id: 'BTN',
    full: 'Botão (Dealer)',
    color: 'var(--pos)',
    range: 95,
    rotulo: 'a MELHOR posição',
    papel: 'Age por ÚLTIMO em todas as rodadas depois do flop — você sempre vê o que todos fazem antes de decidir.',
    regra: 'Jogue MUITAS mãos (a faixa mais larga da mesa). Aumente pra roubar os blinds e use a posição pra controlar o tamanho do pote.',
    maos: 'Pares, cartas altas, conectores e suited — até mãos médias valem.',
    dica: 'É como falar por último numa discussão: você ouve todos os argumentos antes de dar o seu.',
  },
  {
    id: 'SB',
    full: 'Small Blind',
    color: 'var(--accent)',
    range: 40,
    rotulo: 'aposta obrigatória',
    papel: 'É OBRIGADO a pôr metade da aposta antes de ver as cartas. Pior: depois do flop, joga quase primeiro (fora de posição).',
    regra: 'Cuidado: você já tem fichas no pote, mas fica em desvantagem de posição o resto da mão. Complete ou aumente só com mãos decentes — não pague com lixo só porque "já pôs metade".',
    maos: 'Seletivo: mãos boas que aguentem jogar fora de posição.',
    dica: 'É como dar um lance num leilão e ainda ter que mostrar sua carta antes de todo mundo.',
  },
  {
    id: 'BB',
    full: 'Big Blind',
    color: 'var(--accent)',
    range: 55,
    rotulo: 'aposta obrigatória',
    papel: 'É OBRIGADO a pôr a aposta cheia, mas fala por ÚLTIMO no pré-flop — tem o "desconto" de já estar investido.',
    regra: 'Pode DEFENDER bastante contra roubos de blind (já tem fichas no pote), mas lembre: depois do flop você joga cedo (fora de posição).',
    maos: 'Defende largo contra um aumento pequeno; aperta contra aumentos grandes.',
    dica: 'Você já pagou o ingresso — vale a pena ver o filme, mas escolha bem onde sentar.',
  },
  {
    id: 'UTG',
    full: 'Under the Gun',
    color: 'var(--neg)',
    range: 12,
    rotulo: 'a mais APERTADA',
    papel: 'O PRIMEIRO a falar no pré-flop ("debaixo da arma"). Tem a mesa INTEIRA pra agir atrás de você.',
    regra: 'A faixa mais apertada da mesa — só mãos premium. Qualquer um atrás pode ter mão melhor, e você jogará sem saber o que eles têm.',
    maos: 'Só o topo: AA, KK, QQ, JJ, AK, AQ.',
    dica: 'É como ser o primeiro a apostar no escuro — só arrisca quem tem carta MUITO boa.',
  },
  {
    id: 'UTG+1',
    full: 'Under the Gun +1',
    color: 'var(--neg)',
    range: 18,
    rotulo: 'apertada',
    papel: 'Logo depois do UTG — ainda tem quase todo mundo pra agir atrás.',
    regra: 'Quase tão apertado quanto o UTG: abra só mãos fortes, um tiquinho mais largo.',
    maos: 'Pares médios/altos, AK, AQ, AJ, KQ.',
    dica: 'Saiu do "primeiro a falar", mas ainda está cedo — pé no chão.',
  },
  {
    id: 'MP1',
    full: 'Middle Position 1',
    color: 'var(--lvl-heuristic)',
    range: 30,
    rotulo: 'posição do meio',
    papel: 'No meio da mesa: parte dos jogadores já falou, mas ainda há gente atrás.',
    regra: 'Faixa média: além das premium, entram pares médios e cartas altas do mesmo naipe. Sem exageros.',
    maos: 'Pares, AQ/AJ, KQ, suited conectados altos.',
    dica: 'Já dá pra respirar um pouco mais — mas o botão ainda não é seu.',
  },
  {
    id: 'MP2',
    full: 'Middle Position 2',
    color: 'var(--lvl-heuristic)',
    range: 40,
    rotulo: 'meio tardio',
    papel: 'Mais perto do botão que o MP1 — menos gente pra agir atrás.',
    regra: 'Um pouco mais largo que o MP1: já dá pra começar a pressionar e abrir mais mãos.',
    maos: 'Pares, ases com kicker razoável, conectores suited.',
    dica: 'Você está saindo do meio e entrando na "zona de roubo".',
  },
  {
    id: 'DJ',
    full: 'Down Jack (Lojack)',
    color: 'var(--pos)',
    range: 60,
    rotulo: 'posição tardia',
    papel: 'Posição tardia: poucos jogadores atrás de você.',
    regra: 'Faixa ampla — abra mais mãos e comece a roubar os blinds quando a mesa estiver passiva.',
    maos: 'Pares, muitos ases, conectores e suited mais largos.',
    dica: 'Daqui pra frente, agressão controlada compensa: a posição está do seu lado.',
  },
  {
    id: 'HJ',
    full: 'Hijack',
    color: 'var(--pos)',
    range: 75,
    rotulo: 'quase o botão',
    papel: 'Bem perto do botão — "sequestra" (hijack) o roubo de blind antes das últimas cadeiras.',
    regra: 'Jogue agressivo e largo: é uma das melhores posições. Aumente pra roubar e domine os potes pequenos.',
    maos: 'Faixa larga: pares, ases, cartas altas, conectores e suited.',
    dica: 'Roube antes que o botão roube de você — quem ataca primeiro leva os potinhos.',
  },
]

function rangeWord(r: number): string {
  if (r <= 20) return 'joga POUCAS mãos'
  if (r <= 45) return 'joga mãos selecionadas'
  if (r <= 65) return 'joga bastante mão'
  return 'joga MUITAS mãos'
}

export default function PositionsGuide({
  onClose,
  focus,
}: {
  onClose: () => void
  focus?: string
}) {
  const refs = useRef<Record<string, HTMLElement | null>>({})

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  useEffect(() => {
    if (focus && refs.current[focus]) {
      refs.current[focus]?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  }, [focus])

  return (
    <motion.div
      className="guide-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        className="guide-modal"
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: 'spring', stiffness: 260, damping: 26 }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="guide-head">
          <h1>
            <Compass size={20} /> Posições da mesa
            <span className="guide-sub">quem fala quando — e o que jogar</span>
          </h1>
          <button className="ico-btn" onClick={onClose} aria-label="Fechar guia">
            <X size={18} />
          </button>
        </header>

        <p className="guide-intro">
          <b>Posição é QUANDO você fala na rodada.</b> Falar por <b>último</b> é uma vantagem enorme:
          você decide já tendo visto o que todos fizeram. Por isso a regra de ouro:
          <br />
          <i>quanto mais perto do botão, MAIS mãos você joga; quanto mais cedo, mais APERTADO.</i>
          <br />
          As cores e siglas aqui são as mesmas que aparecem nos assentos. 👇
        </p>

        <div className="pos-goldrule">
          <Target size={18} />
          <div>
            <b>Regra de ouro da posição</b>
            <p>
              <span style={{ color: 'var(--neg)' }}>Cedo (UTG) = apertado</span> →{' '}
              <span style={{ color: 'var(--lvl-heuristic)' }}>meio (MP) = médio</span> →{' '}
              <span style={{ color: 'var(--pos)' }}>tarde (HJ/Botão) = solto e agressivo</span>.
            </p>
          </div>
        </div>

        {POSITIONS.map((p) => (
          <section
            key={p.id}
            ref={(el) => {
              refs.current[p.id] = el
            }}
            className={'guide-brain pos-card' + (focus === p.id ? ' is-focus' : '')}
            style={{ '--c': p.color } as unknown as CSSProperties}
          >
            <div className="pos-head">
              <span className="pos-badge">{p.id}</span>
              <div className="pos-id">
                <h2>{p.full}</h2>
                <span className="guide-tag">{p.rotulo}</span>
              </div>
            </div>

            <div className="pos-range">
              <span className="pos-range-k">{rangeWord(p.range)}</span>
              <div className="pos-range-bar">
                <span style={{ width: `${p.range}%`, background: p.color }} />
              </div>
            </div>

            <p className="guide-como">
              <b>🎯 Papel:</b> {p.papel}
            </p>
            <p className="pos-rule">
              <b>📏 Regra:</b> {p.regra}
            </p>
            <p className="pos-hands">
              <b>🃏 Mãos típicas:</b> {p.maos}
            </p>
            <div className="guide-imagine">
              <Lightbulb size={18} />
              <div>
                <b>Imagine assim</b>
                <p>{p.dica}</p>
              </div>
            </div>
          </section>
        ))}

        <button className="btn btn-accent guide-back" onClick={onClose}>
          Voltar ao jogo
        </button>
      </motion.div>
    </motion.div>
  )
}

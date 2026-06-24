import { useEffect, type CSSProperties, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import { Brain, FlaskConical, HelpCircle, Lightbulb, Pencil, ThumbsDown, ThumbsUp, Trophy, X } from 'lucide-react'

// ---------- ilustrações (SVG) de cada cérebro, em estilo "personagem" ----------
const ART: Record<string, ReactNode> = {
  random: (
    <svg viewBox="0 0 100 100" width="62" height="62" fill="none" stroke="currentColor" strokeWidth="3">
      <rect x="20" y="30" width="42" height="42" rx="8" transform="rotate(-8 41 51)" />
      <circle cx="34" cy="44" r="3.5" fill="currentColor" stroke="none" />
      <circle cx="41" cy="51" r="3.5" fill="currentColor" stroke="none" />
      <circle cx="48" cy="58" r="3.5" fill="currentColor" stroke="none" />
      <text x="68" y="42" fontSize="34" fill="currentColor" stroke="none" fontWeight="700">?</text>
    </svg>
  ),
  heuristic: (
    <svg viewBox="0 0 100 100" width="62" height="62" fill="none" stroke="currentColor" strokeWidth="3">
      <rect x="28" y="22" width="44" height="58" rx="6" />
      <rect x="40" y="15" width="20" height="11" rx="3" />
      <path d="M35 41 l5 5 l9 -10" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M35 60 l5 5 l9 -10" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="54" y1="43" x2="64" y2="43" strokeLinecap="round" />
      <line x1="54" y1="62" x2="64" y2="62" strokeLinecap="round" />
    </svg>
  ),
  montecarlo: (
    <svg viewBox="0 0 100 100" width="62" height="62" fill="none" stroke="currentColor" strokeWidth="3">
      <line x1="24" y1="76" x2="78" y2="76" strokeLinecap="round" />
      <rect x="30" y="56" width="9" height="20" fill="currentColor" stroke="none" />
      <rect x="45" y="44" width="9" height="32" fill="currentColor" stroke="none" />
      <rect x="60" y="32" width="9" height="44" fill="currentColor" stroke="none" />
      <text x="44" y="26" fontSize="15" fill="currentColor" stroke="none" fontWeight="700">%</text>
    </svg>
  ),
  adaptive: (
    <svg viewBox="0 0 100 100" width="62" height="62" fill="none" stroke="currentColor" strokeWidth="3">
      <path d="M18 50 Q50 24 82 50 Q50 76 18 50 Z" strokeLinejoin="round" />
      <circle cx="50" cy="50" r="12" />
      <circle cx="50" cy="50" r="4.5" fill="currentColor" stroke="none" />
      <path d="M50 14 l4 7 h-8 z" fill="currentColor" stroke="none" />
    </svg>
  ),
  expert: (
    <svg viewBox="0 0 100 100" width="62" height="62" fill="none" stroke="currentColor" strokeWidth="3">
      <path d="M26 66 L22 38 L38 52 L50 30 L62 52 L78 38 L74 66 Z" strokeLinejoin="round" />
      <line x1="26" y1="72" x2="74" y2="72" strokeLinecap="round" />
      <circle cx="38" cy="52" r="2.6" fill="currentColor" stroke="none" />
      <circle cx="50" cy="30" r="2.6" fill="currentColor" stroke="none" />
      <circle cx="62" cy="52" r="2.6" fill="currentColor" stroke="none" />
    </svg>
  ),
}

interface BrainInfo {
  id: string
  color: string
  emoji: string
  name: string
  tag: string
  fala: string
  como: string
  imagine: string
  fortes: string[]
  fracos: string[]
  vidro: string
}

const BRAINS: BrainInfo[] = [
  {
    id: 'random',
    color: 'var(--lvl-random)',
    emoji: '🟢',
    name: 'Iniciante',
    tag: 'joga no chute',
    fala: '"Eu? Aposto no chute! Cara ou coroa e que seja o que Deus quiser."',
    como: 'Olho só as jogadas permitidas e sorteio UMA, no puro acaso. Não calculo força de mão, não olho ninguém. Zero estratégia.',
    imagine:
      'É o seu primo no churrasco que entrou no jogo agora. Não sabe se a mão presta, então aposta no chute. Ganha uma ou outra de pura sorte — mas no fim da noite tá sem trocado pra rachar a pizza.',
    fortes: [
      'Imprevisível: você não consegue ler um padrão… porque não existe padrão.',
      'De vez em quando blefa "sem querer" e leva o pote.',
    ],
    fracos: [
      'Sangra fichas no longo prazo — é o "peixe" que alimenta a mesa.',
      'Paga com mão lixo e desiste de mão boa.',
      'Nunca extrai valor das mãos fortes.',
    ],
    vidro: '"joga aleatório — sem cálculo de força" (confiança 0%).',
  },
  {
    id: 'heuristic',
    color: 'var(--lvl-heuristic)',
    emoji: '🟡',
    name: 'Amador',
    tag: 'joga por regras',
    fala: '"Eu sigo as regrinhas: par alto? aposto. Carta baixa? tô fora."',
    como: 'Calculo a FORÇA da mão por regras simples (par, cartas altas, naipe igual, conectada) e decido por pot odds. Sempre do mesmo jeito.',
    imagine:
      'É o cozinheiro que segue a receita à risca: "2 ovos, 1 xícara de farinha". Funciona… até acabar o ovo — aí ele trava, não improvisa. No poker joga sempre igual: previsível como horário de novela.',
    fortes: [
      'Fundamento sólido — não comete loucuras.',
      'Ganha fácil do Iniciante.',
    ],
    fracos: [
      'PREVISÍVEL: joga a mesma mão sempre igual → dá pra ler e explorar.',
      'Ignora os oponentes e quase nunca blefa.',
    ],
    vidro: '"Força da mão 61%".',
  },
  {
    id: 'montecarlo',
    color: 'var(--lvl-montecarlo)',
    emoji: '🟠',
    name: 'Intermediário',
    tag: 'calcula as chances',
    fala: '"Antes de apostar, eu simulo 200 partidas na minha cabeça."',
    como: 'Monte Carlo: sorteio as mãos dos oponentes e completo a mesa centenas de vezes, contando quantas eu venço → isso é a EQUITY (minha % real de vitória). Aposto pela probabilidade.',
    imagine:
      'É o engenheiro que, antes de comprar um carro, monta uma planilha e simula 200 cenários de gasto. Decide pela matemática fria — e quase sempre acerta a conta.',
    fortes: [
      'Matematicamente correto: a equity é precisa.',
      'Decisões bem fundamentadas. Ganha do Amador.',
    ],
    fracos: [
      'Assume que todos jogam aleatório — NÃO percebe quem está blefando.',
      'Joga "certinho", mas não EXPLORA ninguém. E é lento (faz muita conta).',
    ],
    vidro: '"Equity 72% (200 simulações)".',
  },
  {
    id: 'adaptive',
    color: 'var(--lvl-adaptive)',
    emoji: '🧠',
    name: 'Adaptativo',
    tag: 'aprende e explora VOCÊ',
    fala: '"Eu te observo. Descobri que você desiste fácil — agora vou te pressionar."',
    como: 'Começo neutro, mas vou ANOTANDO seu estilo (quanto você desiste a apostas, quão agressivo é). Se você desiste demais → eu blefo e roubo os potes. Se você paga tudo → só aposto com mão forte. Eu me MOLDO a você.',
    imagine:
      'É o vendedor que percebe em 2 minutos: "esse cliente adora desconto e desiste fácil" — e ajusta o papo pra te empurrar mais. Ou o professor que muda a explicação pra CADA aluno. Ele joga contra VOCÊ, não contra as cartas.',
    fortes: [
      'EXPLORA suas fraquezas em tempo real.',
      'Contra um humano previsível, é letal — aprende e ajusta.',
    ],
    fracos: [
      'Precisa de tempo pra te "ler" (começa neutro).',
      'A base é heurística, então contra um jogador perfeito ele tem teto.',
      'Se você MUDAR de estilo, ele demora a reagir.',
    ],
    vidro: '"explora: você desiste muito → pressiona/blefa" + "desiste 70% das vezes".',
  },
  {
    id: 'expert',
    color: 'var(--lvl-expert)',
    emoji: '🔴',
    name: 'Expert',
    tag: 'IA treinada (rede neural)',
    fala: '"Eu treinei MILHÕES de mãos contra mim mesmo. Eu não decoro — eu sinto."',
    como: 'Sou uma REDE NEURAL treinada por self-play (joguei comigo mesmo milhões de vezes). Pra cada situação calculo a probabilidade de cada ação e escolho a melhor. Jogo apertado e equilibrado.',
    imagine:
      'É o enxadrista campeão mundial que treinou a vida inteira jogando contra si mesmo — tipo o AlphaGo, que aprendeu sozinho e venceu os melhores do mundo. Ele não pensa em regras: ele "sente" a jogada certa.',
    fortes: [
      'O mais forte de todos — termina com 80%+ das fichas.',
      'Equilibrado (difícil de explorar) e disciplinado: ataca só com vantagem.',
      'Leva os POTÕES.',
    ],
    fracos: [
      'Vence POUCAS mãos (desiste muito) — parece "passivo" pra quem conta mãos.',
      'Foi treinado pra jogar bem CONTRA TODOS, não pra explorar ao máximo UM humano fraco (aí o Adaptativo brilha mais).',
    ],
    vidro: 'as 5 barras de probabilidade da rede neural, ao vivo.',
  },
]

export default function GuideScreen({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

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
            <Brain size={20} /> Os cérebros da Arena
            <span className="guide-sub">guia de bolso</span>
          </h1>
          <button className="ico-btn" onClick={onClose} aria-label="Fechar guia">
            <X size={18} />
          </button>
        </header>

        <p className="guide-intro">
          Cada IA na mesa pensa de um jeito diferente — do que <b>chuta no escuro</b> ao{' '}
          <b>campeão treinado</b>. Vem conhecer os 5 cérebros pessoalmente. 👇
          <br />
          <i>
            Spoiler do Use a Cabeça: o que vence MAIS mãos quase nunca é o que GANHA mais fichas.
            Guarde essa frase — ela explica tudo lá no fim.
          </i>
        </p>

        {BRAINS.map((b) => (
          <section
            key={b.id}
            className="guide-brain"
            style={{ '--c': b.color } as unknown as CSSProperties}
          >
            <div className="guide-brain-head">
              <span className="guide-art">{ART[b.id]}</span>
              <div className="guide-brain-id">
                <h2>
                  {b.emoji} {b.name}
                  <span className="guide-tag">{b.tag}</span>
                </h2>
                <p className="guide-fala">{b.fala}</p>
              </div>
            </div>

            <p className="guide-como">
              <b>🎯 Como eu penso:</b> {b.como}
            </p>

            <div className="guide-imagine">
              <Lightbulb size={18} />
              <div>
                <b>Imagine assim (no dia a dia)</b>
                <p>{b.imagine}</p>
              </div>
            </div>

            <div className="guide-pf">
              <div className="guide-fortes">
                <h3>
                  <ThumbsUp size={15} /> Pontos fortes
                </h3>
                <ul>
                  {b.fortes.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              </div>
              <div className="guide-fracos">
                <h3>
                  <ThumbsDown size={15} /> Pontos fracos
                </h3>
                <ul>
                  {b.fracos.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              </div>
            </div>

            <p className="guide-vidro">
              <FlaskConical size={15} /> <b>Na caixa de vidro:</b> {b.vidro}
            </p>
          </section>
        ))}

        <div className="guide-power">
          <Brain size={18} />
          <div>
            <b>Pare e pense (Brain Power)</b>
            <p>
              Por que o <b>Expert</b> vence MENOS mãos, mas tem MAIS fichas? Porque ganhar no poker
              é levar <b>FICHAS</b>, não quantidade de mãos. O Expert <b>desiste do lixo</b> e ataca
              só os <b>potões</b>. É exatamente o que o painel <i>"Quem mais ganha"</i> mostra!
            </p>
          </div>
        </div>

        <div className="guide-qa">
          <h2>
            <HelpCircle size={18} /> Não existe pergunta besta
          </h2>
          <p>
            <b>P: Então o Iniciante (aleatório) é inútil?</b>
            <br />
            R: Quase! Mas o imprevisível dele é difícil de explorar — às vezes incomoda mais que o
            Amador previsível.
          </p>
          <p>
            <b>P: O Adaptativo é melhor que o Expert?</b>
            <br />
            R: Depende! Contra um humano previsível e fraco, o Adaptativo <b>explora</b> mais. Contra
            todos em geral, o Expert é mais forte e equilibrado.
          </p>
          <p>
            <b>P: Por que o Intermediário não blefa?</b>
            <br />
            R: Porque ele só olha as <b>cartas</b> (equity), não os <b>jogadores</b>. Blefar exige
            LER o oponente — e aí entra o Adaptativo.
          </p>
        </div>

        <div className="guide-exercise">
          <h2>
            <Pencil size={18} /> Afie o lápis
          </h2>
          <p>Cubra as respostas e tente sozinho:</p>
          <ol>
            <li>Qual cérebro joga sem nem olhar a força das cartas? · <span className="guide-ans">Iniciante</span></li>
            <li>Qual te observa e blefa quando você desiste demais? · <span className="guide-ans">Adaptativo</span></li>
            <li>Qual vence MENOS mãos mas ganha MAIS fichas? · <span className="guide-ans">Expert</span></li>
          </ol>
        </div>

        <div className="guide-rank">
          <h2>
            <Trophy size={18} /> No fim das contas (por habilidade)
          </h2>
          <p>
            <span style={{ color: 'var(--lvl-expert)' }}>Expert</span> ≫{' '}
            <span style={{ color: 'var(--lvl-adaptive)' }}>Adaptativo</span> &gt;{' '}
            <span style={{ color: 'var(--lvl-montecarlo)' }}>Intermediário</span> &gt;{' '}
            <span style={{ color: 'var(--lvl-heuristic)' }}>Amador</span> &gt;{' '}
            <span style={{ color: 'var(--lvl-random)' }}>Iniciante</span>
          </p>
          <p className="guide-rank-note">
            As cores aqui são as mesmas dos assentos e dos painéis no jogo. Abra o{' '}
            <b>Modo Laboratório</b> e veja a teoria virar prática ao vivo. 🔬
          </p>
        </div>

        <button className="btn btn-accent guide-back" onClick={onClose}>
          Voltar ao jogo
        </button>
      </motion.div>
    </motion.div>
  )
}

import { type CSSProperties, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import { Brain, FlaskConical, HelpCircle, Lightbulb, Pencil, ThumbsDown, ThumbsUp, Trophy, X } from 'lucide-react'
import { useDialogA11y } from '../useDialogA11y'

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
      'É como alguém que escolhe sem usar informação do estado: serve como controle aleatório para comparar outros agentes.',
    fortes: [
      'Imprevisível: você não consegue ler um padrão… porque não existe padrão.',
      'De vez em quando blefa "sem querer" e leva o pote.',
    ],
    fracos: [
      'Sangra fichas no longo prazo — é o "peixe" que alimenta a mesa.',
      'Paga com mão lixo e desiste de mão boa.',
      'Não foi projetado para extrair valor de forma sistemática.',
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
      'Usa sinais da mão que o controle aleatório ignora.',
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
    como: 'Monte Carlo: sorteio mãos possíveis dos oponentes e completo a mesa várias vezes. A frequência de vitórias é uma estimativa de equity, sujeita a erro amostral e às hipóteses usadas.',
    imagine:
      'É como estimar um gasto sorteando cenários: quanto maior e melhor a amostra, menor tende a ser o ruído da estimativa.',
    fortes: [
      'Produz uma estimativa quantitativa e auditável da equity.',
      'Permite comparar o preço da ação com a chance estimada.',
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
    tag: 'adapta regras a padrões observados',
    fala: '"Eu te observo. Descobri que você desiste fácil — agora vou te pressionar."',
    como: 'Começo com uma hipótese inicial configurada no software e atualizo contagens do seu estilo. Se a amostra indicar mais folds ou calls, ajusto regras de pressão e valor. A leitura é uma heurística, não uma medição clínica nem uma garantia.',
    imagine:
      'É o vendedor que percebe em 2 minutos: "esse cliente adora desconto e desiste fácil" — e ajusta o papo pra te empurrar mais. Ou o professor que muda a explicação pra CADA aluno. Ele joga contra VOCÊ, não contra as cartas.',
    fortes: [
      'Ajusta regras a padrões observados depois de uma amostra mínima.',
      'Pode testar respostas diferentes contra perfis estimados.',
      'Emite um alerta heurístico quando a agressividade muda após uma perda; isso não é diagnóstico de tilt.',
    ],
    fracos: [
      'Sem um perfil humano estável, a parte adaptativa pode ter pouco sinal útil.',
      'Começa pelo "humano típico" — se você fugir do padrão, ele leva algumas mãos pra corrigir o retrato.',
      'A base é heurística, então contra um jogador perfeito ele tem teto.',
    ],
    vidro:
      'no Laboratório (sem humano): "sem leitura confiável — jogo pela força da mão". Contra VOCÊ, depois de te ler: "explora: você desiste muito → pressiona/blefa".',
  },
  {
    id: 'expert',
    color: 'var(--lvl-expert)',
    emoji: '🔴',
    name: 'Expert',
    tag: 'modelo treinado opcional',
    fala: '"Quando um artefato de modelo está disponível, produzo probabilidades de ação."',
    como: 'O backend pode carregar uma rede treinada e amostrar uma política mista. A interface, sozinha, não prova como o artefato foi treinado nem sua força; isso precisa ser reproduzido com versão, dados, sementes e benchmark.',
    imagine:
      'É como uma função aprendida que transforma o estado em probabilidades de ação; seu comportamento depende integralmente do artefato carregado.',
    fortes: [
      'Pode representar decisões não lineares quando um modelo válido está carregado.',
      'Uma política probabilística pode reduzir padrões determinísticos.',
      'Seu desempenho deve ser medido em avaliações reproduzíveis, com incerteza.',
    ],
    fracos: [
      'A taxa de mãos vencidas, isoladamente, não mede retorno nem qualidade da política.',
      'Sessões curtas têm alta variância e não demonstram força relativa.',
      'Sem metadados e benchmark do modelo, não há base para afirmar superioridade.',
    ],
    vidro: 'as 5 barras de probabilidade da rede neural, ao vivo — e, quando duas jogadas empatam, o card avisa que ele SORTEOU (estratégia mista).',
  },
]

export default function GuideScreen({ onClose }: { onClose: () => void }) {
  const dialogRef = useDialogA11y(onClose)

  return (
    <motion.div
      className="guide-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        ref={dialogRef}
        className="guide-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="brains-guide-title"
        tabIndex={-1}
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: 'spring', stiffness: 260, damping: 26 }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="guide-head">
          <h1 id="brains-guide-title">
            <Brain size={20} /> Os cérebros da Arena
            <span className="guide-sub">guia de bolso</span>
          </h1>
          <button className="ico-btn" onClick={onClose} aria-label="Fechar guia">
            <X size={18} />
          </button>
        </header>

        <p className="guide-intro">
          Cada IA na mesa pensa de um jeito diferente — do que <b>chuta no escuro</b> ao{' '}
          <b>modelo treinado opcional</b>. Veja como cada implementação declara decidir. 👇
          <br />
          <i>
            Lembrete: taxa de mãos vencidas e variação de fichas são métricas diferentes.
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

        <div className="guide-science" style={{ borderColor: 'var(--lvl-montecarlo)' }}>
          <h2>🎲 Sorte × Habilidade: a variância (leia isto!)</h2>
          <p>
            Abriu o Laboratório e viu o <b>Amador</b> (ou até o Iniciante) liderando, com o{' '}
            <b>Expert</b> lá no fundo? <b>É normal — é variância.</b> No poker, em POUCAS mãos a{' '}
            <b>sorte domina</b>: quem pega cartas boas dispara, não importa a habilidade. Só em{' '}
            amostras maiores reduzem parte do ruído, mas não garantem uma ordem fixa.
          </p>
          <p className="guide-science-note">
            🔬 O placar desta sessão é descritivo, não um benchmark. Para comparar agentes seria
            necessário fixar versões e sementes, alternar posições, repetir muitas partidas e
            publicar intervalos de confiança. <b>Uma sessão isolada não prova habilidade.</b>
          </p>
        </div>

        <div className="guide-power">
          <Brain size={18} />
          <div>
            <b>Pare e pense (Brain Power)</b>
            <p>
              Uma taxa maior de mãos vencidas implica maior retorno? Não necessariamente: o tamanho
              dos potes e o custo das derrotas também importam. Use o painel apenas para observar a
              sessão e valide hipóteses com uma avaliação controlada.
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
            R: Não. Ele é um controle útil para medir se agentes mais complexos realmente agregam
            algo sob o mesmo protocolo.
          </p>
          <p>
            <b>P: O Adaptativo é melhor que o Expert?</b>
            <br />
            R: Não dá para concluir pela interface. O Adaptativo e o modelo treinado têm objetivos
            diferentes; a comparação exige um protocolo reproduzível para o cenário de interesse.
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
            <li>Qual métrica não deve ser confundida com retorno? · <span className="guide-ans">taxa de mãos vencidas</span></li>
          </ol>
        </div>

        <div className="guide-rank">
          <h2>
            <Trophy size={18} /> No fim das contas (por habilidade)
          </h2>
          <p>
            <b>Hipótese para testar no Modo Jogar:</b> um agente adaptativo pode responder a padrões
            estáveis do jogador após uma amostra suficiente.
          </p>
          <p>
            Compare retorno, variância, decisões e tempo de execução; não presuma uma ordem fixa.
          </p>
          <p style={{ marginTop: '12px' }}>
            <b>No Modo Laboratório</b>, registre também o efeito de posição, baralho e configuração.
            O placar atual não substitui uma bateria pareada.
          </p>
          <p>
            A ordem observada é uma saída experimental que pode mudar entre execuções.
          </p>
          <p className="guide-rank-note">
            As cores são apenas identificadores visuais. Relate tamanho da amostra e incerteza antes
            de interpretar diferenças entre agentes. 🔬
          </p>
        </div>

        <div className="guide-science">
          <h2>🎓 Habilidade e variância: contexto da literatura</h2>
          <p>
            A literatura citada no projeto discute habilidade, aprendizagem e variância no poker.
            Essas referências oferecem contexto, mas não validam automaticamente esta implementação
            nem dispensam a reprodução dos experimentos locais.
          </p>
          <p className="guide-science-note">
            ⚖️ CFR, Cepheus, DeepStack, Libratus e Pluribus são referências externas. Similaridade
            de vocabulário não implica equivalência algorítmica ou de desempenho com a Poker Arena.
          </p>
        </div>

        <button className="btn btn-accent guide-back" onClick={onClose}>
          Voltar ao jogo
        </button>
      </motion.div>
    </motion.div>
  )
}

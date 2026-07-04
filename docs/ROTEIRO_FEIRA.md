# 🎤 Roteiro de demonstração — Poker Arena (feira de ciências)

> Objetivo: em **5 minutos**, mostrar que isto é **IA, matemática e método científico** — não um "joguinho de cartas". Feito para a banca lembrar de **um** diferencial: *a IA explica o que pensa (caixa de vidro) e foi construída com rigor medido*.

---

## ✅ Antes de começar (30 segundos)
1. Duplo-clique no ícone **POKER** → opção **[1] Iniciar** (sobe backend + frontend + navegador).
2. Confira que a tela inicial abriu em `http://localhost:5173`.
3. Deixe uma aba extra no **Swagger** (`http://127.0.0.1:8000/docs`) para a pergunta técnica.
4. Respire. A frase de abertura é: *"Vou mostrar uma IA de poker que **explica cada decisão** — e como eu provei, com números, que ela ficou melhor."*

---

## 🎬 O roteiro (6 momentos)

### 1. Abertura — o enquadramento (30s)
- Aponte o **aviso de Jogo Responsável** na tela de setup.
- Fala: *"Isto é um estudo de **probabilidade, estatística e IA**. Não há dinheiro real. E a ciência mostra que poker é **habilidade**: num campeonato de 32 mil pessoas, os jogadores hábeis lucraram +30,5% e o resto perdeu −15,6%."*
- Escolha **Modo Laboratório** com os **5 níveis** de IA na mesa. Clique em **Iniciar**.

### 2. Modo Laboratório — a caixa de vidro (90s) ⭐ *o coração*
- Os bots jogam sozinhos, cartas abertas. Deixe rodar 2–3 jogadas.
- Aponte o card **"Como o competidor está pensando"**: *"Cada cérebro pensa de um jeito — o Iniciante chuta, o Intermediário **simula centenas de finais**, o Expert é uma **rede neural**. E a IA mostra a chance real, as opções e **o porquê**."*
- Mostre um chip de **MDF/α**: *"Isso é teoria dos jogos: quando o bot blefa, ele calcula quantas vezes o adversário precisa desistir pra valer a pena."*

### 3. O painel de estilo — estatística viva (45s)
- Aponte o **HUD** (VPIP, PFR, WTSD, agressão por região da mesa).
- Fala: *"Estas são as métricas que os profissionais usam. Repare: o Expert entra em poucas mãos mas **vence a maioria dos showdowns** — disciplina. O Iniciante entra em tudo e perde. A personalidade **emerge** do jeito que cada IA calcula."*

### 4. Auditoria — Pluribus, a IA que venceu campeões (45s)
- Abra **Auditoria** → **"🏆 Pluribus — Science 2019"** → dê replay numa mão.
- Fala: *"Estas são mãos **reais** da IA da Universidade Carnegie Mellon que bateu profissionais de elite. A nossa está na mesma família de ideias — self-play — rodando **offline no navegador**."*

### 5. Você joga — a IA te lê (45s)
- Volte, crie uma mesa **Você joga** com um bot **Adaptativo**.
- Fala: *"O Adaptativo começa sabendo como o **humano típico** joga — medido em **250 mil mãos reais** — e se molda a mim. Se eu desistir demais, ele blefa mais."*
- (Se surgir) aponte o **detector de tilt**: *"Ele até detecta quando eu perco a paciência depois de uma derrota — psicologia aplicada."*

### 6. O fecho — o método científico (45s) ⭐ *o que ganha feira*
- Fala: *"O mais importante não é que a IA joga — é **como eu provei que ela melhorou**. Eu criei bots-teste pra atacar as fraquezas do Expert, **medi** os vazamentos, retreinei com dados reais, e criei um **'juiz' automático** que só promove a nova versão se ela vencer a antiga em **todos** os confrontos. A primeira tentativa **foi reprovada** pelo juiz — e isso é o método funcionando. A segunda passou: ficou **quase 2× mais forte**."*

---

## 📊 Números para citar (todos medidos, reproduzíveis)

| Afirmação | Número |
|---|---|
| Expert v2 vs v1 (soma do "juiz" pareado) | **+1.246 → +2.447 bb/100 (~2×)**, melhor em **6/6** confrontos |
| Confirmado por verificação independente | 5 seeds novos, +191 de soma |
| Priors do Adaptativo | **250 mil mãos reais** (fold-to-bet mediano 0,70) |
| Habilidade vs sorte | WSOP 2010: hábeis **+30,5%** × resto **−15,6%** (Levitt-Miles) |
| Fidelidade às regras | validado contra a lib da **U. de Toronto** (paper IEEE) |
| Qualidade | **172 testes backend + 12 frontend**, tudo verde |
| Aleatoriedade das cartas | criptográfica (entropia do SO) |

---

## 🧠 A história científica (o diferencial da banca)
**Análise devastadora** (achei as fraquezas com bots-teste) → **dados reais** (250k mãos, licença aberta) → **treino contra população diversa** → **o juiz reprovou a v1** (−217 num confronto) → **corrigi guiado pelos números** → **juiz aprovou a v2** → **verifiquei de forma independente**. Hipótese → medição → **rejeição** → correção → validação. É ciência de verdade, não "achismo".

---

## ❓ FAQ da banca (respostas de 1 linha)
- **"Isso não é só apostar?"** → Não há dinheiro; é o estudo matemático do jogo — e há evidência científica de que poker é habilidade.
- **"As cartas são aleatórias mesmo?"** → Sim, aleatoriedade **criptográfica** (entropia do sistema operacional), não um `random` qualquer.
- **"Como a IA aprende?"** → Self-play: joga milhões de mãos contra si mesma e contra bots-teste, e uma rede neural aprende a política (OpenSpiel + PPO, servida em ONNX).
- **"Como sei que ela ficou melhor?"** → Um juiz automático mede bb/100 em confrontos pareados (mesmas cartas) e só promove se vencer em tudo.
- **"Qual a arquitetura?"** → Backend Python em Clean Architecture (motor puro → casos de uso → API FastAPI) + frontend React; documentação Swagger/Insomnia.
- **"Dá pra outras modalidades?"** → Roadmap: Short-Deck (viável) e Omaha (analisado); hoje é Texas Hold'em No-Limit, 2 a 9 jogadores.

---

## 🔌 Se algo falhar ao vivo (plano B)
- App não abre → **[2] Parar** e **[1] Iniciar** de novo no launcher; ou abra `http://localhost:5173`.
- Quer provar que está tudo íntegro → **[4] Validar** roda os 184 testes na frente da banca.
- Sem internet → tudo roda **offline**; o Swagger tem versão local em `api-docs/swagger.html`.

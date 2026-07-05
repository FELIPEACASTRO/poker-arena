# Visão em TELAS REAIS — o teste que a banca exige (passo #0)

Rodamos a visão (F1 template + F2 treinado + OCR) em **screenshots REAIS de um cliente de
poker 2D** — o [PokerTH](https://www.pokerth.net/) (open-source, licença livre), que a F2
**nunca viu**. É o domínio certo (cliente 2D digital), não fotos de cartas físicas.

## Resultado honesto (PokerTH.png — gabarito: hero J♠6♥, board 6♠K♣6♣Q♣, pote $700)

| | hole | board | pote | jogadores | sanity |
|---|---|---|---|---|---|
| **F1** | — | 6c 7c 6c Jc (errado) | 9900 (stack) | 0 | **ABSTÉM** |
| **F2** | — | 6s Qs Qd Qc Tc (errado) | 10425 (stack) | 5 | **ABSTÉM** |
| gabarito | Js 6h | 6s Kc 6c Qc | 700 | ~9 | — |

## As duas conclusões (as duas valiosas)

1. **A abstenção FUNCIONA no real.** Nenhum dos dois entregou leitura errada com confiança:
   o sanity pegou "0 cartas do herói" / "carta repetida" e **absteve**. É o "100% ou
   abstém" provado em tela real e nunca vista — o sistema **não recomenda sobre lixo**.

2. **O gap sim→real é REAL e grande.** A F2 treinada só em sintético **não transfere**
   pro PokerTH (as cartas dele têm gráfico/fonte próprios, layout diferente; o pote fica
   noutra posição). Isso é *exatamente* o que a literatura (paper 2509.15045) previu: a
   mAP sintética (98,7%) é inflada; **telas reais exigem fine-tune**.

## O caminho pra fechar (concreto, já preparado)

Estas próprias imagens do PokerTH são **material de treino pro F3** (fine-tune sim→real,
notebook 09). Coletando ~50–150 screenshots reais (PokerTH, jogos de navegador, telas dos
outros mestrandos) → pré-rotular com a visão → corrigir → **fine-tune F3** → re-medir aqui.
Aí a F2 passa a **ler o cliente real** (e não só abster).

Harness reutilizável: `scripts/real_eval.py <pasta>` — solta screenshots reais na pasta e
ele reporta o que F1/F2/OCR leem + a abstenção. É a régua pra levar à banca.

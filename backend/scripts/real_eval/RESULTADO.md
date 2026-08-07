# Visão em telas reais — registro diagnóstico, não prova universal

> Este arquivo registra uma observação histórica. Uma ou duas telas não estimam acurácia,
> e screenshots sem sidecar não contam como evidência. Reexecute `scripts/real_eval.py` para
> obter exact-state com o código/gates atuais.

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

1. **Neste exemplo**, o gate bloqueou as duas leituras erradas. Isso é um teste de regressão,
   não prova “100% ou abstém” nem limita a taxa de falso aceite em outras telas.

2. **Há gap sim→real neste exemplo.** A F2 treinada só em sintético não reconheceu
   corretamente o PokerTH (as cartas têm gráfico/fonte próprios, layout diferente; o pote
   fica noutra posição). Uma tela não estima a magnitude geral desse gap; ela mostra apenas
   que, para este modelo e esta tela, desempenho sintético não bastou como evidência de
   transferência. O valor de mAP citado em versões anteriores não está ligado ao hash do
   ONNX por um relatório reproduzível.

## O caminho pra fechar (concreto, já preparado)

Imagens reais rotuladas podem compor pesquisa futura, com autorização, split por fonte/sessão
e conjunto de teste congelado. Fine-tune pode melhorar ou piorar; só um teste held-out
exact-state e análise de regressão autorizam promoção.

Harness: `scripts/real_eval.py <pasta>`. Ele busca recursivamente, exige sidecars válidos para
contar evidência, mede exact-state e retorna código não-zero se o F2/gabarito necessário falta.

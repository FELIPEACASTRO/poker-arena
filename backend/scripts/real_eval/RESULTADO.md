# Visão em telas reais — execução diagnóstica de 2026-08-07, não prova universal

> Este arquivo registra uma observação histórica. Uma ou duas telas não estimam acurácia,
> e screenshots sem sidecar não contam como evidência. Reexecute `scripts/real_eval.py` para
> obter exact-state com o código/gates atuais.

Rodamos `scripts/real_eval.py scripts/real_eval/imgs` no ambiente local atual sobre duas
telas do PokerTH. O artefato F2 **não está instalado**, portanto esta execução não mede
F2 nem sustenta qualquer alegação de generalização real.

## Resultado executado

| tela | gabarito | F1 exact-state | F1 sanity | latência completa | F2 |
|---|---|---:|---|---:|---|
| `PokerTH.png` | sidecar presente | **0** | **ABSTÉM** | 10,08 s (**acima de 4 s**) | ausente |
| `PokerTH04Screenshot.jpg` | ausente | não conta | **ABSTÉM** | 3,90 s | ausente |

No único item rotulado, o F1 leu hole vazio, board incorreto/repetido e pote 9.900;
o sanity bloqueou a saída. No segundo item também houve cartas repetidas e abstenção,
mas sem sidecar não é possível classificar correção.

## As duas conclusões (as duas valiosas)

1. **Nestas duas telas**, o gate bloqueou as leituras. Isso é diagnóstico,
   não prova “100% ou abstém” nem limita a taxa de falso aceite em outras telas.

2. **Há evidência negativa de transferência do F1** no item rotulado e nenhuma evidência
   atual do F2. Uma tela não estima a magnitude geral do gap; F2 ausente não pode receber
   nota de acurácia. O estado de promoção visual permanece **NO-GO**.

## O caminho pra fechar (concreto, já preparado)

Imagens reais rotuladas podem compor pesquisa futura, com autorização, split por fonte/sessão
e conjunto de teste congelado. Fine-tune pode melhorar ou piorar; só um teste held-out
exact-state e análise de regressão autorizam promoção.

Harness: `scripts/real_eval.py <pasta>`. Ele busca recursivamente, exige sidecars válidos para
contar evidência, mede exact-state e retorna código não-zero se o F2/gabarito necessário falta.

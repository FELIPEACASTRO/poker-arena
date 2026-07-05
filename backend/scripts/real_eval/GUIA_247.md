# Guia — calibrar a visão pra ler o 247 Free Poker (para o demo ao vivo)

O modelo agnóstico (F2) foi treinado só em sintético e **não lê o 247 ainda** (gap sim→real,
medido). O caminho **certo e legítimo** (não hardcodar o 247 — isso quebraria o agnosticismo
que a banca valida) é o **F3: fine-tune do F2 em screenshots reais do 247**. Uma vez feito,
o "Copiloto ao Vivo" lê o 247 dentro do orçamento de ≤4s.

## Passo 1 — Coletar (~20–40 telas do 247)
Jogue no 247freepoker.com e tire screenshots de **mãos variadas**: pré-flop, flop, turn,
river; cartas diferentes; posições diferentes. Salve como `.png`. (Já há 5 telas de tutorial
em `imgs/247/` como semente.)

## Passo 2 — Rotular (uma vez; ~1h pra 30 telas)
Como o F2 ainda não lê o 247, o pré-rótulo automático não ajuda aqui — rotule à mão num
tool web grátis:
1. Suba as telas no [Roboflow](https://roboflow.com/) (grátis) ou [LabelImg](https://github.com/HumanSignal/labelImg).
2. Desenhe as caixas das **cartas** (herói + board), dos **jogadores** (`seat`) e do **botão**
   (`button`), com as **54 classes** do projeto (52 cartas + `seat` + `button`).
3. Exporte em **YOLO** → `real/images/*.png` + `real/labels/*.txt`.
4. Nomeie por fonte pra o split held-out: `247_001.png`, `247_002.png`…

## Passo 3 — Fine-tune (Colab, notebook 09)
Abra o **notebook 09** (`ml/notebooks/09_vision_finetune.ipynb`), coloque os arquivos em
`/content/real/{images,labels}` e rode. Ele parte do F2, **congela o backbone**, mistura
sintético (anti-esquecimento) e mede o ganho no held-out real. Publica `table_yolo11n_ft.onnx`
se melhorar.

Colab: https://colab.research.google.com/github/FELIPEACASTRO/poker-arena/blob/main/ml/notebooks/09_vision_finetune.ipynb

## Passo 4 — Instalar e verificar
1. Baixe o `.onnx` ajustado → renomeie pra `poker_vision.onnx` → `backend/models/`.
2. `uv run python scripts/real_eval.py scripts/real_eval/imgs/247` → confere que agora **lê as
   cartas** do 247 **e** reporta a latência **≤4s**.

## Passo 5 — Demo ao vivo
Janela 1 = 247freepoker. Janela 2 = app → **"Ao Vivo"** → **"Capturar tela do jogo"** →
escolhe a janela do 247. O copiloto lê e recomenda em tempo real (≤4s).

## Gabarito das telas-semente (pra conferir a leitura depois do fine-tune)
| tela | herói | board | pote | jogadores |
|---|---|---|---|---|
| freepoker-preflop | (2 cartas) | — | 10 | 5 |
| freepoker-flop | Q♦ 10♥ | 2♥ 6♣ 10♣ | 10 | 5 |
| freepoker-turn | Q♦ 10♥ | 2♥ 6♣ 10♣ J♠ | 10 | 5 |
| freepoker-river | (2 cartas) | 5 cartas | 26 | 5 |

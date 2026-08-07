# Guia experimental — avaliar visão em uma interface autorizada

O detector foi treinado em sintético e falhou no exemplo real documentado. Uma hipótese de
pesquisa é testar fine-tune em screenshots que o pesquisador esteja autorizado a capturar e
processar. Confira termos de uso, privacidade e consentimento antes da coleta; este guia não
declara que uma plataforma específica autoriza scraping, automação ou redistribuição.
Leitura correta e orçamento de latência precisam ser medidos depois, não presumidos.

## Passo 1 — Planejar uma coleta-piloto autorizada
Em um ambiente autorizado, capture screenshots de **mãos variadas**: pré-flop, flop, turn,
river; cartas diferentes; posições diferentes. Salve como `.png`. Este checkout não contém
um corpus `imgs/247/` pronto; as imagens existentes em `imgs/` não substituem uma coleta
rotulada e consentida.

## Passo 2 — Rotular
Como o detector não generalizou para o exemplo real documentado, trate qualquer pré-rótulo
como proposta a revisar, não como gabarito. Prefira uma ferramenta local, como
[LabelImg](https://github.com/HumanSignal/labelImg). Use um serviço hospedado, como
[Roboflow](https://roboflow.com/), somente se os direitos sobre as imagens e a política de
privacidade autorizarem explicitamente o upload.

1. Importe as telas na ferramenta de rotulagem autorizada.
2. Desenhe as caixas das **cartas** (herói + board), dos **jogadores** (`seat`) e do **botão**
   (`button`), com as **54 classes** do projeto (52 cartas + `seat` + `button`).
3. Exporte em **YOLO** → `real/images/*.png` + `real/labels/*.txt`.
4. Registre fonte, cliente, sessão, tema e baralho no manifesto; o split deve usar esses
   grupos, não apenas um prefixo no nome do arquivo.

## Passo 3 — executar o pipeline de candidato

O notebook 09 exige pares imagem/label estritos, pelo menos quatro grupos com cinco imagens
cada, treino/validação não vazios, baseline HF pinado e seed determinística. Seu gate interno
combina mAP50, mAP50–95 e piso de regressão por classe. A saída fica em
`candidates/<sha256>/` com manifesto; publicação é opt-in e não altera o canônico.

Esses controles impedem os bugs antigos de split vazio e promoção automática, mas ainda são
um gate de **candidato**. Exact-state, falso aceite/abstenção, calibração, latência e paridade
ONNX num conjunto independente continuam obrigatórios antes de instalar o artefato.

Depois de corrigir e testar esse contrato, execute o fine-tune:
Abra o [notebook 09](../../../ml/notebooks/09_vision_finetune.ipynb), coloque os arquivos em
`/content/real/{images,labels}` e rode. A receita parte do F2, congela camadas e mistura
sintético. Não defina `POKER_PUBLISH_ARTIFACTS=1` durante exploração; publique somente um
candidato que passe o gate interno e preserve o manifesto.

## Passo 4 — Verificar antes de instalar

1. Baixe o candidato e confira SHA-256 e manifesto.
2. Aponte `POKER_VISION_MODEL` para o arquivo candidato, sem sobrescrever o canônico.
3. Adicione sidecars completos ao conjunto independente e rode
   `uv run python scripts/real_eval.py <pasta-do-teste>`. O resultado, não o plano, dirá
   exact-state, abstenção e latência.
4. Verifique calibração, falso aceite e paridade ONNX. Só então abra uma decisão explícita de
   promoção e atualize o `MANIFEST.json`/model card.

## Passo 5 — Demo controlada

Use uma interface local ou uma janela cuja captura esteja autorizada. No app, escolha
**“Ao Vivo”** → **“Capturar tela do jogo”**. Enquanto o gate não passar, o comportamento
correto é abster.

## Gabarito

Crie sidecars por imagem conforme o contrato de `scripts/real_eval.py`, com revisão humana
independente. Não use nomes de arquivo ou anotações aproximadas como ground truth.

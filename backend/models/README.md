# Modelos treinados (Expert)

O nível **🔴 Expert** carrega uma política neural treinada em formato **ONNX**.

## Como plugar o modelo

1. Treine no **notebook 05** (`ml/notebooks/05_pokerbench_warmstart.ipynb`) — ele
   produz e publica `poker_expert.onnx` no seu HF Hub.
2. Baixe o `poker_expert.onnx` e coloque **nesta pasta**:
   ```
   backend/models/poker_expert.onnx
   ```
   ou aponte para outro caminho com a variável de ambiente:
   ```
   POKER_EXPERT_MODEL=/caminho/para/poker_expert.onnx
   ```
3. Pronto — o backend detecta o arquivo e o nível **Expert** passa a aparecer
   automaticamente em `GET /levels` e na tela de setup do jogo.

O contrato do ONNX (gerado pelo notebook): entrada `obs` `(1, 121)` float32 →
saída `logits` `(1, 5)` sobre as ações `fold / check_call / raise_half / raise_pot
/ all_in`. O `MLBot` aplica a máscara legal e devolve uma ação válida do motor.

> Os arquivos `.onnx` não são versionados no git (ver `.gitignore`).

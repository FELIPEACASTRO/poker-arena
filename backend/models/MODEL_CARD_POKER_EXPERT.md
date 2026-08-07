# Model card — `poker_expert.onnx`

## Uso pretendido

Política discreta de cinco ações para o bot Expert. Recebe as 121 features definidas em
`poker_arena/ml/encoder.py`; a aplicação mascara ações ilegais antes da amostragem.

Não é um solver e não há evidência suficiente para chamá-lo de GTO, ótimo ou superior a
jogadores humanos. Não deve ser usado para apostas reais ou decisões financeiras.

## Estado de implantação

**QUARENTENA.** O arquivo existe, mas `MANIFEST.json` registra licença e linhagem como não
resolvidas. O gate fail-closed não publica o nível Expert até que o estado seja explicitamente
`approved` ou `promoted`, com hash, governança e contrato válidos.

## Identidade e contrato verificados

- SHA-256: `e1164cc273d93c38eb609329c0cc273507fd48b8219d19ff16ac03a660f75db5`
- Tamanho: 394.449 bytes.
- Produtor ONNX declarado: `pytorch`.
- Entrada: `obs`, float32, `(batch, 121)`.
- Saída: `logits`, float32, `(batch, 5)` na ordem `fold`, `check_call`,
  `raise_half`, `raise_pot`, `all_in`.
- Metadados customizados: ausentes.

## Linhagem e dados

O repositório contém `ml/notebooks/05_pokerbench_warmstart.ipynb` como receita candidata,
mas o artefato não contém commit, dataset revision, seed, configuração, métricas ou hash de
checkpoint. Portanto, a ligação do peso à receita não está comprovada.

O parser PokerBench foi corrigido para a notação compacta e para rejeitar inconsistências
entre alvo e ações disponíveis. Este peso é anterior à correção; sem re-treino reproduzível,
ele não herda automaticamente a validade do pipeline corrigido.

## Métricas e limitações

Não há métricas anexadas de held-out solver agreement, exploitability, lucro contra humanos
ou intervalo de confiança. Features de `to_call`, stack e ação anterior reconstruídas do
PokerBench continuam aproximadas. Qualquer promoção exige avaliação pareada e um artefato
novo ligado a código/dados imutáveis.

Os pós-processamentos históricos `temperature=0.75`, `min_prob_ratio=0.15` e
`sizing_jitter=0.12` não têm validação ligada a este hash e foram desativados por padrão.
Na ausência de uma `inference_policy` aprovada no manifesto, o runtime usa os valores
neutros `1.0`, `0.0` e `0.0`.

## Licença

O ONNX não embute licença. A licença do código do repositório não resolve por si só a licença
dos pesos nem dos dados de treino. Status: **não resolvido**.

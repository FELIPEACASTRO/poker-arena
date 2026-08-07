# Model card — `poker_expert_v1_backup.onnx`

## Estado

Backup local de uma política Expert. Não é selecionado automaticamente pelo backend atual.

- SHA-256: `1a46ce03e97748cea2016d7d9fc8c943779292fe9e06f5368f927fde1dcb91c6`
- Tamanho: 394.449 bytes.
- Entrada: `obs`, float32, `(batch, 121)`.
- Saída: `logits`, float32, `(batch, 5)`.
- Produtor declarado: `pytorch`; metadados customizados ausentes.

Não há manifesto que demonstre de qual checkpoint, dados, seed ou versão de código ele veio,
nem qual relação experimental mantém com `poker_expert.onnx`. As limitações de parser,
métricas e licença descritas no model card principal também se aplicam. Status de linhagem e
licença: **não resolvido**. Não promover este backup com base apenas no nome do arquivo.

Estado de runtime: **QUARENTENA**. Backup ou existência local não equivalem a promoção; o
gate exige estado `approved`/`promoted`, hash, governança e contrato válidos.

# Model card — `card_reader.onnx` (ausente)

O código espera um CNN opcional com entrada float32 `(1,3,96,64)` e duas saídas:
13 logits de rank (`23456789TJQKA`) e 4 logits de naipe (`shdc`). Nenhum arquivo com esse
nome está instalado neste snapshot, portanto não existem hash, metadados, métricas, linhagem
ou licença verificáveis.

Mesmo que um arquivo com esse nome apareça, ele continuará indisponível até existir uma
entrada `approved`/`promoted` no manifesto com SHA-256, licença, linhagem e contrato
`(1,3,96,64) -> (1,13)+(1,4)` válidos.

`localize_read.py` recua para ZNCC por template. Esse caminho é útil como diagnóstico no
estilo sintético calibrado, mas não equivale ao CNN ausente e não fecha o gate de evidência
real. Qualquer afirmação sobre o reader CNN deve permanecer **NÃO TESTADA** até que um
artefato versionado, model card completo e benchmark rotulado sejam fornecidos.

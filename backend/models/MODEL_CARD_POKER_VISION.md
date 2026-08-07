# Model card — `poker_vision.onnx`

## Uso pretendido

Detector experimental de cartas, assentos e botão para propor um `RecognizedState`. A saída
sempre passa pelo gate fail-closed; não é autorização autônoma para uma recomendação.

## Estado de implantação

**QUARENTENA.** Embora o arquivo e seu hash estejam inventariados, a linhagem permanece
parcial. Por isso o detector não é anunciado como disponível; o backend conserva o fallback
F1 até uma entrada `approved`/`promoted` resolver governança e contrato.

## Identidade e contrato verificados

- SHA-256: `2bc63b9b43da261cea7654513f0f5e8646610ca665e13e1129dc0961972a26c4`.
- Tamanho: 10.645.921 bytes.
- Entrada: `images`, float32, `(1, 3, 640, 640)`.
- Saída: `output0`, float32, `(1, 58, 8400)`.
- 54 classes: 52 cartas na ordem rank-major/naipe `s,h,d,c`, seguidas de `seat`, `button`.
- O carregador rejeita shapes ou metadados de classe incompatíveis.

## Linhagem disponível

Os metadados embutidos declaram Ultralytics YOLO11n 8.4.87, exportação em
`2026-07-04T22:23:05.491037` e treino com `/content/pokervision/data.yaml`. Não há commit,
revision do dataset, seed, split, log de treino ou relatório de avaliação ligado ao hash;
assim, a linhagem é apenas parcial. Uma receita no notebook 08 não é prova de que produziu
este binário.

## Evidência e limitações

O ONNX não contém métricas. Resultados sintéticos não demonstram transferência para clientes
reais, e screenshots sem gabarito não medem acurácia. O script `scripts/real_eval.py` agora
exige sidecars rotulados para exact-state e sinaliza execução incompleta quando o artefato ou
gabarito falta.

Falhas esperadas incluem mudança de fonte/layout, oclusão, escala, cartas sobrepostas, falso
positivo confiante e confusão de pote/stack. Confiança agregada não substitui a menor
confiança de um campo crítico.

## Licença

Metadado embutido: `AGPL-3.0 License (https://ultralytics.com/license)`. A compatibilidade
desse regime com distribuição/deploy deve ser revisada pelo responsável pelo projeto; este
registro não é aconselhamento jurídico.

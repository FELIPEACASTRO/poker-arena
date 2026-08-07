# Estado da validação externa de visão — 2026-07-18

## Resultado

**Nenhum modelo foi promovido.** O gate científico e o runner confiável estão
implementados, mas não existe no pacote corpus que satisfaça o perfil
`poker-arena-external-vision-v1-2026-07-18`.

## Inventário local relevante

- `PokerTH.png` possui sidecar completo; a origem Wikimedia Commons registra o
  screenshot PokerTH sob GPL v2+. Serve como smoke diagnóstico, mas é `n=1`.
- `PokerTH04Screenshot.jpg` é atribuído a Doitux na Wikimedia Commons sob GFDL
  1.2+ / CC BY-SA 3.0, porém não possui sidecar de ground truth completo.
- o material “247” não demonstra autorização compatível, não possui gabarito
  completo e tem termos restritivos. Não é elegível para manifesto/receipt.
- ONNX na árvore paralela repetem hashes já inventariados; não são evidência nova.

Buscas em Kaggle e Hugging Face não localizaram corpus específico de screenshots
de interface de poker com licença, rótulos e protocolo compatíveis. Cartas físicas
e UI genérica não validam esse domínio.

## Reprovação demonstrada

O caso de uma observação retorna `fail` com `insufficient_holdout`,
`insufficient_diversity`, `insufficient_accepted_predictions` e
`subgroup_too_small`. Mesmo previsão correta não satisfaz o IC conservador de
falso aceite. Predictions importadas não contam: o gate executa o candidato e o
pipeline real, e liga receipt ao código/configuração/lock atuais.

## Caminho executável

1. Pré-registrar protocolo cego e hash-pinado.
2. Coletar screenshots autorizados, com consentimento/termos e sem dinheiro real.
3. Rotular com ao menos dois anotadores e adjudicar divergências.
4. Criar manifesto conforme `docs/DATASET_GOVERNANCE.md`, com `external-test`
   congelado e grupos separados.
5. Criar plano de avaliação com pares imagem/truth e evidência de anotação.
6. Executar, a partir de `backend`:

Imagem, truth e evidência do protocolo são recapturadas por descritor depois da
validação do manifesto, com identidade estável e SHA-256 conferido antes do
consumo. A inferência usa somente esses bytes em memória e não reabre o path.
Isso comprova o snapshot observado nessa execução; não torna o arquivo de origem
imutável após o término. Preservação posterior exige storage content-addressed
ou read-only e o receipt correspondente.

```powershell
.\.venv\Scripts\python.exe -m poker_arena.ml.external_validation `
  --artifact models\candidate.onnx `
  --candidate-manifest models\MANIFEST.candidate.json `
  --manifest C:\corpus-autorizado\manifest.json `
  --root C:\corpus-autorizado `
  --observations C:\corpus-autorizado\evaluation-plan.json `
  --receipt models\receipts\candidate.external.json
```

Código `0` significa somente que o receipt passou. `scripts/promote_model.py`
cria proposta separada; o manifesto ativo nunca é alterado automaticamente.

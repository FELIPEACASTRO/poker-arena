# Diagnóstico em imagens públicas — contrato de uso

`backend/scripts/public_image_diagnostic.py` mede observações descritivas do pipeline em
screenshots públicos obtidos legalmente. Ele **não pesquisa nem baixa imagens**, não substitui
o holdout externo da tese e não produz recibo de promoção.

Um resultado do Google Imagens é somente um índice. Antes do download manual, abra a página
original, confirme autoria, licença e permissão para o uso pretendido. Não use material com
licença ausente, ambígua, “all rights reserved” ou baseado apenas no filtro de licença do
buscador.

## Manifesto mínimo

```json
{
  "schema_version": 1,
  "purpose": "diagnostic-only",
  "samples": [{
    "image": "imgs/table.png",
    "source_url": "https://commons.wikimedia.org/wiki/File:Example.png",
    "license": {
      "id": "CC-BY-SA-4.0",
      "url": "https://creativecommons.org/licenses/by-sa/4.0/"
    },
    "attribution": "Autor conforme a página original",
    "rights_confirmed": true,
    "redaction_reviewed": true,
    "redact_boxes": [[10, 10, 120, 30]],
    "crop_box": [0, 80, 1280, 640]
  }]
}
```

O caminho é relativo ao manifesto, não pode escapar da pasta e não pode ser symlink. Cada
imagem é limitada a 20 MiB e 16 megapixels. PNG, JPEG e GIF são aceitos; GIF usa somente o
primeiro frame e arquivos com mais de 100 frames são rejeitados. `redact_boxes` usa
`[x, y, largura, altura]` e
mascara nomes/avatares/outros identificadores **na saída**; a inferência recebe a imagem
original para não alterar artificialmente o resultado. `crop_box`, quando presente, define
explicitamente a ROI entregue ao reconhecedor, sem alterar o arquivo-fonte. O frame, crop e
dimensões de entrada são registrados no relatório e fazem parte do ID da variante; assim a
tela completa e a ROI podem ser comparadas sem confusão. A revisão humana de redação é
obrigatória mesmo quando não há caixas.

Um sidecar opcional `table.truth.json` ou `table.json` pode conter `hole`, `board`, `pot` e,
opcionalmente, `n_players` e `position`. Sem sidecar, o relatório registra a predição e a
latência, mas deliberadamente não calcula acurácia.

Execução a partir de `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts\public_image_diagnostic.py `
  caminho\manifest.json caminho\run-novo
```

A saída contém IDs por SHA-256, métricas descritivas por campo/engine, mediana e P95 de
latência e overlays PNG sem EXIF. URLs, atribuição, caminhos locais e mensagens internas de
exceção não são copiados para o relatório sanitizado. Preserve o manifesto original em área
controlada para auditoria e atribuição.

## Interpretação permitida

- É permitido: “o modelo acertou/errou esta amostra licenciada”, com o gabarito disponível.
- Não é permitido: chamar imagens de conveniência de benchmark, estimar generalização,
  comparar alunos estatisticamente ou promover modelo com esse relatório.
- Para a tese, use o gate externo pré-registrado, com amostragem independente, diversidade,
  anotação/adjudicação e intervalos de confiança.

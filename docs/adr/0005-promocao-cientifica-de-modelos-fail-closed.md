# ADR-0005: promoção de visão condicionada a holdout externo

## Status

Superada em 2026-08-07 pela ADR-0006. Mantida como registro histórico do perfil v2.

## Contexto

Existência do ONNX, resultado sintético, uma tela real ou um valor pontual de
acurácia não demonstram generalização. O inventário local possui somente uma
tela PokerTH com gabarito completo. Outros arquivos não têm rótulo completo ou
possuem restrição incompatível de redistribuição. Nenhum constitui holdout externo.

## Decisão

Um artefato de detector de mesa em estado `approved` ou `promoted` precisa conter
`promotion_receipt` com path, SHA-256 e revisão de perfil. O runtime reabre esse
recibo inclusive em cache hit. O recibo só é `pass` quando o runner confiável
executa o ONNX candidato e o pipeline F2 real sobre todas as imagens externas e
comprova:

- manifesto autorizado para `model-evaluation`, licença, consentimento, termos,
  retenção e hashes;
- split `external-test` separado de desenvolvimento;
- protocolo imutável, pré-registrado, cego ao modelo, com ao menos dois
  anotadores e adjudicação de divergências;
- ausência de duplicata exata e near-duplicate perceptual entre splits;
- ao menos 200 observações, 100 aceites, 3 fontes, 3 clientes, 2 temas,
  2 baralhos, 20 sessões e 3 resoluções, com 20 amostras por subgrupo;
- exact-state com limite inferior Wilson 95% >= 0,90; falso aceite com limite
  superior Wilson 95% <= 0,05; ECE/Brier <= 0,05; latência P95 <= 1 s;
- hashes da revisão do pipeline, configuração de inferência, código do avaliador
  e lock de dependências ainda idênticos ao runtime.

O perfil é exclusivo do detector de estado completo. Ele não pode autorizar um
Expert estratégico nem um classificador de crop `card_reader`. `promote_model.py`
somente cria uma proposta nova de manifesto e nunca sobrescreve o ativo.

## Alternativas consideradas

- **Importar predictions JSON:** rejeitada; valores perfeitos poderiam ser
  fabricados sem executar o ONNX.
- **Acurácia pontual ou mAP:** rejeitada; não mede estado completo, incerteza ou
  falso aceite.
- **Resultados sintéticos/de treino:** rejeitados por seleção e gap sim→real.
- **Comparação perceptual O(n²):** rejeitada. A busca usa cinco bandas, cache e
  orçamento; colisão excessiva falha fechada.
- **Promoção automática in-place:** rejeitada por eliminar revisão e rollback.

## Consequências

O fallback continua utilizável, mas nenhum peso atual é promovido. Coleta e
dupla anotação autorizadas têm custo real. Mudar thresholds ou pipeline exige
nova revisão e novos receipts, nunca interpretação retroativa.

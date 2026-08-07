# Diagnóstico em imagens públicas de mesas — 2026-07-18

## Resultado executivo

O F1 **não acertou o estado completo em nenhuma das seis variantes** avaliadas (três
screenshots, cada um em tela inteira e ROI declarada). O gate de segurança recusou as seis,
portanto nenhum estado incorreto chegou ao copiloto como decisão. A única leitura de campo
correta foi o board `3d Ah 2d` no recorte PartyPoker.

Este é um diagnóstico pequeno e dirigido, não um benchmark científico: as imagens foram
encontradas por busca de imagens, mas recuperadas e atribuídas na publicação original; não
formam amostra aleatória nem holdout independente. O gabarito foi lido uma vez por inspeção
humana e ainda não foi adjudicado por um segundo anotador.

## Proveniência e gabarito observado

As três imagens estão publicadas no README do repositório `dickreuter/Poker`, que declara
GPL-3.0. Os binários permaneceram apenas em diretório temporário e não foram incorporados ao
pacote.

| Fonte original | SHA-256 do arquivo | Gabarito humano usado |
|---|---|---|
| `doc/ps-example.png` | `55de1559f35a688edcb23e71031b62e6f1304a08b2ad08790897ad26fcc45097` | hole `As 9s`; board `Kd 2s Jc Tc 2d`; pot `21` centavos |
| `doc/ggpk2.png` | `798fbd5c468f92e77ab45e7a2f19fb47ee280c926369677fbb13c61303b6baab` | hole `Ah 5c`; board `8h Td Ks`; pot `5` centavos |
| `doc/partypoker.gif`, primeiro frame de 63 | `41945e9ca9eadb605ba1f1a6bd0594b1cb072e9cf4116a13a10b6b657366c3b9` | hole `8s 5d`; board `3d Ah 2d`; pot `5` centavos |

Uma quarta imagem do PokerApp/SourceForge foi inspecionada, mas excluída do teste rotulado
porque a página não provou de forma inequívoca a licença específica do screenshot. O download
do PokerTH no Wikimedia Commons retornou HTTP 429; não foram feitos retries agressivos.

## Resultados F1 antes da correção de desempenho

| Variante | Hole correto | Board correto | Pote correto | Estado exato | Aceito |
|---|---:|---:|---:|---:|---:|
| ps-example — tela inteira | não | não | não | não | não |
| ps-example — ROI `[690,0,977,700]` | não | não | não | não | não |
| ggpk2 — tela inteira | não | não | não | não | não |
| ggpk2 — ROI `[730,80,798,615]` | não | não | não | não | não |
| partypoker — tela inteira | não | não | não | não | não |
| partypoker — ROI `[535,125,525,385]` | não | **sim** | não | não | não |

- Estado exato: `0/6`.
- Hole exato: `0/6`.
- Board exato: `1/6`.
- Pote exato: `0/6`.
- Aceites: `0/6`.
- Latência mediana: `3.668,7 ms`; P95 nearest-rank: `7.127,3 ms`.
- O baseline chegou a produzir potes implausíveis como `97.121.224`, `2.165.444.462` e
  `74.422.147.777.772.225.512`; todos foram acompanhados de estado inválido e abstinência.

## Correção: OCR evitado quando as cartas já obrigam abstinência

O perfil mostrou que RapidOCR/ONNX consumia aproximadamente 96% da latência F1. Se a estrutura
das cartas já é impossível, está incompleta, repetida ou abaixo do limiar estrito, ler o pote
não pode transformar o estado em aceitável. O pipeline agora marca o pote como ausente, registra
`pot_source=skipped-card-gate`, pula o OCR e ainda executa o sanity-check completo.

Na repetição das mesmas seis variantes:

- exatidão permaneceu idêntica: estado `0/6`, hole `0/6`, board `1/6`, pote `0/6`;
- aceites permaneceram `0/6` — não houve relaxamento de segurança;
- mediana caiu de `3.668,7 ms` para `76,2 ms` (**48,1 vezes menor**);
- P95 caiu de `7.127,3 ms` para `97,3 ms` (**73,3 vezes menor**).

Esses ganhos são observações nesta máquina e nestas entradas, não SLO nem estimativa
populacional. O caminho OCR de estados com cartas fortes e válidas continua ativo.

## Limites e decisão científica

- O F2 não foi executado: o ONNX instalado continua em quarentena por licença/linhagem não
  resolvidas. Contornar esse gate invalidaria a rastreabilidade da tese.
- `0/6` demonstra que o F1 atual não generaliza para essas interfaces; não demonstra a taxa de
  erro populacional.
- A abstenção funcionou como defesa, mas **abstenção correta não equivale a reconhecimento
  correto**.
- A próxima alegação científica exige dataset externo pré-registrado, anotação dupla/adjudicação,
  split por fonte/cliente sem vazamento, cobertura, risco seletivo, calibração, intervalos de
  confiança e latência por hardware.

O contrato e o runner reproduzível estão em `docs/PUBLIC_IMAGE_DIAGNOSTIC.md` e
`backend/scripts/public_image_diagnostic.py`.

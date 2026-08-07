# ADR-0006: uma única distribuição canônica

## Status

Aceita em 2026-08-07.

## Contexto

A raiz possuía duas árvores executáveis, `CLAUDE` e `CODEX`, com contratos incompatíveis.
A árvore antiga ativava modelos por presença e continha caminhos de VLM/notebooks que não
satisfaziam as fronteiras atuais. Também havia credenciais adjacentes à árvore que o scanner
local não cobria.

## Decisão

`CODEX` é a única solução canônica. A árvore legada e material sensível ficam fora da
distribuição. O gate de segurança escaneia a raiz completa e um contrato executável valida
canonização, metadados acadêmicos e repositório Git funcional.

O repositório Git canônico fica na raiz de `CODEX`, preservando a topologia e o histórico do
repositório público como referência explícita no contrato canônico. Como o checkout recebido
não possuía metadados Git utilizáveis e o objetivo é uma banca local reprodutível, a entrega
usa um snapshot-raiz autocontido, sem depender de objetos Git externos ou temporários; a pasta
`POKER` é apenas o contêiner local da workspace. O sistema
permanece um monólito modular: frontend, API, aplicação, motor e ML têm fronteiras
internas, mas um deploy único evita complexidade operacional sem benefício para o escopo da
dissertação.

## Consequências

### Positivas

- elimina duas verdades científicas e operacionais concorrentes;
- reduz risco de executar acidentalmente o pipeline permissivo;
- dá uma fronteira inequívoca ao scan de release e à citação.

### Negativas

- referências históricas à árvore antiga deixam de ser executáveis;
- restauração exige migração explícita e nova auditoria, nunca cópia silenciosa.

### Neutras

- o código permanece no subdiretório `CODEX` da workspace, mas `CODEX` é a própria raiz Git.

## Alternativas consideradas

- **Manter ambas com aviso:** rejeitada; ainda permite execução da variante errada.
- **Microserviços por componente:** rejeitada; aumenta custo, falhas de rede e operação sem
  necessidade de escala independente.
- **Apagar o legado:** rejeitada em favor de quarentena recuperável fora da distribuição.

# ADR 0003: OpenAPI ao vivo como contrato executável canônico

- Estado: aceita
- Data: 2026-07-18

## Contexto

Manter correções separadas no FastAPI, no arquivo OpenAPI, no Swagger e no projeto
Insomnia permite divergências silenciosas em segurança, paginação, exemplos e cabeçalhos.

## Decisão

1. O schema servido por `/openapi.json`, depois da projeção canônica do projeto, é a fonte
   de verdade do contrato HTTP.
2. `api-docs/openapi.json`, Swagger offline e Insomnia são gerados desse contrato, não
   mantidos manualmente como especificações independentes.
3. O gate de QA compara estruturalmente o contrato ao vivo e o exportado e falha quando
   houver divergência, exemplo inválido ou recurso sem operação correspondente.
4. Exemplos devem ser executáveis e seguros: sem segredo real, sem mojibake, com PHH
   válido e com limites/idempotência documentados.

## Consequências

- Alterar uma rota exige atualizar schema/testes e regenerar os clientes no mesmo ciclo.
- A documentação offline é um artefato reproduzível; edição manual será sobrescrita.


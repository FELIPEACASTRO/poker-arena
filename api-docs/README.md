# Contrato da API — Poker Arena

Esta pasta contém o contrato local da **Poker Arena API 0.2.0**, um serviço de Texas
Hold'em No-Limit para 2 a 9 jogadores. Os artefatos são gerados da aplicação FastAPI;
não devem ser editados manualmente.

## Artefatos

| Arquivo | Finalidade |
|---|---|
| `openapi.json` | Contrato OpenAPI 3.1 importável e fonte do Swagger offline. |
| `swagger.html` | Swagger UI standalone, com a especificação embutida e assets locais. |
| `insomnia.json` | Export Insomnia v4 com todas as operações REST e o WebSocket. |
| `generate.py` | Gerador determinístico dos três artefatos. |
| `vendor/receipt.json` | Proveniência, versão, origem, tamanhos e SHA-256 dos assets Swagger. |

O gerador parte de `app.openapi()` e acrescenta apenas comportamentos que vivem no
middleware e, por isso, não são inferidos automaticamente pelo FastAPI: autenticação
condicional, bloqueio cross-site (`Origin`/`Sec-Fetch-Site`), rejeição de `Host`,
`X-Request-ID`, cabeçalhos de segurança e cabeçalhos de concorrência.

## Swagger

- Com o backend ativo: `http://127.0.0.1:8000/docs` ou
  `http://127.0.0.1:8000/redoc`. Essas duas telas são derivadas diretamente do FastAPI;
  o contrato exportado nesta pasta é mais completo porque também projeta o middleware.
- Offline: abra `swagger.html`. Em `file://`, o botão **Try it out** permanece
  desabilitado.
- Servido por HTTP, o Swagger offline só habilita chamadas quando a própria página está
  em `localhost`, `127.0.0.1` ou `::1`. A autorização não é persistida no navegador.

Para executar o contrato exportado sem CDN, sirva esta pasta localmente e abra
`http://127.0.0.1:8080/swagger.html`:

```powershell
python -m http.server --bind 127.0.0.1 8080 --directory api-docs
```

Os assets offline são cópias byte a byte de `swagger-ui-dist@5.17.14`. O pacote
oficial, o tarball de origem e cada SHA-256 estão fixados em
`vendor/receipt.json`; `vendor/LICENSE` e `vendor/NOTICE` são cópias verbatim
dos arquivos publicados no npm. Tanto a geração quanto `--check` falham se um
asset, licença, notice ou receipt divergir do inventário fixado.

## Insomnia

Importe `insomnia.json` e selecione o ambiente **Base local**. O pacote não contém
credenciais; `api_token` e `request_id` começam vazios, e os cabeçalhos correspondentes
ficam desabilitados. As requisições protegidas trazem as duas alternativas aceitas pelo
runtime, `X-Poker-Token` e `Authorization: Bearer`; habilite somente uma delas.

Variáveis do ambiente:

| Variável | Uso |
|---|---|
| `base_url` | `http://127.0.0.1:8000`. |
| `ws_url` | `ws://127.0.0.1:8000`. |
| `table_id` | ID devolvido por `POST /tables`. |
| `game_id` | ID obtido em `GET /games`. |
| `offset` / `limit` | Janela da listagem de partidas ou das mãos de um replay. |
| `seat` | Índice do assento a remover. |
| `api_token` | Token local, somente se `POKER_API_TOKEN` estiver configurado. |
| `idempotency_key` | Valor único por comando; habilite o cabeçalho quando quiser replay seguro. |
| `expected_version` | Versão lida no estado/ETag; habilite `If-Match` para controle otimista. |
| `request_id` | ID opcional para correlação nos logs. |

Fluxo mínimo:

1. Execute **Mesa → Criar uma mesa** e copie `table_id` para o ambiente.
2. Leia `GET /tables/{table_id}` e observe `version`/`ETag`.
3. Execute a operação adequada ao campo `phase`.
4. Em comandos críticos, use uma `Idempotency-Key` nova e envie a versão em `If-Match`.

Fluxo opcional do VLM remoto (somente pesquisa autorizada):

1. Configure o provedor remoto e um `POKER_API_TOKEN` de 32 a 512 caracteres ASCII
   imprimíveis. O recurso de consentimento recusa acesso anônimo, mesmo que as demais
   rotas estejam operando sem autenticação.
2. Preencha `api_token`, mantenha apenas um dos headers de autenticação habilitado e
   execute `POST /copilot/remote-vlm/consent-sessions` com `{"consent": true}`.
3. Copie o `session_id` emitido para `remote_vlm_session_id` no multipart de
   `/copilot/from-image` e marque `remote_vlm_consent=true`. O fallback remoto só é
   considerado quando o leitor local reprova e a capability ainda está ativa.
4. Revogue a capability com `DELETE /copilot/remote-vlm/consent-sessions`, enviando o
   `session_id` no corpo. Nunca o coloque em path, query string, log ou storage.

`GET /ready` retorna `503/degraded` se o operador habilitar o VLM remoto com token, TTL
ou provedor incompleto. Desabilitado, ele continua sendo uma dependência opcional.

`POST /tables` aceita `Idempotency-Key`, mas não aceita `If-Match`, pois ainda não existe
uma sessão anterior. Os demais comandos de mesa aceitam os dois cabeçalhos. Respostas de
estado incluem `ETag`, `X-Session-Version` e `X-Idempotent-Replay`.
O servidor conserva até 256 respostas idempotentes e mais 4096 tombstones por escopo. Se
a resposta já tiver saído da janela, repetir a mesma chave retorna `409` e nunca reexecuta
o comando. Use uma chave nova somente para uma nova intenção do usuário.

Para o WebSocket, conecte em `/tables/{table_id}/ws` e envie um objeto como:

```json
{
  "type": "call",
  "amount": 0,
  "command_id": "unique-command-1",
  "expected_version": 0
}
```

O servidor envia primeiro um `TableStateResponse`. `player_id` identifica cada jogador
durante toda a sessão, mesmo que a cadeira mude. Cada comando deve ser um objeto JSON
de no máximo 4096 bytes e só pode conter `type`, `amount`, `command_id` e
`expected_version`. `command_id`, quando informado, aceita 1 a 128 caracteres no padrão
`[A-Za-z0-9][A-Za-z0-9._:-]*`; `expected_version` deve ser inteiro não negativo. Erros
de comando chegam como `{"error":"...","code":"..."}` com um dos códigos
`validation_error`, `idempotency_conflict`, `version_conflict` ou `invalid_action`.
Mensagens grandes e JSON inválido retornam apenas `error`.
JSON com profundidade superior a 32 também é recusado sem encerrar a conexão. Toda mutação
REST confirmada e todo comando WebSocket novo publicam o mesmo estado versionado para
todos os clientes conectados à mesa; replays respondem apenas ao cliente solicitante.

Antes do upgrade, a conexão pode ser fechada com `4401` (token inválido quando
configurado), `4403` (`Origin` fora de localhost/127.0.0.1) ou `4404` (mesa ausente).
Quando a autenticação estiver ativa, envie somente `X-Poker-Token` no handshake. Token
em query string é deliberadamente recusado para impedir exposição em URLs e access logs.

## Operações cobertas

| Grupo | Método | Rota |
|---|---|---|
| Sistema | `GET` | `/health` |
| Sistema | `GET` | `/ready` |
| Catálogo | `GET` | `/levels` |
| Mesa | `POST` | `/tables` |
| Mesa | `GET` | `/tables/{table_id}` |
| Jogada | `POST` | `/tables/{table_id}/actions` |
| Jogada | `POST` | `/tables/{table_id}/step` |
| Jogada | `POST` | `/tables/{table_id}/next-hand` |
| Jogadores | `POST` | `/tables/{table_id}/players` |
| Jogadores | `DELETE` | `/tables/{table_id}/players/{seat}` |
| Copiloto | `POST` | `/copilot` |
| Copiloto | `POST` | `/copilot/review-hand` |
| Copiloto | `POST` | `/copilot/from-image` |
| Copiloto | `POST` | `/copilot/remote-vlm/consent-sessions` |
| Copiloto | `DELETE` | `/copilot/remote-vlm/consent-sessions` |
| Auditoria | `GET` | `/games` |
| Auditoria | `GET` | `/games/{game_id}` |
| Tempo real | `WS` | `/tables/{table_id}/ws` |

`/health` e `/ready` são públicos. As demais rotas aceitam `X-Poker-Token` ou
`Authorization: Bearer ...` e passam a exigi-los quando o operador define
`POKER_API_TOKEN`. Todo valor configurado deve ter 32–512 caracteres ASCII imprimíveis;
um valor fraco/inválido bloqueia as rotas protegidas e deixa `/ready` degradado (`503`).
A exceção deliberada é o recurso de consentimento VLM remoto: ele
sempre exige um token válido/configurado. `/games` e `/games/{game_id}` usam paginação
por `offset`/`limit`; siga `page.next_offset` até `null` para percorrer tudo. Logs de partidas são
trilha de auditoria do usuário e, por padrão, não são apagados automaticamente. Poda é
uma operação explícita do backend (`prune_old_games` ou `MatchLogger(retention=...)`).
Arquivos inválidos não são parcialmente aceitos: o detalhe da partida retorna `409`, o
catálogo continua disponível com os jogos íntegros e registra o arquivo corrompido no log
operacional. Uma falha ao gravar uma ação desfaz também a alteração da sessão e do arquivo.

## Erros e cabeçalhos globais

Qualquer rota pode responder `400 text/plain` se `Host` não estiver na allowlist local.
Erros da aplicação usam `{"detail":"..."}`; validação FastAPI usa `422` com detalhes por
campo. Conforme a operação, o contrato também enumera `401`, `403`, `404`, `409`,
`413`, `415` e `503`. `403` cobre mutações cross-site bloqueadas; `503` cobre prontidão
ou dependência remota explicitamente habilitada, mas incompleta. Todas as respostas
documentadas incluem `X-Request-ID`, `Cache-Control: no-store`,
`Content-Security-Policy`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options:
nosniff` e `X-Frame-Options: DENY`.

## Evolução e limite operacional

A API está em `0.2.0`, sem prefixo de versão e voltada a execução local. Até `1.0`, uma
mudança incompatível exige incremento da versão, regeneração dos artefatos e atualização
dos testes/consumidores no mesmo pacote; não há promessa de estabilidade para clientes
externos. Não existe rate limiting no processo FastAPI. Exposição além do loopback exige,
no mínimo, proxy com TLS, autenticação obrigatória e limites de taxa/corpo.

## Regeneração e gate de drift

Na raiz do projeto, no Windows:

```powershell
backend\.venv\Scripts\python.exe api-docs\generate.py
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\api\test_api_docs.py
```

Para apenas detectar drift sem reescrever arquivos, use
`backend\.venv\Scripts\python.exe api-docs\generate.py --check`. O gate agregado usa
esse modo read-only; assim, documentação desatualizada reprova em vez de ser corrigida
silenciosamente durante a validação.

Em um ambiente gerenciado por `uv`:

```bash
cd backend
uv run python ../api-docs/generate.py
uv run pytest -q tests/api/test_api_docs.py
```

O teste compara os três arquivos versionados byte a byte com uma geração nova, valida
também proveniência, tamanho e SHA-256 dos assets Swagger, resolve
todas as referências locais, valida os exemplos JSON contra os modelos do FastAPI,
confere a cobertura das operações no Insomnia e procura padrões conhecidos de segredo.

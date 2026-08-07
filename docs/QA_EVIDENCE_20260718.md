# Evidência de QA e limites — 2026-07-18

> **Evidência histórica:** descreve exclusivamente o checkout de 2026-07-18 e o perfil v2.
> Não deve ser usada como evidência do HEAD ou do gate científico v3 de 2026-08-07.

Este documento registra a validação final do checkout `Poker Arena 0.2.0`. Ele separa
resultado observado de inferência: um gate aprovado demonstra que os contratos testados
passaram nesta máquina; não demonstra desempenho GTO, acurácia em imagens reais nem
generalização científica fora dos dados avaliados.

## Resultado autoritativo

Comando executado na raiz do projeto:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\assets\validar.ps1
```

Resultado final: **14/14 gates passaram**. A execução isolada de confirmação contém
**946 testes de backend: 946 passaram, zero falhou e zero foi ignorado**. Os dois contratos
que antes dependiam do privilégio Windows de criar symlink agora sempre exercitam a defesa
por resolução canônica simulada; a criação real do link continua sendo uma verificação
oportunística adicional, sem produzir skip.

| Gate | Evidência final |
|---|---|
| Backend pytest + branch coverage | passou; limiar fail-closed de 85% atendido |
| Ruff backend e scripts | passou |
| Segurança/F821 em 12 notebooks | passou; `S311` é ignorado somente nesse gate porque os PRNGs dos experimentos são semeados, não criptográficos |
| Mypy | passou em 53 módulos de produção |
| Scanner integral de credenciais | `SECRET_SCAN_OK findings=0` |
| Drift OpenAPI/Insomnia/Swagger | passou; contrato e artefatos 0.2.0 byte a byte coerentes |
| Perfil público estrutural | `PRODUCTION_PROFILE_STATIC_OK`; a homologação bloqueia corretamente imagens sem digest |
| Dependências Python bloqueadas | export do `uv.lock` passou; `pip-audit` sem vulnerabilidade conhecida |
| Frontend Vitest | 62/62 passaram em 15 arquivos |
| Navegação Playwright | 6/6 passaram em dois ciclos isolados (5 locais + 1 autenticado/remoto) |
| TypeScript + build Vite | passou com Vite 8.1.0 deduplicado |
| ESLint | passou |
| `npm audit` | 0 vulnerabilidades conhecidas |

## Cobertura integrada exercitada

O navegador usou build real do frontend e backend Uvicorn real em loopback. Os cenários
cobriram configuração, criação e gestão de mesa, ações, PHH, copiloto, upload multipart de
imagem, WebSocket real, conflito `409` com ressincronização, paginação de partidas/mãos,
viewport móvel e apresentação de erro HTTP.

Um segundo ciclo habilitou autenticação e consentimento remoto com token efêmero. A captura
supervisionada enviou a imagem a um stub VLM OpenAI-compatible estritamente local, que
verificou autenticação, redaction, `no-store` e vínculo do consentimento. A resposta foi
tratada como proposta não calibrada, com confiança zero e decisão nula; o consentimento foi
revogado. Token, storage do navegador, portas e runtime temporário foram verificados como
ausentes após o teste.

## Correções de maior impacto verificadas

- WebSocket passou a ter implementação de runtime explícita (`websockets` 16.x), em vez de
  depender incidentalmente de extras do Uvicorn.
- CORS, autenticação, origem, `TrustedHost` e headers defensivos foram reordenados para que
  preflight local válido funcione sem expor CORS a origens externas e para que erros também
  recebam headers de segurança.
- Logs de partidas passaram a usar criação exclusiva, identidade do arquivo, descritores
  verificados, rejeição de hardlink/reparse/substituição e rollback observável.
- Launchers, gate e runner E2E usam executáveis regulares validados, ambiente allowlist,
  proxy desabilitado nas sondagens, temporários próprios e cleanup de árvore/fallback do
  processo exato.
- No Windows, o runner E2E usa Job Objects com `KILL_ON_JOB_CLOSE`; `start.ps1`/`stop.ps1`
  mantêm `taskkill` como primeira tentativa e usam fallback Toolhelp32 ligado a
  `PID + StartTime + Path`, com recaptura e encerramento dos descendentes em profundidade.
- O perfil público exige origem HTTPS exata, hostname explícito, `/api`, segredo por arquivo,
  identidade individual fornecida pelo proxy e autenticação HTTP/WebSocket. NGINX aplica
  TLS, HSTS, OIDC, limites de taxa/conexão e headers defensivos; serviços ficam non-root,
  read-only e em redes segmentadas.
- A visão aprovada/promovida passou a exigir receipt de holdout externo ligado ao ONNX,
  manifesto, plano, código/configuração e lock. Predictions importadas não contam: o runner
  executa o candidato F2. O receipt de visão não pode autorizar `expert` ou `card_reader`, e
  a ferramenta de promoção somente cria uma proposta nova, nunca sobrescreve o ativo.
- O caminho estrito de visão agora evita RapidOCR quando a estrutura/confiança das cartas já
  torna a abstinência inevitável. Nas seis variantes públicas licenciadas, a exatidão e os
  `0/6` aceites permaneceram inalterados, enquanto a mediana caiu de 3.668,7 ms para 76,2 ms
  e o P95 de 7.127,3 ms para 97,3 ms. O sanity-check completo continua obrigatório.
- A resolução F2 deixou de sondar e revalidar repetidamente o mesmo candidato dentro de uma
  inferência; o artefato aprovado é resolvido uma vez e ligado ao recognizer. Ausência,
  quarentena e falhas de inferência continuam com fallback controlado.
- Upload e captura ao vivo exibem agora motor executado, estado, confiança reportada,
  latência observada, decisão/abstenção e todos os motivos, sem apresentar confiança como
  acurácia. O limite do frontend foi alinhado aos 5 MiB reais do backend e falha de `toBlob`
  deixou de ser silenciosa.
- Notebooks não propagam tokens para instaladores; a chave HMAC do PHH é mantida em
  `bytearray`, zerada e esvaziada após uso; OpenSpiel foi fixado em `1.6.15` nos notebooks
  que o instalam.
- Swagger UI offline 5.17.14 possui licença, notice, receipt, tamanhos e SHA-256 verificados
  fail-closed. OpenAPI, Swagger e Insomnia foram regenerados na versão 0.2.0.

## Smoke do launcher

`assets/start.ps1` iniciou backend e frontend reais e suas sondagens internas obtiveram
HTTP 200 em `/ready` e `/`. Em seguida, `assets/stop.ps1` foi executado fora do sandbox:
mesmo com erros da tentativa graciosa via `taskkill`, o fallback encerrou as raízes e o
filho Uvicorn registrados. Os PIDs 12904, 15024 e 20868 deixaram de existir, os dois
endpoints ficaram inalcançáveis e o arquivo `pids.json` foi removido. Uma segunda limpeza
confirmou igualmente ausentes os PIDs 18940, 3712 e 20660. Ao fim do QA não restou PID
registrado nem serviço E2E nas portas de teste.

## Limites científicos e operacionais restantes

1. Não existe ainda um benchmark autorizado, versionado e externo de screenshots reais que
   prove acurácia, calibração e generalização da visão entre sites, temas, resoluções e decks.
   O gate exige, entre outros controles, 200 observações, 100 aceites, 3 fontes, 3 clientes,
   20 sessões, subgrupos de 20, dupla anotação/adjudicação, independência perceptual de splits,
   Wilson 95%, falso aceite, ECE, Brier e P95. O material local rotulado é `n=1` e falha
   corretamente; nenhum modelo atual foi promovido.
   Um diagnóstico adicional em três screenshots públicos/seis variantes obteve estado exato
   `0/6`, hole `0/6`, board `1/6` e pote `0/6`; as seis leituras foram corretamente recusadas.
   Ele está documentado em `docs/research/PUBLIC_TABLE_IMAGE_CHECK_20260718.md` e não satisfaz
   os requisitos do holdout por ser amostra de conveniência com anotação humana única.
2. Nenhum modelo ou dataset descoberto em Kaggle, Hugging Face ou nas plataformas regionais
   foi promovido automaticamente. Licença, proveniência, near-duplicates, split por grupo,
   holdout externo e manifesto imutável continuam obrigatórios.
3. O perfil público está implementado e testado estruturalmente, mas ainda não está homologado
   num host de internet. Faltam certificados/IdP reais, imagens por digest, build e `nginx -t`
   em Docker, handshake TLS/WSS, MFA, carga, SBOM/scan/assinatura e pentest. O modo atual é um
   workspace autenticado compartilhado, não multi-tenancy hostil com ownership/ACL por usuário.
4. Nenhum treino remoto Modal/HF foi necessário para estas correções. Portanto não há receipt
   novo de GPU, métrica ou checkpoint que sustente ganho científico de modelo nesta rodada.
5. `open_spiel==1.6.15` fecha a dependência direta dos notebooks, mas o arquivo de tese deve
   acrescentar hashes de todas as wheels transitivas ou uma imagem de container imutável para
   reprodução arquivística completa.
6. O projeto não contém histórico Git funcional neste checkout. Sem commit/árvore assinada,
   a rastreabilidade de alterações depende dos arquivos e receipts presentes no pacote.
7. Foram removidos 64 caches, builds e logs de QA comprovados. O último diretório,
   `backend/.ruff_cache`, continha uma entrada com ACL anômala e foi movido como unidade para
   a quarentena recuperável
   `C:\tmp\poker_codex_backend_ruff_cache_acl_quarantine_20260718`; ele não permanece no pacote
   e não foi tratado como fonte ou evidência. A rodada final removeu ainda os caches
   regeneráveis de pytest/Ruff/Mypy, `frontend/dist`, logs do smoke e seus dois basetemps;
   a inspeção posterior confirmou todos ausentes.
8. As imagens “247” tinham termos incompatíveis com o uso pretendido e foram retiradas do
   pacote para a quarentena recuperável
   `C:\tmp\poker_codex_restricted_247_images_20260718`. Os screenshots PokerTH permanecem
   apenas como smoke licenciado; um tem gabarito completo e não constitui benchmark externo.

## Reexecução

O gate autoritativo continua sendo `assets/validar.ps1`. Execuções parciais ajudam no
diagnóstico, mas não substituem o resultado agregado porque não cobrem simultaneamente
contrato, dependências, segurança, frontend e navegação.

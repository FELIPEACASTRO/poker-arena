# Poker Arena — frontend

Cliente local em React + TypeScript/Vite para os modos Jogar e Laboratório, gestão de
assentos, auditoria, perfis competitivos contextuais, copiloto de análise e captura
supervisionada. A interface não é uma
fronteira de autorização: regras, versões, idempotência e validação permanecem no backend.

## Execução local

1. Suba o backend em outro terminal:

   ```powershell
   cd ..\backend
   uv run uvicorn poker_arena.api.app:app --host 127.0.0.1 --port 8000
   ```

2. Na pasta `frontend`, instale e inicie:

   ```powershell
   npm.cmd ci
   npm.cmd run dev
   ```

3. Abra `http://localhost:5173`. O cliente usa `http://127.0.0.1:8000` por padrão.
   Para outro backend, defina a variável antes de iniciar:

   ```powershell
   $env:VITE_API = "http://127.0.0.1:9000"
   npm.cmd run dev
   ```

Use apenas origens autorizadas pelo backend. `VITE_API` é configuração pública incorporada
ao bundle; nunca coloque token ou outra credencial nessa variável nem em arquivos `.env`.

## Arquitetura atual

| Caminho | Responsabilidade |
|---|---|
| `src/api.ts` | cliente HTTP, erro tipado, paginação e cabeçalhos `Idempotency-Key`/`If-Match` |
| `src/store.ts` | estado da mesa, identidade de jogador, versão otimista, retry idempotente, ressincronização 409 e cancelamento |
| `src/App.tsx` | navegação e composição das telas/modais |
| `src/components/SetupScreen.tsx` | consulta `/levels` e configuração de 2 a 9 jogadores |
| `src/components/PokerTable.tsx` + `Seat.tsx` + `Card.tsx` | mesa, posições e cartas |
| `src/components/ActionBar.tsx` | ações legais devolvidas pelo backend |
| `src/components/ManageTable.tsx` | inclusão e remoção de bots |
| `src/components/CopilotScreen.tsx` | análise de spot e histórico PHH |
| `src/components/LiveCopilotScreen.tsx` + `src/capture.ts` | captura com consentimento e envio supervisionado |
| `src/components/VisionDiagnostics.tsx` | estado detectado, confiança reportada, abstenção, latência e motivos sem inventar métricas |
| `src/components/AuditPage.tsx` | lista e replay dos jogos persistidos |
| `src/components/WatchPanels.tsx` | placar, corrida de fichas e perfil contextual por posição/papel com incerteza e abstenção |
| `src/useDialogA11y.ts` | foco, Escape e semântica dos diálogos |
| `src/styles.css` + `src/theme.css` | layout, tokens visuais e responsividade |

Fluxo principal: configuração → `POST /tables` → estado versionado → comando com chave de
idempotência e versão esperada → novo estado. Uma falha de transporte é repetida no máximo
uma vez com a mesma chave; um `409` força `GET /tables/{id}` e revisão humana antes de nova
tentativa. Vitórias usam `player_id`, nunca o índice mutável da cadeira. A interface cancela
respostas superadas, mas o backend continua sendo a fonte única das ações legais e do resultado.

No modo `watch`, cada item em `watch_stats.bots` pode conter `competitive_profile`. A UI
exibe o painel recolhível **Inteligência contextual**, sempre com numerador/denominador,
nível de evidência e intervalo; não converte a leitura em conselho e não envia o perfil de
volta ao motor. Os estados antes de 12 oportunidades permanecem `insufficient`; 12–29 são
`emerging` e 30 ou mais são `stable`. Esses cortes são operacionais e aparecem como tal.

O formulário do Copiloto não se limita a narrar uma mão concluída: ele recebe um spot atual,
hipotético ou histórico e devolve recomendação, tamanho de raise quando aplicável, equity,
pot odds, alternativas e justificativa. O replay PHH é necessariamente pós-mão. A entrada
visual só mostra recomendação quando o backend a autoriza; F1 e estados abstidos continuam
diagnósticos. O uso pretendido permanece estudo/simulação local, não RTA em terceiros.

## Qualidade

Na pasta `frontend`:

```powershell
npm.cmd test
npm.cmd run build
npm.cmd run lint
npm.cmd run typecheck:e2e
npm.cmd run test:e2e
npm.cmd audit --audit-level=high
```

- Vitest + Testing Library cobrem cliente, store e componentes em ambiente JSDOM.
- Playwright executa navegação contra o backend real e o build de produção, verifica o
  fluxo de mesa, ações, copiloto, gestão, auditoria paginada, diálogos, mesa móvel, responsividade, semântica
  básica, modos de um/dois monitores, perfil competitivo e uma falha HTTP controlada.
- O E2E usa `127.0.0.1:8765` para a API e `127.0.0.1:4177` para a UI, inicia e encerra os
  servidores do teste e usa Microsoft Edge por padrão. O runner recompila a UI em um
  runtime único, transmite aos filhos apenas uma allowlist de variáveis do sistema e não
  herda tokens, manifests, VLM remoto nem diretório de logs do shell. Defina
  `PLAYWRIGHT_CHANNEL` apenas para um canal de navegador compatível já instalado.
- Screenshots de falha existem somente dentro do runtime temporário e são apagados após
  todos os processos serem encerrados; trace e vídeo ficam desativados. Isso minimiza a
  retenção de páginas que poderiam conter dados sensíveis.

O gate agregado do projeto é [`../assets/validar.ps1`](../assets/validar.ps1). Não trate a
existência desses testes como resultado: o estado válido é a saída da execução no checkout
e ambiente em questão.

O contrato de linguagem e evidência do painel de visão está em
[`../docs/VISION_PRESENTATION.md`](../docs/VISION_PRESENTATION.md). Confiança interna não é
apresentada como acurácia/calibração, e uma latência isolada não é apresentada como benchmark.
Os resultados atuais em screenshots públicos estão separados no
[`diagnóstico datado`](../docs/research/PUBLIC_TABLE_IMAGE_CHECK_20260718.md).

O launcher abre `/?view=capture`, um workspace exclusivo em tela cheia. O fluxo é autorização →
escolha temporária de **Mesmo monitor** ou **Outro monitor** → seleção de **Janela** →
confirmação da prévia → análise. Tela inteira e guia são bloqueadas e
nenhum quadro é enviado antes da confirmação. Quadros são reduzidos para até 1280 px, processados
sequencialmente com backoff após falhas e mostrados com percepção, confiança interna, latência e
abstenção; recomendações estratégicas ficam ocultas no modo de apresentação. A revisão manual
continua disponível em `/?view=copilot`.

Para validar os guias derivados da interface:

```powershell
npm.cmd run docs:pedagogical-guide
npm.cmd run docs:navigation-guide
node e2e/render_navigation_guide.mjs
```

O segundo comando atualiza screenshots canônicos e, portanto, deve ser usado somente em
uma revisão documental deliberada. Consulte o [índice canônico](../docs/README.md).

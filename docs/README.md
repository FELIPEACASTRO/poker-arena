# Índice canônico da documentação

Atualizado em **2026-08-08**. Este índice separa documentação operacional vigente,
contratos normativos, evidência datada, artefatos gerados e registros históricos. Essa
separação impede que um resultado antigo seja apresentado como propriedade do checkout
atual.

## Estado da solução documentada

O produto liberável é a demonstração **local, supervisionada e offline** com escopo
`LOCAL_MASTER_DEFENSE`. O último snapshot funcional integralmente validado antes desta
reconciliação documental é `b055b235192706b455642932d8bc81a9cc99606a`: 16/16 gates,
1.141 testes backend, 80 testes frontend e 13 cenários E2E. Esses números são evidência
datada, não uma promessa permanente; qualquer mudança exige nova execução do gate e do
preflight.

Na reconciliação documental atual, as regressões dirigidas passaram com 1.141/1.141
backend, 80/80 frontend, build/lint, 13/13 E2E, OpenAPI sem drift, guias HTML sem erro e
receipt v5 aprovado. Isso valida o conteúdo alterado, mas não substitui os 16 gates e o
preflight clean-tree exigidos depois do commit candidato.

Implementações atualmente expostas:

| Área | Contrato implementado | Limite explícito |
|---|---|---|
| Launcher Windows | `POKER.bat` inicia backend, frontend e navegador; lista URLs; valida; executa preflight; encerra somente processos registrados | perfil local em `127.0.0.1` |
| Captura | escolha temporária entre mesmo/outro monitor, consentimento, seleção obrigatória de `Janela`, prévia e zero upload antes da confirmação | o navegador não revela o número físico do monitor |
| Visão | F1/F2/F3, estado proposto, sanidade, confiança interna, latência e abstenção | somente F2 promovido por receipt externo poderia autorizar decisão; nenhum está promovido |
| Motor | NLHE 2–9 jogadores, posições exatas, apostas, all-in, side pots, showdown e auditoria atômica | sem ante, rake, straddle ou múltiplos boards no diferencial atual |
| Bots | Random, Heuristic, Monte Carlo, Adaptive e Expert condicionado ao manifesto | instrumentação não prova GTO nem interpretabilidade causal |
| Copiloto | recebe um spot descrito e devolve ação sugerida, valor do raise quando aplicável, equity, pot odds, opções e justificativas; também revisa histórico PHH | apoio educacional/local; a recomendação é heurística e não prova GTO |
| Inteligência competitiva | RFI, limp, isolamento, call/3-bet/squeeze/4-bet, steal/defesa, blind-versus-blind, resposta a aposta e agressão IP/OOP por posição/papel | sessão local, descritiva, com incerteza/abstenção e sem conselho de ação |
| API e tempo real | FastAPI, OpenAPI/Swagger/ReDoc offline, Insomnia, REST versionado e WebSocket | backend local não deve ser publicado diretamente |
| Segurança | loopback, host/origin allowlist, limites de corpo, scan de segredos, consentimento remoto efêmero e fail-closed | perfil público de referência ainda exige homologação externa |

Generalização visual em clientes reais, optimalidade GTO, produção multi-tenant e jogo com
dinheiro real permanecem fora do escopo e não são alegados.

O nome “pós-jogo” encontrado em contratos antigos descreve a **política de uso seguro**,
não ausência de recomendação. O formulário de spot efetivamente calcula o que fazer no
estado informado. Já o histórico PHH é retrospectivo. A captura por imagem só expõe uma
recomendação quando visão, sanidade e contexto de apostas têm autoridade suficiente; com o
F1 atual da banca, o comportamento correto é reconhecer/diagnosticar e suprimir a ação.

## Comece por aqui

| Objetivo | Documento vigente |
|---|---|
| Instalar, iniciar, parar e conhecer a arquitetura | [`../README.md`](../README.md) |
| Operar a captura visual | [`GUIA_DE_NAVEGACAO_POKER_ARENA.html`](GUIA_DE_NAVEGACAO_POKER_ARENA.html) e [PDF](GUIA_DE_NAVEGACAO_POKER_ARENA.pdf) |
| Aprender toda a solução | [`GUIA_PEDAGOGICO_POKER_ARENA.html`](GUIA_PEDAGOGICO_POKER_ARENA.html) |
| Apresentar à banca | [`ROTEIRO_BANCA.md`](ROTEIRO_BANCA.md) |
| Consultar o parecer vigente | [`RELATORIO_OMEGA_AUDITORIA_20260807.md`](RELATORIO_OMEGA_AUDITORIA_20260807.md) |
| Interpretar visão sem exagero | [`VISION_PRESENTATION.md`](VISION_PRESENTATION.md) |
| Entender inteligência competitiva | [`research/COMPETITIVE_INTELLIGENCE_20260808.md`](research/COMPETITIVE_INTELLIGENCE_20260808.md) e [`adr/0008-inteligencia-competitiva-contextual-descritiva.md`](adr/0008-inteligencia-competitiva-contextual-descritiva.md) |
| Usar a API | [`../api-docs/README.md`](../api-docs/README.md), [Swagger offline](../api-docs/swagger.html) e [OpenAPI](../api-docs/openapi.json) |
| Contribuir e validar | [`../CONTRIBUTING.md`](../CONTRIBUTING.md) e [`NON_FUNCTIONAL_REQUIREMENTS.md`](NON_FUNCTIONAL_REQUIREMENTS.md) |

## Classificação de todos os documentos Markdown e HTML

### Vigentes e normativos

- raiz: [`../README.md`](../README.md), [`../CONTRIBUTING.md`](../CONTRIBUTING.md) e
  [`../SECURITY.md`](../SECURITY.md);
- componentes: [`../frontend/README.md`](../frontend/README.md),
  [`../api-docs/README.md`](../api-docs/README.md), [`../ml/README.md`](../ml/README.md),
  [`../ml/LOGGING_STYLE.md`](../ml/LOGGING_STYLE.md) e
  [`../deploy/production/README.md`](../deploy/production/README.md);
- operação/ciência: [`NON_FUNCTIONAL_REQUIREMENTS.md`](NON_FUNCTIONAL_REQUIREMENTS.md),
  [`VISION_PRESENTATION.md`](VISION_PRESENTATION.md),
  [`PUBLIC_IMAGE_DIAGNOSTIC.md`](PUBLIC_IMAGE_DIAGNOSTIC.md),
  [`DATASET_GOVERNANCE.md`](DATASET_GOVERNANCE.md), [`ROTEIRO_BANCA.md`](ROTEIRO_BANCA.md)
  e [`ROTEIRO_FEIRA.md`](ROTEIRO_FEIRA.md);
- modelos e VLM: [`../backend/models/README.md`](../backend/models/README.md), os quatro
  `MODEL_CARD_*.md`, [`../backend/scripts/GUIA_VLM.md`](../backend/scripts/GUIA_VLM.md) e
  [`../backend/scripts/real_eval/GUIA_247.md`](../backend/scripts/real_eval/GUIA_247.md);
- decisões: [`adr/README.md`](adr/README.md) e ADRs 0001–0008.

### HTML operacional ou gerado

- [`GUIA_DE_NAVEGACAO_POKER_ARENA.html`](GUIA_DE_NAVEGACAO_POKER_ARENA.html) e
  [`GUIA_PEDAGOGICO_POKER_ARENA.html`](GUIA_PEDAGOGICO_POKER_ARENA.html) são guias
  versionados e testados;
- [`../frontend/index.html`](../frontend/index.html) é o shell do cliente;
- [`../api-docs/swagger.html`](../api-docs/swagger.html) é gerado de `app.openapi()` e deve
  permanecer idêntico ao gerador.

### Evidência datada: preservar resultados e limites

- auditoria vigente: [`RELATORIO_OMEGA_AUDITORIA_20260807.md`](RELATORIO_OMEGA_AUDITORIA_20260807.md);
- pesquisa atual de perfis: [`research/COMPETITIVE_INTELLIGENCE_20260808.md`](research/COMPETITIVE_INTELLIGENCE_20260808.md),
  inventário Markdown/JSON de 23 fontes e registro da figura;
- visão: [`ml/EXTERNAL_VALIDATION_STATUS_20260718.md`](ml/EXTERNAL_VALIDATION_STATUS_20260718.md),
  [`research/PUBLIC_TABLE_IMAGE_CHECK_20260718.md`](research/PUBLIC_TABLE_IMAGE_CHECK_20260718.md)
  e [`../backend/scripts/real_eval/RESULTADO.md`](../backend/scripts/real_eval/RESULTADO.md);
- pesquisa anterior: `research/STATE_OF_ART_20260717.md`,
  `research/PLATFORM_SWEEP_20260717.md` e todos os receipts em `research/evidence/`.

Datas, hashes, contagens e resultados desses documentos descrevem o artefato declarado em
cada um; não devem ser reescritos retroativamente para “parecer atuais”.

### Históricos ou superados

- [`RELATORIO_FINAL_AUDITORIA_20260807.md`](RELATORIO_FINAL_AUDITORIA_20260807.md) e
  [`QA_EVIDENCE_20260718.md`](QA_EVIDENCE_20260718.md) são snapshots superados pelo Omega;
- `superpowers/specs/`, `superpowers/plans/` e `superpowers/research/` registram desenho e
  pesquisa de junho, não o contrato atual;
- `../backend/scripts/expert_om_evidence/` preserva um experimento reprovado/adversarial;
- model cards de artefatos ausentes, candidatos ou em quarentena registram justamente esse
  estado e não autorizam runtime.

## Regra de manutenção documental

Uma mudança precisa atualizar, na mesma revisão:

1. o README do componente e este índice quando a superfície de uso mudar;
2. OpenAPI/Swagger/Insomnia quando o contrato HTTP mudar;
3. guias HTML, screenshots e PDF quando a interface ou o roteiro mudar;
4. NFR/ADR quando autoridade, confiança, privacidade ou critério de aceite mudar;
5. relatório datado somente com evidência realmente executada, preservando o snapshot anterior.

Validação mínima da documentação:

```powershell
backend\.venv\Scripts\python.exe api-docs\generate.py --check
cd frontend
npm.cmd run docs:pedagogical-guide
npm.cmd run typecheck:e2e
```

O gate autoritativo continua sendo `assets\validar.ps1`; para a banca, execute também
`POKER.bat` → **[5] Preflight banca** em uma árvore Git limpa.

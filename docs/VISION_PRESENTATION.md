# Contrato de apresentação do reconhecimento de imagem

O fluxo operacional iniciado pelo `.bat` é `/?view=capture`: um workspace de página inteira,
não um modal. O operador confirma a autorização do parceiro, escolhe **Janela** no seletor nativo,
confere a prévia e só então inicia a análise. Tela inteira e guia são bloqueadas; nenhum quadro é
enviado antes da confirmação. A escolha não pode ser automatizada silenciosamente por restrição
de segurança da Web. O modal `/?view=copilot` permanece para revisão manual pós-jogo.

## Objetivo

A interface apresenta cada tentativa de reconhecimento como evidência operacional, não
como prova de desempenho científico. A mesma visão é usada no upload pós-jogo e na
captura supervisionada.

## Fonte de cada campo

| Campo exibido | Fonte | O que pode afirmar |
|---|---|---|
| Estado detectado | `FromImageResult.detected` | Proposta daquela imagem: cartas, pote, jogadores, posição e stacks |
| Motor | `FromImageResult.engine` | Qual caminho respondeu (`F1`, `F2`, `F3` ou desconhecido) |
| Confiança reportada | `detected.confidence` | Sinal interno de uma tentativa, somente quando finito e em `[0,1]` |
| Abstenção | `sanity.ok === false` | O gate bloqueou a decisão |
| Motivos/avisos | `sanity.problems` / `sanity.warnings` | Diagnóstico estruturado devolvido pelo backend |
| Latência da chamada | relógio monotônico do navegador ao redor de `api.fromImage` | Tempo navegador → backend → resposta daquela chamada |
| Decisão | `decision` | Não exibida durante a captura ao vivo; revisão estratégica é pós-jogo |

## Linguagem proibida sem nova evidência

- Não chamar confiança de acurácia, probabilidade de acerto ou calibração.
- Não transformar uma captura, screenshot sem gabarito ou latência isolada em benchmark.
- Não afirmar generalização, superioridade, produção ou estado da arte.
- Não esconder abstenção, motivo de falha, motor desconhecido ou valor inválido.
- Não comparar F1/F2/F3 sem executar o mesmo conjunto externo, rotulado e versionado.

O painel informa explicitamente que confiança é um sinal interno e que a latência é uma
observação individual, não benchmark. Confiança inválida aparece como `Indisponível`; uma
abstenção sem `problems` recebe uma mensagem fail-closed, em vez de um motivo inventado.

## Evidência necessária para uma comparação competitiva

Uma futura tabela de modelos só pode ser publicada após receipt imutável contendo dataset
externo licenciado, split sem vazamento, hashes, definição de exact-state/campo, cobertura,
taxa de abstenção, risco seletivo, calibração, latência por percentis, hardware, warm-up,
versões e intervalos de confiança. Resultados sintéticos devem permanecer separados dos
screenshots reais.

Até esse receipt existir, a interface compara apenas **estado operacional da tentativa**:
detectou o quê, com qual sinal interno, quanto a chamada demorou e por que decidiu ou se
absteve. Consulte também o
[`MODEL_CARD_POKER_VISION.md`](../backend/models/MODEL_CARD_POKER_VISION.md).

## Testes executáveis

- `VisionDiagnostics.test.tsx`: estado, motor, confiança, latência, abstinência, motivos,
  avisos, limites de linguagem e valores inválidos.
- `CopilotScreen.test.tsx`: integração do upload e limite de 5 MB coerente com o backend.
- `LiveCopilotScreen.test.tsx`: consentimento, confirmação sem upload antecipado, bloqueio de
  tela/guia, recusa de permissão, término da track, sessão remota e leitura periódica.

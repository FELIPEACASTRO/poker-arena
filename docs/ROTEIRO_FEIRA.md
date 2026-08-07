# Roteiro de demonstração — Poker Arena

Este roteiro descreve o snapshot revisado em 2026-07-17. Antes de cada demonstração,
confirme o estado no checkout atual. Números de experimentos antigos não devem ser
apresentados como resultado vigente sem reexecução ligada a hashes de código, dados e modelo.
O diferencial demonstrável é a combinação de motor auditável, bots comparáveis, explicações
instrumentais e abstenção explícita da visão — não uma alegação de GTO ou superioridade humana.

## Antes de começar

1. Rode a opção **[4] Validar** do launcher e guarde o relatório desta execução.
2. Inicie a aplicação e confira `http://127.0.0.1:8000/health` e `/ready`.
3. Abra `http://localhost:5173` e o Swagger ao vivo em
   `http://127.0.0.1:8000/docs`.
4. Consulte `/levels`: o Expert só pode ser escolhido quando o ONNX compatível está
   disponível.

Se qualquer gate falhar, apresente a falha como resultado; não substitua o relatório por uma
contagem antiga de testes.

## Demonstração sugerida (5 minutos)

### 1. Enquadramento

Crie uma mesa sem dinheiro real. Explique que o projeto estuda decisão sob informação
imperfeita, engenharia de software e visão computacional. A aplicação é educacional e não
deve orientar apostas ou decisões financeiras.

### 2. Modo Laboratório

Monte uma mesa com os níveis retornados por `/levels` e avance algumas jogadas. Mostre que:

- Random, Heuristic, Monte Carlo e Adaptive implementam estratégias diferentes; quando
  `/levels` também expuser o Expert, ele usa a política ONNX instalada;
- o painel exibe sinais calculados por cada implementação, não pensamentos humanos nem prova
  de optimalidade; e
- MDF e fold equity são referências didáticas com hipóteses restritas, especialmente úteis
  em spots heads-up/river, não uma solução GTO geral para potes multiway.

### 3. Estatísticas com tamanho de amostra

Mostre VPIP, PFR, WTSD e agressão, sempre junto do número de mãos. Valores iniciais são
instáveis e não autorizam frases como “o Expert vence a maioria dos showdowns”. O alerta de
possível tilt é uma heurística de mudança de agressão após uma perda; não é diagnóstico
psicológico.

### 4. Copiloto e visão com abstenção

No Copiloto, revise um spot descrito ou um histórico PHH. Se usar uma screenshot, destaque o
comportamento correto: o pipeline propõe um estado, valida estrutura/confiança e **abstém**
quando a evidência é insuficiente. O detector instalado não tem benchmark real abrangente e
não lê “qualquer interface”. O fallback VLM remoto permanece desligado salvo opt-in do
operador.

### 5. Auditoria e referência externa

Abra a partida empacotada rotulada como Pluribus. Ela é uma conversão de mãos públicas do
PHH Dataset, atribuída a `uoftcprg/phh-dataset` (CC BY 4.0); não foi gerada pelo Expert deste
projeto. Use-a para mostrar replay e proveniência, não para afirmar que o modelo local tem a
força ou a arquitetura de Pluribus.

### 6. Fecho científico

Abra os model cards em `backend/models/`. Diga claramente:

- o Expert instalado é uma política ONNX experimental de 121 features e cinco ações;
- sua linhagem, licença do peso e métricas independentes ainda não estão resolvidas;
- resultados históricos de cross-play foram preservados, mas não confirmados nesta auditoria;
- datasets novos precisam de manifesto, licença, hash e splits sem vazamento; e
- uma promoção futura exige seeds independentes, confrontos pareados e intervalos de
  confiança pré-registrados.

Isso demonstra método científico de forma mais forte que uma promessa não verificável: o
sistema registra limites e deixa de decidir quando o gate não passa.

## Fatos técnicos seguros para citar

| Tema | Evidência no pacote |
|---|---|
| Mesa | Texas Hold'em No-Limit, de 2 a 9 jogadores |
| Regras | testes determinísticos/propriedade e cenários diferenciais contra PokerKit |
| Embaralhamento | `SystemRandom` quando não há seed explícita; seeds existem para reprodução |
| Expert | ONNX `obs (batch,121)` → `logits (batch,5)`; não é solver/GTO comprovado |
| Visão | YOLO11n experimental; gate fail-closed; sem generalização real demonstrada |
| Opponent model | priors neutros Beta(1,1), atualizados apenas por observações da sessão |
| API | FastAPI REST + WebSocket, OpenAPI/Swagger e projeto Insomnia gerados do app |

Não cite uma quantidade fixa de testes: ela muda com a suíte. Use apenas a saída da validação
executada no mesmo checkout que está sendo demonstrado.

## FAQ da banca

- **“É GTO?”** — Não. Há receitas didáticas de CFR/NFSP restritas a jogos pequenos; o
  Expert NLHE é uma política experimental que precisa de novo cross-play ligado ao hash do
  checkpoint. Os registros históricos não constituem exploitability válida nem validação
  atual.
- **“Como a IA aprende?”** — Os notebooks contêm receitas de CFR, NFSP e PPO, mas os pesos
  instalados não carregam manifesto suficiente para atribuir com segurança uma receita de
  treino específica.
- **“A IA lê qualquer mesa?”** — Não. O detector atual falhou no exemplo real documentado
  e o gate deve abster; um corpus real independente ainda é necessário.
- **“Ela conhece o humano típico?”** — Não no runtime atual. O modelo de oponente começa
  neutro e aprende estatísticas desta sessão; os priors antigos foram removidos por viés no
  pipeline de dados.
- **“Como se mede melhoria?”** — Com cross-play pareado, rotação de assentos, múltiplas
  seeds e intervalos de confiança. Concordância com solver ou uma única seed não basta.
- **“Qual a arquitetura?”** — motor Python, camada de aplicação, API FastAPI e frontend
  React/TypeScript, com contratos OpenAPI e WebSocket.

## Plano B

- Se a aplicação não abrir, pare e reinicie pelo launcher e consulte `/ready`.
- Se o Expert não aparecer, demonstre os níveis realmente retornados por `/levels` e o model
  card; não force o carregamento.
- Se a visão abster, mantenha o resultado: isso é o gate funcionando.
- Sem internet, backend/frontend e Swagger offline podem rodar localmente, mas instalação de
  dependências, VLM remoto e downloads de modelos/datasets não são recursos offline.

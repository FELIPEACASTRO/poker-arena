# Poker Arena — ML / Pesquisa

Experimentos de treino e avaliação dos agentes. O texto dentro de notebooks antigos também
pode registrar hipóteses e resultados da época; ele não substitui este inventário nem os
model cards atuais. Notebooks e saídas históricas não são,
por si só, prova científica: a promoção exige manifesto de dados/código/checkpoint,
hashes, splits sem leakage, múltiplas seeds e benchmark independente. O backend serve
somente artefatos ONNX que passam pelo contrato; veja `backend/models/`.

O perfil competitivo `ci-local-v1` não é um modelo promovido nem um artefato desta pasta:
é um resumo determinístico de eventos da sessão, com Beta/Wilson/EWMA e abstenção, exposto
somente para leitura. Ele não altera bots nem substitui os gates de ML abaixo.

## Gate externo de visão

O gate executável está em `backend/poker_arena/ml/external_validation.py`. Ele
usa o runner F2 real e exige holdout externo, anotação independente,
near-duplicate check, exact-state, IC Wilson, falso aceite, ECE/Brier, latência
e subgrupos. Consulte `docs/ml/EXTERNAL_VALIDATION_STATUS_20260718.md`: uma única
tela rotulada é diagnóstico, não evidência de generalização.

## Notebooks

| Notebook | O que faz | Onde rodar |
|---|---|---|
| `notebooks/01_kuhn_cfr_single_cell.ipynb` ⭐ | Demonstração didática de CFR em jogos pequenos e gráfico de convergência. Resultados só valem para o jogo/configuração executados. | Colab (CPU) |
| `notebooks/01_kuhn_cfr_convergence.ipynb` | Variante comentada da demonstração de CFR; não prova optimalidade no motor NLHE. | Colab (CPU) |
| `notebooks/02_nfsp_leduc_single_cell.ipynb` 🧠 | Demonstração NFSP/OpenSpiel em Leduc. Exploitability de Leduc não transfere automaticamente para o NLHE customizado. | Colab (CPU; GPU opcional) |
| `notebooks/03_train_ppo_selfplay.ipynb` 🏋️ | **Arquivado e bloqueado no início da execução.** A receita PPO v1 perde histórico e estado por assento; permanece somente como registro, não como caminho de treino atual. | Não executar |
| `notebooks/04_qa_testes.ipynb` 🧪 | Harness histórico de QA no Colab. É complementar: o gate atual é `assets/validar.ps1` no checkout, com dependências e artefatos reais. | Colab (CPU) |
| `notebooks/05_pokerbench_warmstart.ipynb` 🧠🎯 | **Arquivado e bloqueado no início da execução.** A concordância histórica com PokerBench não previu força no cross-play; mantido apenas para rastrear a hipótese reprovada. | Não executar |
| `notebooks/06_selfplay_bb100.ipynb` | **Arquivado e bloqueado no início da execução.** Publicava o canônico sem gate independente e não possui cadeia imutável até os pesos instalados. | Não executar |
| `notebooks/07_expert_v2_populacao.ipynb` 🧬🏆 | Receita revisada de PPO populacional: PHH v3 pinado, amostragem em 27 estratos, manifesto/hashes, gate pareado e publicação de candidato opt-in. Ainda não foi reexecutada nesta auditoria; não sustenta promoção nem nova métrica enquanto isso. | CPU primeiro; L4 apenas após profiling |
| `notebooks/08_vision_agnostic.ipynb` 👁️🧠 | Candidato de visão **sintético** com domain randomization e **YOLO11n**. O held-out mede apenas estilos do gerador; não prova generalização real. Publicação é opt-in e o artefato exige validação cega por cliente/sessão/tema antes de promoção. | **Colab/L4**, após aprovar licença e protocolo |
| `notebooks/09_vision_finetune.ipynb` | Pipeline SIM→REAL: baseline HF pinado, pares estritos, ≥4 grupos, seed, gates de mAP e regressão por classe, candidato por SHA e publicação opt-in. Mesmo com gate interno, exact-state, calibração, latência e paridade ONNX continuam bloqueando promoção. | L4 após corpus autorizado |
| `notebooks/10_vlm_server_colab.ipynb` | Protótipo de servidor VLM remoto. O backend atribui confiança zero à proposta sem calibração; túnel público introduz privacidade, custo e disponibilidade. | GPU compatível, só em pesquisa autorizada |
| `notebooks/11_card_reader_cnn.ipynb` | Receita para classificador rank/naipe sintético. `card_reader.onnx` não está instalado e não há benchmark real ligado a um hash. | CPU/GPU após protocolo real |

### Como rodar (Colab)
1. Abrir o `.ipynb` no Google Colab.
2. `Runtime → Run all`.
3. Inspecionar o gate e as saídas declaradas pelo notebook executado. Não use “Run all” nos
   notebooks 03, 05 ou 06: eles abortam intencionalmente por estarem arquivados.

## Autenticação no Colab (Secrets)

Quando um notebook realmente precisar de acesso privado, injete o segredo pelo cofre
do ambiente; nunca grave credenciais no notebook, URL Git, log ou manifesto. A
auditoria atual não encontrou ingestão executável via API/SDK do Kaggle nos notebooks.
Existe um coletor público metadata-only em `backend/scripts/catalog_search_receipt.py`,
que deliberadamente não usa credenciais nem baixa dados. O notebook 07 consulta
GitHub/Zenodo; o 08 gera dados locais; e 07–09 só podem publicar candidatos no HF
mediante opt-in explícito.

Exemplo para um futuro job que realmente use os dois serviços:

```python
import os
from google.colab import userdata

os.environ["HF_TOKEN"]        = userdata.get("HF_TOKEN")
os.environ["KAGGLE_USERNAME"] = userdata.get("KAGGLE_USERNAME")
os.environ["KAGGLE_KEY"]      = userdata.get("KAGGLE_KEY")
print("Auth OK (HF + Kaggle)")  # nao imprime valores
```

- `huggingface_hub` lê **`HF_TOKEN`** automaticamente (prefira-o ao `HF_KEY`).
- `kaggle` / `kagglehub` leem **`KAGGLE_USERNAME` + `KAGGLE_KEY`** automaticamente.
- Notebooks auto-contidos não devem solicitar nem carregar credenciais.
- Presença de `kaggle.json` ou variáveis de ambiente não constitui integração nem
  evidência de que um dataset foi baixado.
- **Segurança:** nunca dar `print()` no valor de um secret; só usar via `os.environ`.

## Stack experimental e limites
- **OpenSpiel** (Apache-2.0) — CFR/MCCFR/NFSP/Deep CFR em jogos suportados; não
  fornece exploitability válida para o NLHE 6-max customizado sem um adaptador e
  abstração formalmente verificados.
- **stable-baselines3** — implementação usada pelas receitas PPO; isso não converte o
  simulador customizado em jogo OpenSpiel nem prova equivalência com Deep CFR.
- Hardware: CPU para parsing/CFR pequeno/geração sequencial; L4 como primeira GPU para
  behavioral cloning ou visão. A100/H100 só após profiling demonstrar ganho por dólar.

## Backlog de pesquisa (não implementado)

- adaptador OpenSpiel separado para Kuhn/Leduc/HU com contratos de observação e ação;
- PSRO/cross-play com matriz de payoffs, rotação de assentos e negócios pareados;
- benchmark de visão real por cliente/sessão/tema, calibração e curva risco-cobertura; e
- comparação PP-OCRv4/v6 e detectores permissivos somente após revisão de licença.

## Registro histórico do experimento Expert v2 (não reproduzido nesta auditoria)

Os números abaixo são registros anteriores, não evidência independente atual. Os pesos
instalados não possuem manifesto de treino que ligue dataset, código e checkpoint aos
hashes atuais; portanto as alegações de promoção precisam ser reexecutadas.

A jornada completa, medida em cada passo (commits `7bad5a6` → `ba83346`):

**1. Análise devastadora do v1** (bb/100, sondas de exploração, 3k+ mãos/confronto):
o registro indicava ganhos contra parte do painel, mas derrota contra Monte Carlo no
protocolo posterior (−47 bb/100), além de ineficiências: fold-to-bet 70–78%, sangria de
blinds −17 bb/100 e margem fina vs NitExploiter (+22). Remendos de inferência
(guarda de equity) foram **testados e REPROVADOS** em pareado (−357 amplo / −84
restrito) — a política treinada era coerente; o caminho era retreinar.

**2. Notebook 07 "População"**: o registro dizia usar 250k mãos do PHH. A auditoria
descobriu que a seleção `setdefault` retinha apenas o primeiro estrato e que checks
contaminavam a agressividade. O notebook foi refeito contra PHH v3 pinado (Zenodo
17136841, CC BY 4.0), com recibo de governança específico para PHH, amostragem
determinística entre 27 estratos, hashes e comparação baseline/candidato governada. O
manifesto genérico v1 não valida esse corpus multijogador; o notebook ainda precisa ser
reexecutado, sem reutilizar resultados antigos, antes de sustentar qualquer conclusão. As
21,6 milhões de mãos humanas são logs históricos de 1–23 de julho de 2009: opponent
modelling contemporâneo exige holdout moderno, autorizado, externo e temporal.

**3. O gate REPROVOU a 1ª tentativa** (e isso é o sistema funcionando): o v2.0
melhorou heur/mc/station (+150 a +190) mas piorou vs maniac (−217, consistente em
6 seeds) e nit (−27). Causas: maniac/nit entravam no pool só por sorteio, e o
"melhor checkpoint" era selecionado só por vs-heurístico (régua ≠ gate).

**4. v3 = correções guiadas pelos números**: maniac+nit GARANTIDOS em toda rotação
do pool + seleção do checkpoint pela RÉGUA COMPOSTA (heur+maniac+nit) + 2× passos.

**5. O registro marcou o gate como aprovado e melhor em 6/6 confrontos:**

| Confronto | v1 | v2 | Δ |
|---|---|---|---|
| random | +422 | +656 | +235 |
| heuristic | +82 | +395 | +313 |
| montecarlo | −47 | −6 | +41 |
| maniac | +476 | +655 | +179 |
| station | +296 | +700 | +404 |
| nit | +19 | +48 | +29 |
| **SOMA** | **+1246** | **+2447** | **+1201** |

**6. O registro chamou de “verificação independente”** um run local com 5 seeds:
heur +8 · maniac +160 · nit +24. Isso teria motivado a promoção na época, mas o artefato
instalado não está ligado ao run por manifesto e a promoção não foi confirmada nesta
auditoria. O backup local também não prova parentesco entre checkpoints. Os antigos priors
0,70/0,46 foram removidos do
runtime porque derivavam do pipeline enviesado. O `OpponentModel` agora usa Beta(1,1)
neutro e fraco até existir uma estimativa externa, representativa e auditável.

## Roadmap: Expert v3 (trabalho futuro)

O gate novo falha fechado sem pré-registro externo que fixe MDE e margem de
não inferioridade: são 30 blocos pareados, FWER Bonferroni e um gate de precisão pelo
half-width do IC. Os números históricos abaixo não satisfazem retroativamente esse contrato.

1. **Features novas no encoder** (quebra o contrato v1, exige treino do zero):
   histórico tokenizado de ações/tamanhos/ruas, agressor e full raise, estado/stack por
   assento, stack efetivo, SPR, pot/side pots e máscara legal derivada do motor. Medir
   colisões entre histórias estrategicamente distintas antes de treinar.
2. **PPO como controle obrigatório**, congelado e avaliado por cross-play pareado,
   rotação de assentos, duplicate deals, seeds independentes e IC. Current-policy,
   league/checkpoint e entropia entram como ablações, não defaults copiados.
3. **Recompensa de roubo/defesa de blind** — a sangria estrutural (−17 bb/100 ao
   foldar) ainda é o custo fixo a atacar.
4. **Pool com clones neurais** (behavior cloning das mãos com cartas reveladas) —
   os perfis fish/reg atuais são paramétricos; clones aprendidos são o passo além.
5. **PSRO/SP-PSRO e opponent head somente como challengers pós-PPO**, primeiro em
   Kuhn/Leduc/OpenSpiel com exploitability exata. Em NLHE, medir robustez/cross-play e
   nunca chamar a proxy de GTO.
6. **Régua composta ampliada** no treino (incluir montecarlo/station no score do
   checkpoint, se o custo de avaliação couber).

# Poker Arena — ML / Pesquisa

Treino e prova científica dos cérebros de IA. **Roda na nuvem** (Colab Pro+ /
HF Jobs / Kaggle), não localmente — o Python 3.14 local não tem wheels de
OpenSpiel/PyTorch. O backend só baixa o checkpoint pronto.

## Notebooks

| Notebook | O que faz | Onde rodar |
|---|---|---|
| `notebooks/01_kuhn_cfr_single_cell.ipynb` ⭐ | **Célula única** — instala + treina CFR (Kuhn+Leduc) + plota + imprime política. **Logs amigáveis estilo _Use a Cabeça_** (boxes, "Não Tem Pergunta Idiota", barra da brecha encolhendo, marcos comemorados). | Colab (CPU, minutos) |
| `notebooks/01_kuhn_cfr_convergence.ipynb` | Mesma coisa, com as explicações didáticas como comentários (célula única). | Colab (CPU, minutos) |
| `notebooks/02_nfsp_leduc_single_cell.ipynb` 🧠 | **NFSP** — a primeira IA que *aprende* por rede neural (self-play). A brecha cai conforme ela aprende. Fiel ao exemplo oficial do OpenSpiel. | Colab (CPU/GPU, minutos) |
| `notebooks/03_train_ppo_selfplay.ipynb` 🏋️ | **Treina o nível Expert** — PPO self-play sobre o NOSSO motor (6-max No-Limit). Aprende padrões e blefe; cada checkpoint = um nível. Exporta ONNX + publica no HF. | **Colab Pro+** (GPU, horas) |
| `notebooks/04_qa_testes.ipynb` 🧪 | **QA completo** — contextualiza a solução pro time de QA e roda todos os tipos de teste da literatura (regressão+cobertura, teste de mesa, propriedade, valor-limite, negativo, segurança, determinismo, integração, desempenho). | Colab (CPU, minutos) |
| `notebooks/05_pokerbench_warmstart.ipynb` 🧠🎯 | **Warm-start + benchmark GTO** (PokerBench). ⚠️ **Descontinuado**: auditoria impartial mostrou que a concordância com o solver **não prevê força** (o modelo perdia −350 bb/100 no cross-play). Mantido só como histórico. | — |
| `notebooks/06_selfplay_bb100.ipynb` | Self-play **puro** medido por bb/100. Funciona, mas a análise devastadora mostrou o limite: sem diversidade de oponentes, sobram margens finas. **Superado pelo 07.** | Colab Pro+ (GPU, horas) |
| `notebooks/07_expert_v2_populacao.ipynb` 🧬🏆 | **Treino EFETIVO (use este)** — baixa mãos REAIS (Zenodo 10796885, 21,6M, CC BY 4.0) → **priors do Adaptativo** + perfis humanos calibrados (fish/reg); treina o Expert v2 contra **POOL diverso** (snapshot + regras + sondas maniac/station/nit + humanos, rotacionados); **gate devastador pareado** — só promove no HF se vencer o v1 sem degradar nenhum confronto. | **Colab Pro+** (A100, horas) |

### Como rodar (Colab)
1. Abrir o `.ipynb` no Google Colab.
2. `Runtime → Run all`.
3. Saídas: `kuhn_cfr_convergence.png`, `leduc_cfr_convergence.png` + a política aprendida.

## Autenticação no Colab (Secrets)

As credenciais já estão nos **Secrets do Colab** (🔑), com acesso ao notebook ligado:
`HF_TOKEN`, `HF_KEY`, `KAGGLE_USERNAME`, `KAGGLE_KEY`. Os notebooks de treino (que
baixam datasets do Kaggle e publicam checkpoints no HF Hub) usam este bloco —
**sem nunca imprimir as chaves**:

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
- O notebook 01 (Kuhn/Leduc) **não** precisa disso — é auto-contido. Vale para os
  próximos (NFSP/Deep CFR/PPO), que puxam dados e publicam modelos.
- **Segurança:** nunca dar `print()` no valor de um secret; só usar via `os.environ`.

## Stack (verificada)
- **OpenSpiel** (Apache-2.0) — CFR, MCCFR, **NFSP**, **Deep CFR**, exploitability.
- **stable-baselines3** — **PPO self-play** (alternativa à Deep CFR; paper 2502.08938).
- Treino pesado: **Colab Pro+ (A100, 24h, background)**; modelo final → **HF Hub**.

## Próximos notebooks (backlog)
- `02_nfsp_leduc.ipynb` — NFSP em Leduc (self-play que aprende).
- `03_deep_cfr_leduc.ipynb` — Deep CFR (rede neural) + exploitability.
- `04_ppo_selfplay.ipynb` — PPO self-play (stable-baselines3).
- `05_crossplay_matrix.ipynb` — matriz NFSP × Deep CFR × PPO × baselines (avaliação 6-max).

## ✅ Expert v2 — ENTREGUE (jul/2026) — o registro histórico do método

A jornada completa, medida em cada passo (commits `7bad5a6` → `ba83346`):

**1. Análise devastadora do v1** (bb/100, sondas de exploração, 3k+ mãos/confronto):
vencia tudo, mas com ineficiências: fold-to-bet 70–78%, sangria de blinds −17 bb/100,
margens finas vs NitExploiter (+22) e campo montecarlo (+71). Remendos de inferência
(guarda de equity) foram **testados e REPROVADOS** em pareado (−357 amplo / −84
restrito) — a política treinada era coerente; o caminho era retreinar.

**2. Notebook 07 "População"**: 250k mãos REAIS de NLHE (Zenodo 10796885, CC BY 4.0,
via uoftcprg/phh-dataset) → priors populacionais + perfis humanos calibrados
(fish/reg) → treino PPO contra POOL diverso → gate devastador pareado.

**3. O gate REPROVOU a 1ª tentativa** (e isso é o sistema funcionando): o v2.0
melhorou heur/mc/station (+150 a +190) mas piorou vs maniac (−217, consistente em
6 seeds) e nit (−27). Causas: maniac/nit entravam no pool só por sorteio, e o
"melhor checkpoint" era selecionado só por vs-heurístico (régua ≠ gate).

**4. v3 = correções guiadas pelos números**: maniac+nit GARANTIDOS em toda rotação
do pool + seleção do checkpoint pela RÉGUA COMPOSTA (heur+maniac+nit) + 2× passos.

**5. Gate APROVADO com dominância — melhor em TODOS os confrontos:**

| Confronto | v1 | v2 | Δ |
|---|---|---|---|
| random | +422 | +656 | +235 |
| heuristic | +82 | +395 | +313 |
| montecarlo | −47 | −6 | +41 |
| maniac | +476 | +655 | +179 |
| station | +296 | +700 | +404 |
| nit | +19 | +48 | +29 |
| **SOMA** | **+1246** | **+2447** | **+1201** |

**6. Verificação independente** (5 seeds fora do gate, local): heur +8 · maniac +160
· nit +24 → promoção confirmada. Modelo em produção no backend; v1 preservado como
backup local. **Bônus:** os priors reais (fold-to-bet 0.70, agressão 0.46; medianas
de 3.588 jogadores) entraram no `OpponentModel` do Adaptativo (suavização bayesiana).

## Roadmap: Expert v3 (trabalho futuro)

1. **Features novas no encoder** (quebra o contrato v1, exige treino do zero):
   histórico de ações da mão (nº de raises na rua, agressor), stack efetivo em bb,
   equity Monte Carlo como feature.
2. **Recompensa de roubo/defesa de blind** — a sangria estrutural (−17 bb/100 ao
   foldar) ainda é o custo fixo a atacar.
3. **Pool com clones neurais** (behavior cloning das mãos com cartas reveladas) —
   os perfis fish/reg atuais são paramétricos; clones aprendidos são o passo além.
4. **Régua composta ampliada** no treino (incluir montecarlo/station no score do
   checkpoint, se o custo de avaliação couber).

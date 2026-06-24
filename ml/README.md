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

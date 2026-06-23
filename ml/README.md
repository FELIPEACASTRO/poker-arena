# Poker Arena — ML / Pesquisa

Treino e prova científica dos cérebros de IA. **Roda na nuvem** (Colab Pro+ /
HF Jobs / Kaggle), não localmente — o Python 3.14 local não tem wheels de
OpenSpiel/PyTorch. O backend só baixa o checkpoint pronto.

## Notebooks

| Notebook | O que faz | Onde rodar |
|---|---|---|
| `notebooks/01_kuhn_cfr_convergence.ipynb` | CFR converge ao Nash no Kuhn + Leduc (exploitability → 0, com gráfico). **Evidência científica nº 1.** | Colab (CPU, minutos) |

### Como rodar (Colab)
1. Abrir o `.ipynb` no Google Colab.
2. `Runtime → Run all`.
3. Saídas: `kuhn_cfr_convergence.png`, `leduc_cfr_convergence.png` + a política aprendida.

## Stack (verificada)
- **OpenSpiel** (Apache-2.0) — CFR, MCCFR, **NFSP**, **Deep CFR**, exploitability.
- **stable-baselines3** — **PPO self-play** (alternativa à Deep CFR; paper 2502.08938).
- Treino pesado: **Colab Pro+ (A100, 24h, background)**; modelo final → **HF Hub**.

## Próximos notebooks (backlog)
- `02_nfsp_leduc.ipynb` — NFSP em Leduc (self-play que aprende).
- `03_deep_cfr_leduc.ipynb` — Deep CFR (rede neural) + exploitability.
- `04_ppo_selfplay.ipynb` — PPO self-play (stable-baselines3).
- `05_crossplay_matrix.ipynb` — matriz NFSP × Deep CFR × PPO × baselines (avaliação 6-max).

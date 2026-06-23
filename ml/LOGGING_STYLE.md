# Convenção de Logs — estilo "Use a Cabeça" (Head First)

> **REGRA DO PROJETO:** todos os logs de **qualquer notebook (.ipynb) ou job/script**
> seguem este estilo. Logs ensinam e encantam — nunca são dumps crus de números.

## Princípios (do método Head First)
1. **Tom conversacional** — fale *com* a pessoa ("você vai VER isso acontecer").
2. **Boxes** para separar seções importantes (ASCII, auto-dimensionados).
3. **"Não Tem Pergunta Idiota"** — explique os conceitos-chave em P/R simples.
4. **Indicador visual de progresso que muda ao vivo** (ex.: barra encolhendo).
5. **Marcos comemorados** — "UAU! a brecha furou 0.01 — salto de qualidade!".
6. **Conclusão em linguagem simples** — "O QUE VOCÊ ACABOU DE PROVAR".
7. **Sem jargão cru** — traduza métrica em significado ("brecha" = exploitability).

## Snippet canônico (cole no topo de cada notebook/job)

```python
import math

def box(titulo, linhas):
    largura = max([len(titulo)] + [len(l) for l in linhas])
    print('  +' + '-' * (largura + 2) + '+')
    print('  | ' + titulo.ljust(largura) + ' |')
    print('  +' + '-' * (largura + 2) + '+')
    for l in linhas:
        print('  | ' + l.ljust(largura) + ' |')
    print('  +' + '-' * (largura + 2) + '+')

def comentario(e):
    if e > 0.3:   return 'ainda da pra explorar facil'
    if e > 0.05:  return 'opa, ta ficando esperto...'
    if e > 0.005: return 'quase imbativel!'
    return 'praticamente impossivel de explorar  [imbativel]'

def barra(valor, valor_inicial, alvo=1e-3):
    # barra que ENCOLHE conforme `valor` se aproxima de `alvo` (escala log)
    lo, hi = math.log10(alvo), math.log10(max(valor_inicial, alvo) + 1e-12)
    cur = math.log10(max(valor, 1e-9))
    frac = max(0.0, min(1.0, (cur - lo) / (hi - lo + 1e-12)))
    n = int(frac * 20)
    return '[' + '#' * n + '.' * (20 - n) + ']'

def marcos_check(valor, marcos, niveis=(0.1, 0.01, 0.001)):
    # imprime celebracao quando `valor` cruza um nivel pela primeira vez
    for m in niveis:
        if not marcos.get(m) and valor < m:
            marcos[m] = True
            print(f'         >>> UAU! a brecha furou {m} - salto de qualidade!')
```

## Para jobs (sem notebook)
Mesma regra: heartbeats e progresso em tom amigável, marcos e um box de fechamento
com o veredito. Vale para scripts de treino (HF Jobs/Colab/Kaggle) e harness de CV.

## Referência viva
Exemplo aplicado: `ml/notebooks/01_kuhn_cfr_single_cell.ipynb` e
`01_kuhn_cfr_convergence.ipynb`.

# Convenção de logs didáticos e auditáveis

Esta é uma recomendação de apresentação para notebooks e jobs; não há linter que garanta
adesão universal. Linguagem acessível não pode transformar proxy em prova, omitir incerteza
ou chamar uma política de “imbatível”. Todo resultado deve identificar jogo, métrica, seed,
split, versão de dados/código e se a execução é treino, calibração ou teste.

## Princípios

1. Use tom claro e explique o significado **e o limite** da métrica.
2. Separe configuração, progresso, avisos e veredito em blocos legíveis.
3. Mostre denominador/tamanho de amostra e, quando aplicável, intervalo de confiança.
4. Celebre apenas a conclusão permitida pelo gate pré-registrado.
5. Registre falhas, valores não finitos, artefatos ausentes e publicação bloqueada.
6. Diferencie “convergiu neste jogo pequeno” de “funciona no NLHE do produto”.
7. Nunca imprima tokens, URLs com credenciais, paths privados ou conteúdo sensível.

## Snippet de apresentação

```python
import math


def box(title: str, lines: list[str]) -> None:
    width = max([len(title), *(len(line) for line in lines)])
    print("  +" + "-" * (width + 2) + "+")
    print("  | " + title.ljust(width) + " |")
    print("  +" + "-" * (width + 2) + "+")
    for line in lines:
        print("  | " + line.ljust(width) + " |")
    print("  +" + "-" * (width + 2) + "+")


def metric_comment(value: float, *, game: str) -> str:
    if not math.isfinite(value):
        return "ERRO: valor nao finito; gate reprovado"
    if value > 0.3:
        level = "distante do alvo deste experimento"
    elif value > 0.05:
        level = "melhora observada; ainda material"
    elif value > 0.005:
        level = "pequeno neste jogo/configuracao"
    else:
        level = "abaixo do limiar pre-registrado neste jogo/configuracao"
    return f"{level}; nao extrapolar de {game} para NLHE"


def progress_bar(value: float, initial: float, target: float = 1e-3) -> str:
    lo = math.log10(target)
    hi = math.log10(max(initial, target) + 1e-12)
    cur = math.log10(max(value, 1e-12))
    fraction = max(0.0, min(1.0, (cur - lo) / (hi - lo + 1e-12)))
    count = int(fraction * 20)
    return "[" + "#" * count + "." * (20 - count) + "]"
```

## Fechamento mínimo de um job

O bloco final deve registrar:

- status `PASS`, `FAIL` ou `INCOMPLETE` e a regra que o produziu;
- hashes/revisions de dataset, código e checkpoint;
- seeds, número de unidades independentes e métricas com incerteza;
- diferenças entre o runtime de avaliação e o alvo de deploy; e
- destino do artefato. Publicação deve ser opt-in e ocorrer somente após `PASS`.

Kaggle, Hugging Face, Colab ou Modal são ambientes possíveis, não evidência de que uma
integração foi executada nem de que os resultados são reproduzíveis.

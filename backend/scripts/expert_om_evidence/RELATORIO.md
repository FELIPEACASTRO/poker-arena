# Experimento — Expert opponent-aware vs GTO puro

**Pergunta:** dar ao Expert (política neural treinada, ONNX, joga estratégia MISTA ≈ GTO)
a técnica do AdaptiveBot (modelar `fold_to_bet` do oponente e desviar a política pra
explorar) o deixa **mais forte**?

**Hipótese (pré-registrada):** cética (~50/50). O projeto já tinha um precedente: o
*equity guard* — outro remendo de inferência sobre a política treinada — foi **medido**
e **reprovado** (−84 a −357 bb/100).

**Veredito medido: REPROVA (ambas as variantes).** O overlay de exploração **não** torna
o Expert melhor — confirma a hipótese cética e o precedente do equity guard.

---

## Metodologia (pré-registrada ANTES de ver o resultado, commit `d407211`)

Desenho por 4 agentes (workflow), fixado antes de rodar (anti-p-hacking):

- **Pareado por baralho:** baseline (Expert puro) e OM (Expert+exploração) jogam os
  MESMOS seeds; a métrica é a **diferença por mão** dᵢ (mata a variância de carta).
- **Duas variantes:** **V1** (tilt uniforme nas probs, fiel à fórmula linear do
  AdaptiveBot) e **V2** (separa BLEFE de VALOR — modula o tilt pela massa que a rede já
  dá a cada ação; a correção que a fórmula linear não faz).
- **Calibração × Teste** com vilões **E** seeds **disjuntos** (mede generalização, não
  overfitting): k escolhido só na calibração (vs over-folder), congelado, testado no
  held-out.
- **IC 95% por bootstrap pareado** (cauda pesada do poker). **Taxa de decisões alteradas
  pelo warp** logada. **Sanity:** k=0 ⇒ OM bit-idêntico ao baseline (verificado).
- **Critério de promoção (fixado antes):** promove SSE (1) ganha no sub-pool EXPLORÁVEL
  (IC>0 em ≥2/3) **E** (2) é NÃO-INFERIOR no ROBUSTO (IC sup > −5 bb/100) **E** (3) sem
  ganho grande vs random. Senão: REPROVA e mantém OFF, como o equity guard.

*Nota:* `montecarlo` foi dropado do pool robusto por custo (5 bots simulando equity por
decisão ⇒ ~10× mais lento). `heuristic` (benchmark canônico do equity guard) e
`expert_mirror` (self-play) servem de juízes robustos. N=4000 teste / 2000 calibração.

---

## Resultados (bb/100, pareado, IC95%)

### V1 — tilt uniforme (fiel/ingênua do AdaptiveBot), k=4.0
| Vilão | Grupo | base | OM | Δ (IC95%) | veredito |
|---|---|---|---|---|---|
| overfolder | explorável | −83.2 | −76.4 | **+6.8** [−15.7,+29.4] | não-sig |
| station | explorável | +702.4 | +452.8 | **−249.6** [−401,−106] | **PERDA sig** |
| maniac | explorável | +585.2 | +423.4 | **−161.8** [−311,−19] | **PERDA sig** |
| heuristic | robusto | +401.4 | +329.0 | −72.4 [−198,+49] | não-sig (−) |
| expert_mirror | robusto | +127.0 | +32.2 | **−94.8** [−157,−33] | **PERDA sig** |
| random | controle | +600.1 | +541.8 | −58.3 [−215,+97] | não-sig |

**V1 REPROVA:** perde significativamente no explorável (station, maniac) **e** no robusto
(mirror). O tilt uniforme vira **maniac contra quem paga** (station −249) e **abre o
próprio jogo** contra o espelho (−94). É o defeito exato da fórmula linear, medido.

### V2 — separa blefe de valor (corrigida), k=4.0
| Vilão | Grupo | base | OM | Δ (IC95%) | veredito |
|---|---|---|---|---|---|
| overfolder | explorável | −83.2 | −78.7 | +4.5 [−14.8,+24.1] | não-sig |
| station | explorável | +702.4 | +695.8 | −6.6 [−81.7,+68.4] | não-sig (**corrigiu** V1) |
| maniac | explorável | +585.2 | +494.4 | **−90.7** [−168,−18] | **PERDA sig** |
| heuristic | robusto | +401.4 | +363.3 | −38.1 [−106,+29] | não-sig |
| expert_mirror | robusto | +127.0 | +71.3 | −55.7 [−110,+0.9] | não-sig (borderline) |
| random | controle | +600.1 | +538.6 | −61.5 [−215,+88] | não-sig |

**V2 REPROVA:** a correção **elimina o desastre da station** (−249 → −6.6, não-sig) e é
não-inferior no robusto, mas **não GANHA em nenhum explorável de forma significativa** (o
melhor é +4.5, IC cruza 0) e ainda **perde vs maniac**. Não cruza a barra de promoção.

---

## Mecanismo — POR QUE não ajuda

1. **Taxa de decisões alteradas pelo warp é BAIXA (1–23%; ~1–2% vs o espelho).** O piso
   `min_prob_ratio` + a confiança da política treinada absorvem o desvio: na maioria dos
   spots o overlay é um no-op. A política já é coerente; sobra pouca massa pra desviar.
2. **V1 quebra o equilíbrio e é punida:** somar agressão uniforme com mão fraca = blefar
   contra quem paga (station) e virar previsível pro espelho.
3. **Nem a V2 corrigida ganha:** a exploração que sobrevive à política confiante é pequena,
   e o read linear de `fold_to_bet` não captura o exploit certo vs um agressor (contra o
   maniac o certo é PAGAR mais fino / trapar, não ajustar o próprio blefe).

Mesma lição do *equity guard*: **remendo de inferência sobre a política treinada não a
melhora.**

---

## Conclusão honesta + a caveat que importa

- **O que foi testado e reprovado:** dar ao Expert a exploração do Adaptativo **por
  OVERLAY de inferência**. Não ajuda (V1 piora; V2 é neutra-a-negativa).
- **O que NÃO foi testado:** **RE-TREINAR** a política com as features do oponente na
  ENTRADA + pool de oponentes diverso (o "caminho real" que o próprio `ml_bot.py` aponta).
  O experimento não refuta essa via — só a via do remendo.
- **Veredito mecânico (pré-registrado, aceito como saiu):** REPROVA. Mantém o Expert puro
  (GTO) como default, exatamente como o equity guard ficou OFF.

*(Veredito da revisão adversarial: ver seção abaixo.)*

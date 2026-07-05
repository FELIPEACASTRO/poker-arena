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

## Mecanismo — POR QUE não ajuda (corrigido pela revisão adversarial)

> Minha explicação inicial ("a taxa de alteração baixa PROVA que não há exploit a
> extrair") foi **REFUTADA** pela revisão: ao estender a grade de k até 8, **há exploit
> significativo vs um over-folder puro** (V1 overfolder k=8: **+60 [+23,+98] SIG**), e a
> taxa baixa era **artefato do k capado** (em k=8 a alteração é 34–36%; em k=20, 65–90%),
> não ausência de exploit. A justificativa mudou; o veredito não.

O motivo REAL, mais fundamental:

1. **O trade-off é INTRÍNSECO.** O mesmo botão (k) que faz o over-folder ganhar é
   **monotonicamente acoplado ao desastre** nos outros: em k=8, V1 dá overfolder +60 SIG
   **mas** station −550, maniac −412, robustos negativos. Subir a dose pra capturar o
   exploit só vira o Expert num **maníaco stackeado pelos callers**. Não há k que passe o
   critério (ganhar em ≥2 exploráveis E ser não-inferior nos robustos).
2. **Raiz: 6-max multiway.** Enfrentando aposta há ~4,3 jogadores vivos em média (potes
   4–6-way dominam). "Blefar pra fazer foldar" é um exploit **heads-up mal-aplicado a
   multiway**, e o read **escalar agregado** (`fold_to_bet` do campo, sem contar vivos nem
   por-assento) não distingue os dois casos.
3. **V1 quebra o equilíbrio e é punida** (blefa contra quem paga; vira previsível pro
   espelho). **A V2 corrigida** elimina o desastre da station mas não captura ganho
   significativo em lugar nenhum — e o read linear não captura o exploit certo vs agressor
   (contra o maniac o certo é PAGAR fino/trapar, não ajustar o próprio blefe).

Mesma lição do *equity guard*: **remendo de inferência sobre a política treinada não a
melhora — e aqui, piora com implementação mais forte.**

---

## Conclusão honesta + a caveat que importa

- **O que foi testado e reprovado:** dar ao Expert a exploração do Adaptativo **por
  OVERLAY de inferência**. Não ajuda (V1 piora; V2 é neutra-a-negativa).
- **O que NÃO foi testado:** **RE-TREINAR** a política com as features do oponente na
  ENTRADA + pool de oponentes diverso (o "caminho real" que o próprio `ml_bot.py` aponta).
  O experimento não refuta essa via — só a via do remendo.
- **Veredito mecânico (pré-registrado, aceito como saiu):** REPROVA. Mantém o Expert puro
  (GTO) como default, exatamente como o equity guard ficou OFF.

---

## Revisão adversarial (3 lentes tentaram REFUTAR o REPROVA)

Os três atacantes convergiram: **REPROVA confirmado** (nenhum conseguiu flipar pra
"melhora"). O que sobreviveu e o que caiu:

- **Caiu (justificativa):** "alteração baixa prova ausência de exploit" — FALSO. Estendendo
  k até 8, há exploit SIG vs over-folder puro (+60). Corrigido acima.
- **Sobreviveu (veredito):** nenhum k plausível (1–8, boundary estendido) passa o critério;
  o botão que salva o explorável é acoplado ao desastre nos robustos. O melhor caso
  exploravel (V2 overfolder +4.5) precisaria de **N~75.000 mãos** só pra virar
  significativo mantendo o ponto (N=4000 está 10×+ disso) e, mesmo assim, +4.5 bb/100 é
  trivial enquanto a mesma variante perde −90.7 SIG pro maniac. As PERDAS significativas
  são robustas a N (o IC encolhe **em torno** do mesmo ponto; −249 não migra pra 0).

**Caveat validada (o escopo honesto):** mediu-se **OVERLAY** de inferência sobre vilões
**sintéticos e estáticos** em 6-max. Ficaram **fora do escopo**: (a) **RE-TREINO** com
features de oponente (outra técnica, não um overlay), (b) um exploit **por-assento /
ciente-de-vivos** (o overlay escalar não distingue multiway de heads-up), (c) vilões reais
que re-adaptam — sendo que (c) só **reforça** REPROVA (estático é o cenário mais favorável
ao exploit; humano puniria o desvio).

**Conclusão acionável (juiz):** *não integrar o overlay de exploração ao Expert — não
melhora e machuca vs agressivos; se retomar opponent-awareness, fazer por RE-TREINO com
features por-assento/ciente-de-vivos, que é outra técnica e exige novo pré-registro.*

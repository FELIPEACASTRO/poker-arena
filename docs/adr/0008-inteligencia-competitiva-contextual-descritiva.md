# ADR-0008: inteligência competitiva contextual permanece descritiva

## Status

Aceita.

## Contexto

O modo Laboratório já exibia VPIP, PFR, agressão, WTSD/W$SD e quatro regiões de
posição. Essas taxas não distinguiam oportunidade, papel pré-flop, ordem IP/OOP ou
incerteza. Usar diretamente uma frequência pequena para adaptar a política criaria
risco de overfitting, falsa precisão e maior explorabilidade do próprio agente.

A distribuição é uma demonstração local de mestrado. Ela não deve coletar perfis
externos, fazer datamining nem fornecer assistência em jogo real.

## Decisão

Adicionar um perfil versionado por `player_id`, calculado apenas dos eventos da sessão
local. Cada sinal registra numerador e denominador; expõe média posterior Beta(1,1),
intervalo Wilson 95%, estágio de evidência e abstenção antes de 12 oportunidades.

Os contextos aceitos na versão 1 são: VPIP/PFR global, regional e por posição exata;
RFI/open-raise, limp, isolamento, call/3-bet/4-bet, squeeze, tentativa/defesa de roubo,
blind-versus-blind, fold diante de raise/bet e agressão IP/OOP. Uma EWMA descreve
recência, sem ser chamada de teste causal ou diagnóstico.

O contrato fixa `scope=local_session_only` e
`authority=descriptive_only_no_action_advice`. A camada não é importada pelas políticas
dos bots e não pode escolher uma ação.

## Consequências

### Positivas

- perfis por posição/papel são explicáveis e reproduzíveis;
- amostras pequenas deixam de aparecer como certeza;
- a API permite auditar contagens, método e escopo;
- técnicas futuras podem ser comparadas contra uma baseline explícita.

### Negativas

- a UI exibe mais informação e exige expansão deliberada pelo usuário;
- o limiar 12/30 é operacional, não uma constante científica universal;
- o perfil não melhora automaticamente o retorno dos bots.

### Neutras

- alterar Python do runtime invalida o receipt de desempenho e exige nova medição;
- ampliar contextos aumenta o risco de múltiplas comparações e requer protocolo.

## Alternativas consideradas

**Rótulos TAG/LAG fixos como principal inteligência.** Rejeitados: thresholds arbitrários
escondem contexto e estilos híbridos.

**Treinar imediatamente um classificador/transformer.** Rejeitado: não há dataset
autorizado, split temporal por jogador e holdout calibrado para o estado local.

**Inferir range pelas cartas de showdown.** Rejeitado: showdowns são uma amostra seletiva.

**Adaptar o bot diretamente às frequências.** Rejeitado: best response a modelo impreciso
pode reduzir segurança; exige gate experimental separado.

## Referências

- [Mapa sistemático e implementação](../research/COMPETITIVE_INTELLIGENCE_20260808.md)
- [Bayes' Bluff](https://arxiv.org/abs/1207.1411)
- [Balancing Safety and Exploitability](https://doi.org/10.1609/aaai.v25i1.7981)
- [Online Implicit Agent Modelling](https://aamas.csc.liv.ac.uk/Proceedings/aamas2013/docs/p255.pdf)

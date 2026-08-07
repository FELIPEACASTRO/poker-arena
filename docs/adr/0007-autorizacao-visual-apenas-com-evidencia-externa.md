# ADR-0007: somente visão externamente validada autoriza decisão

## Status

Aceita em 2026-08-07.

## Contexto

ZNCC, score de OCR e confiança bruta de detector não são probabilidades de correção calibradas.
Sanidade estrutural rejeita estados impossíveis, mas não detecta uma leitura errada e plausível.
O F1 é calibrado no gerador sintético; o VLM remoto é uma proposta sem calibração; nenhum dos
dois limita atualmente o falso aceite em interfaces reais.

## Decisão

F1 e VLM são somente diagnósticos e sempre terminam em abstenção para recomendação estratégica.
Apenas um F2 de deployment com manifesto aprovado, identidade verificada e receipt de holdout
externo válido pode autorizar decisão. Mudar limiar ou pipeline invalida o receipt.

## Consequências

### Positivas

- elimina a falsa equivalência entre plausibilidade, score alto e correção;
- transforma ausência de evidência em indisponibilidade explícita;
- alinha o runtime ao protocolo científico e aos model cards.

### Negativas

- enquanto nenhum F2 passar, imagens não produzem recomendações automáticas;
- coleta, anotação e avaliação externa têm custo real.

### Neutras

- propostas continuam visíveis para depuração supervisionada.

## Alternativas consideradas

- **Limiar ZNCC/OCR 0,85:** rejeitada como autorização; score não calibrado.
- **Sanidade estrutural apenas:** rejeitada; não captura erro semanticamente plausível.
- **VLM com confiança declarada pelo provedor:** rejeitada sem calibração independente.


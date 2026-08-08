# Contribuindo

## Princípio

Código que executa não é, por si só, evidência científica. Toda contribuição deve declarar se
é implementação, hipótese, diagnóstico ou resultado medido.

## Gate mínimo

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\assets\validar.ps1
```

Além do gate:

- mudanças no motor exigem invariantes e, quando aplicável, oráculo independente;
- mudanças de API exigem regeneração e verificação do OpenAPI;
- mudanças de visão exigem métricas por campo e estado exato, risco/cobertura e falso aceite;
- mudanças de modelo exigem manifesto, SHA-256, licença, linhagem e receipt do holdout externo;
- mudanças de thresholds exigem pré-registro, justificativa estatística e novo receipt;
- mudanças de inteligência competitiva exigem oportunidade/denominador antes da ação,
  testes de posição/papel, incerteza explícita e prova de que o perfil não altera a política;
- mudanças de interface exigem atualizar os guias HTML, screenshots/PDF afetados e seus
  testes; mudanças de uso ou arquitetura exigem atualizar o README do componente e
  `docs/README.md`;
- nenhum segredo, dado privado ou saída sensível pode entrar no commit.

Artefatos gerados não são editados manualmente. Após mudar a API, regenere
OpenAPI/Swagger/Insomnia; após mudar o guia de navegação, regenere o PDF. Preserve
resultados históricos em documentos datados e acrescente um novo snapshot em vez de
reescrever a evidência anterior.

## Commits e revisão

Use commits pequenos e semanticamente isolados. Registre trade-offs relevantes em ADR. Não
misture refatoração mecânica com mudança de comportamento científico. Um teste sintético deve
ser rotulado como sintético; não use “produção”, “universal”, “GTO” ou “validado” sem evidência
diretamente ligada ao artefato e ao protocolo correspondente.

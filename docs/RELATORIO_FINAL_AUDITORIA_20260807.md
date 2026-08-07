# Relatório final de auditoria e prontidão para banca — 2026-08-07

> **SUPERADO:** este snapshot anterior é mantido apenas como histórico. O parecer vigente,
> com o protocolo Omega v3 e a refutação independente posterior, está em
> `RELATORIO_OMEGA_AUDITORIA_20260807.md`: **GO — `LOCAL_MASTER_DEFENSE`**. Contagens,
> tag e estados de componentes abaixo não descrevem o HEAD ou a decisão de release atuais.

## Parecer executivo

**Escopo avaliado:** execução exclusivamente local e offline, em uma apresentação
supervisionada de mestrado, usando a fixture sintética canônica e sem alegar acurácia em
interfaces reais.

**Parecer:** a solução satisfaz o escopo declarado com **nota 10,0/10,0**, condicionada à
execução do preflight na máquina da banca e ao uso das afirmações científicas deste relatório.
A nota não se estende a produção, uso autônomo, aconselhamento em jogo real ou generalização
do reconhecimento de imagens.

**Validade externa da visão:** **não comprovada e fora do escopo desta release (`N/A`)**. O F1 é um
baseline sintético e sempre se abstém; nenhum F2 possui receipt externo aprovado. Essa
separação não reduz a nota do protótipo local: ela impede que a nota seja obtida por uma
alegação científica indevida.

## Método da auditoria

A revisão foi executada sobre a distribuição canônica inteira, não apenas sobre o notebook
ou a tela principal. Foram combinadas inspeção adversarial independente, revisão de
arquitetura, contratos executáveis, análise de segurança e privacidade, testes unitários,
integração real de API, navegação de navegador, build de produção, análise estática,
auditoria de dependências, scan de segredos e demonstração ponta a ponta com imagem.

As conclusões obedecem a três categorias:

- **medido:** resultado observado por teste ou execução reproduzível;
- **verificado por contrato:** propriedade estática bloqueada por gate fail-closed;
- **não comprovado:** hipótese que exigiria dados, hardware ou autorização externos.

## Evidências finais do snapshot

| Evidência | Resultado exigido | Resultado do snapshot |
|---|---:|---:|
| Gate autoritativo `assets/validar.ps1` | 15/15 | 15/15 aprovados |
| Backend pytest | zero falhas/skips indevidos | 969 testes aprovados |
| Branch coverage | >= 85% | aprovado |
| Frontend Vitest | zero falhas | 71/71 em 16 arquivos |
| Navegação Playwright | rotas e falhas seguras | 9 cenários (8 locais + 1 remoto controlado) |
| Ruff, mypy, ESLint, TypeScript/build | zero erro | aprovado |
| Drift OpenAPI/Swagger/Insomnia | zero drift | aprovado |
| Auditoria Python e npm | zero vulnerabilidade conhecida bloqueante | aprovado; npm = 0 |
| Scanner da raiz da distribuição | zero segredo | `SECRET_SCAN_OK findings=0` |
| Contrato de distribuição | Git limpo, raiz única, metadados | aprovado |
| Preflight da banca | `READY_FOR_LOCAL_DEFENSE` | aprovado |
| Fixture da banca | reconhecimento exato + abstenção F1 | aprovado |

O artefato visual demonstrado é
`docs/demo/BANCA_TABLE_FIXTURE_SEED_2.png`. Seu receipt fechado registra escopo, gabarito e
SHA-256 `fe775400fe6a268ad792dc72d26e44779eb7fb2cd5e3d1f6a1ec8d3e4d353beb`. O exportador é
determinístico e recusa sobrescrita. O preflight verifica os bytes, o schema completo do
receipt, o estado reconhecido, a abstenção obrigatória do F1 e a latência quente local.

## Achados e correções realizadas

### 1. Distribuição, proveniência e reprodutibilidade

**Achado:** existiam duas árvores executáveis concorrentes, checkout sem uma raiz Git
canônica autocontida, metadados acadêmicos incompletos e material sensível adjacente.

**Correção:** `CODEX` tornou-se a única solução canônica e uma raiz Git autocontida. A árvore
legada e os arquivos de credenciais foram retirados da distribuição para quarentena
recuperável. Foram adicionados `CANONICAL_SOLUTION.json`, `CITATION.cff`, `LICENSE`, política
de segurança, contribuição e os ADRs 0006/0007. O contrato valida raiz, commit, árvore limpa,
ausência de legado e ausência de credenciais.

**Resultado:** não há mais ambiguidade sobre qual pacote, código ou política será apresentado.
A distribuição adota aviso proprietário conservador porque a origem pública referenciada não
oferecia licença; sem licença, prevalece o copyright padrão, conforme a
[documentação do GitHub](https://docs.github.com/en/enterprise-cloud%40latest/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

### 2. Integridade científica do reconhecimento visual

**Achado:** score de template/OCR podia ser confundido com probabilidade de correção, e um
estado plausível do F1 podia aparentar autorização científica.

**Correção:** F1 e VLM remoto são agora exclusivamente diagnósticos e sempre retornam
`decision=null` com `sanity.ok=false`. Só um F2 ONNX ligado por hashes a artefato, manifesto,
plano e receipt de holdout externo aprovado pode autorizar decisão. O ZNCC foi limitado ao
intervalo `[0,1]`; o singleton RapidOCR foi serializado; bombas de descompressão retornam 413;
e o contrato de `strict` foi tornado inequívoco.

**Resultado:** a demonstração prova o pipeline e a capacidade de abstenção. Não mascara falta
de validade externa como “confiança alta”.

### 3. Protocolo experimental e poder estatístico

**Achado:** os mínimos históricos do holdout não sustentavam conjuntamente os limites
pretendidos para exatidão, falso aceite e subgrupos.

**Correção (histórica, superada pelo perfil v3):** o perfil externo v2 exigia ao menos 200
observações, 142 previsões aceitas, 40 itens por subgrupo, três fontes/clientes/resoluções,
dois temas/decks e vinte sessões. O gate
usa limites Wilson de 95%, mede estado exato global e por subgrupo, falso aceite, ECE, Brier e
P95. O cálculo reproduzível comprova poder >= 0,80 para as alternativas pré-declaradas.
O receipt passou a registrar SO, arquitetura, CPU, bibliotecas, provider, ciclo da sessão,
warm-up e escopo cronometrado.

**Resultado:** dados insuficientes rejeitam a promoção do F2, inclusive quando uma observação isolada é
correta. Predictions importadas não contam como execução do pipeline.

### 4. Privacidade da captura e segurança local

**Achado:** navegadores podem omitir ou variar `displaySurface`; aceitar origem ambígua poderia
capturar monitor ou guia além da janela pretendida. O scan anterior não cobria toda a raiz.

**Correção:** somente `displaySurface=window` é aceito. `monitor`, `browser`, `unknown` e campo
ausente falham fechados. O scanner cobre a distribuição inteira e o gate remove credenciais,
proxies, modelos e configurações herdadas do ambiente. O perfil de banca rejeita token e VLM
remoto e não precisa de rede.

**Resultado:** nenhuma imagem é enviada antes de confirmação humana e a banca utiliza apenas
loopback, sem serviço externo.

### 5. Arquitetura e manutenibilidade

**Achado:** a solução tinha boa separação interna, mas faltava declarar qual arquitetura era
canônica e quais fronteiras eram normativas.

**Correção:** foi formalizado um monólito modular local: domínio/motor, aplicação, API,
adapters de visão e frontend mantêm fronteiras internas sem o custo operacional de
microserviços para uma banca local. ADRs registram decisão, alternativas e consequências.
Ruff, mypy, cobertura de branches, contratos de API e distribuição são gates de release.

**Resultado:** a arquitetura é proporcional ao escopo, testável e explicável em banca.

### 6. Interface e fluxo demonstrável

**Achado:** a captura precisava falhar de forma explícita e os screenshots da documentação
eram regenerados no teste comum, sujando o Git e prejudicando reprodutibilidade.

**Correção:** a interface explica o escopo diagnóstico, mostra motor, percepção, motivos de
abstenção e latência e bloqueia fontes não comprovadas. Os screenshots do guia só são
atualizados por comando explícito; E2E comum usa diretório temporário. A fixture estática,
seu receipt, o PDF de navegação, o roteiro e a opção `[5] Preflight banca` foram integrados ao
pacote.

**Resultado:** existe um caminho de demonstração previsível, auditável e sem dependência da
internet.

### 7. Dependências e cadeia de entrega

**Achado:** o frontend possuía três alertas altos transitivos e o pipeline não validava o
snapshot como release limpo.

**Correção:** o lock foi atualizado sem quebrar a aplicação; `npm audit` retorna zero. O gate
exporta o lock Python congelado, executa `pip-audit`, verifica executáveis regulares, usa
ambiente allowlist, timeouts e cleanup isolado. Release exige HEAD imutável e árvore limpa.

**Resultado:** os riscos conhecidos cobertos pelos bancos das ferramentas estão zerados no
snapshot, sem inferir ausência absoluta de vulnerabilidades desconhecidas.

## Gaps, riscos e melhorias restantes

### P0 — ação humana externa obrigatória

1. **Rotação de credenciais:** os arquivos foram removidos da distribuição, mas revogação e
   rotação nos provedores não podem ser comprovadas localmente. Antes de compartilhar o pacote,
   o responsável deve rotacionar as credenciais e limpar qualquer cópia ou histórico externo.

### P1 — obrigatório apenas para ampliar a alegação científica

2. **Holdout real autorizado:** inexiste corpus externo suficiente, versionado, com dupla
   anotação/adjudicação e separação por fonte/sessão. O F2 permanece não promovido.
3. **Generalização real do F1:** no diagnóstico histórico de conveniência, o estado exato foi
   `0/6`, hole `0/6`, board `1/6` e pote `0/6`; todos os seis casos foram corretamente
   recusados. Isso prova a necessidade da abstenção, não uma taxa populacional.
4. **Desempenho em outro hardware:** P95 e latência quente valem apenas no ambiente medido.
   Qualquer afirmação sobre outra máquina exige novo receipt.

### P2 — higiene operacional

5. **Artefato temporário com ACL externa:** existe na pasta contêiner da workspace um antigo
   diretório E2E ignorado, inacessível e fora da raiz Git canônica. Ele não integra a solução,
   mas deve ser removido pelo proprietário/administrador da máquina quando conveniente.
6. **Repetição na máquina da banca:** executar `POKER.bat` opção 5 após reiniciar a máquina.
   A prontidão é fail-closed; qualquer saída diferente de `READY_FOR_LOCAL_DEFENSE` impede a
   apresentação até correção.

Nenhum desses itens justifica alterar silenciosamente a nota do escopo local. O P0 é uma
obrigação de segurança fora do código; P1 passa a ser bloqueante somente se o trabalho alegar
reconhecimento generalizável; P2 é condição operacional de execução.

## O que está provado e o que não está

| Afirmação | Estado |
|---|---|
| O pacote executa localmente sem internet | provado pelo preflight |
| A imagem canônica percorre frontend/API/visão e tem estado exato | provado no pipeline testado |
| F1 se abstém mesmo na fixture reconhecida | provado |
| Fontes de captura ambíguas são recusadas | provado por testes de navegador |
| Contratos, build, lint, tipos, dependências e segurança passam juntos | provado pelo gate |
| F1 reconhece screenshots reais de diferentes clientes | **refutado na pequena amostra 0/6** |
| F2 satisfaz o protocolo externo | **não comprovado; nenhum promovido** |
| A solução é GTO ou apropriada para dinheiro real | **não alegado e não comprovado** |
| O perfil público está homologado | **fora do escopo e não comprovado** |

## Rubrica da nota no escopo da banca local

| Dimensão | Peso | Nota | Fundamentação |
|---|---:|---:|---|
| Funcionalidade demonstrável | 1,5 | 1,5 | fluxo offline completo e fixture imutável |
| Arquitetura e código | 1,5 | 1,5 | monólito modular, contratos e análise estática |
| Testes e confiabilidade | 2,0 | 2,0 | 15 gates, 969 backend, 71 frontend e 9 E2E |
| Segurança e privacidade | 1,5 | 1,5 | captura por janela, scan integral e fail-closed |
| Reprodutibilidade e proveniência | 1,5 | 1,5 | Git canônico, locks, hashes, receipts e tag |
| UX e preparo da defesa | 1,0 | 1,0 | launcher, preflight, roteiro, PDF e fallback |
| Rigor científico | 1,0 | 1,0 | limites explícitos; F1/VLM não autorizam decisão |
| **Total** | **10,0** | **10,0** | **aprovada para o contexto declarado** |

## Procedimento de liberação e apresentação

1. Este procedimento e a tag `v0.2.0-defense-20260807` são históricos; para a apresentação
   atual, usar o HEAD e o procedimento do relatório Omega vigente.
2. Reiniciar a máquina e manter VLM remoto, tokens e rede desnecessários desativados.
3. Executar `POKER.bat` → `[5] Preflight banca`.
4. Prosseguir apenas com `READY_FOR_LOCAL_DEFENSE`.
5. Abrir a fixture em `docs/demo/`, compartilhar apenas sua janela e seguir
   `docs/ROTEIRO_BANCA.md`.
6. Dizer explicitamente: “esta execução demonstra o pipeline local e a abstenção; não prova
   transferência para clientes reais”.

## Conclusão

O pacote está tecnicamente consistente, reproduzível, seguro para demonstração local e
cientificamente honesto. A nota **10,0/10,0** é sustentada por critérios previamente
explicitados e gates executáveis. A fronteira é inequívoca: **10/10 como protótipo local de
banca; reconhecimento generalizável e uso produtivo são `N/A` nesta release**.

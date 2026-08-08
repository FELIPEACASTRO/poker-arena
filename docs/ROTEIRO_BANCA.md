# Roteiro de demonstração local para a banca

## Antes de entrar na sala

1. Reinicie a máquina e não configure tokens, VLM remoto, proxy ou credenciais no terminal.
2. Execute `POKER.bat` e escolha **Preflight banca**. Continue somente com
   `RELEASE_DECISION=GO; SCOPE=LOCAL_MASTER_DEFENSE` e `READY_FOR_LOCAL_DEFENSE`.
3. Abra `docs/demo/BANCA_TABLE_FIXTURE_SEED_2.png` no visualizador de imagens. Escolha
   **Iniciar** e compartilhe apenas essa **janela**. Mantenha o PDF
   `docs/GUIA_DE_NAVEGACAO_POKER_ARENA.pdf` aberto como fallback visual.
4. Não dependa de internet. Backend, frontend, Swagger e baseline F1 são locais.

## Sequência sugerida (7–10 minutos)

1. **Problema e arquitetura:** monólito modular local; captura → visão → sanity → decisão.
2. **Motor verificável:** crie uma mesa, mostre posições, side pots e caixa de vidro dos bots.
3. **Processamento de imagem:** escolha **Outro monitor**, mantenha o workspace de captura
   no monitor 1 e a janela da fixture visível no monitor 2. No seletor protegido, escolha
   somente **Janela**, selecione a fixture, confirme a prévia e mostre
   cartas, pote, jogadores, posição, confiança interna e latência. O JSON ao lado da imagem
   contém o SHA-256 e o gabarito auditável.
4. **Rigor científico:** destaque que F1 é um baseline sintético e, por isso, a recomendação
   estratégica é suprimida por segurança mesmo quando a fixture é lida corretamente. Esse é
   o resultado esperado e aprovado da demo. Mostre o receipt obrigatório do F2.
5. **Falha segura:** tente uma fonte não comprovada/guia ou imagem inválida e mostre a abstenção.
6. **Reprodutibilidade:** mostre o commit, o preflight e o gate completo, sem alegar que testes
   sintéticos provam generalização para clientes reais.

Se houver apenas uma tela, use **Mesmo monitor** e organize painel e fixture lado a lado.
Não minimize nem sobreponha a janela capturada. O navegador não expõe o número físico do
monitor; a verificação é feita pela seleção humana e pela prévia, nunca por uma alegação
automática da aplicação.

## Frases cientificamente seguras

- “Esta execução demonstra o pipeline local e seus mecanismos de abstenção.”
- “O F1 foi medido no renderizador sintético canônico; transferência real ainda não foi provada.”
- “Somente o F2 com holdout externo, diversidade, poder estatístico e receipt imutável pode
  habilitar uma recomendação.”

Evite “100% preciso”, “GTO”, “produção” ou “funciona em qualquer sala”.

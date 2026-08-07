# Roteiro de demonstração local para a banca

## Antes de entrar na sala

1. Reinicie a máquina e não configure tokens, VLM remoto, proxy ou credenciais no terminal.
2. Execute `POKER.bat` e escolha **Preflight banca**. Continue somente com
   `READY_FOR_LOCAL_DEFENSE`.
3. Escolha **Iniciar**, permita compartilhamento apenas de uma **janela** e mantenha o PDF
   `docs/GUIA_DE_NAVEGACAO_POKER_ARENA.pdf` aberto como fallback visual.
4. Não dependa de internet. Backend, frontend, Swagger e baseline F1 são locais.

## Sequência sugerida (7–10 minutos)

1. **Problema e arquitetura:** monólito modular local; captura → visão → sanity → decisão.
2. **Motor verificável:** crie uma mesa, mostre posições, side pots e caixa de vidro dos bots.
3. **Processamento de imagem:** selecione somente a janela autorizada, confirme a prévia e
   mostre cartas, pote, jogadores, posição, confiança interna e latência.
4. **Rigor científico:** destaque que F1 é um baseline sintético e, por isso, a decisão fica
   bloqueada mesmo quando a fixture é lida corretamente. Mostre o receipt obrigatório do F2.
5. **Falha segura:** tente uma fonte não comprovada/guia ou imagem inválida e mostre a abstenção.
6. **Reprodutibilidade:** mostre o commit, o preflight e o gate completo, sem alegar que testes
   sintéticos provam generalização para clientes reais.

## Frases cientificamente seguras

- “Esta execução demonstra o pipeline local e seus mecanismos de abstenção.”
- “O F1 foi medido no renderizador sintético canônico; transferência real ainda não foi provada.”
- “Somente o F2 com holdout externo, diversidade, poder estatístico e receipt imutável pode
  habilitar uma recomendação.”

Evite “100% preciso”, “GTO”, “produção” ou “funciona em qualquer sala”.

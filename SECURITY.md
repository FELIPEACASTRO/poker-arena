# Política de segurança

## Escopo

Inclui backend, frontend, scripts operacionais, notebooks, modelos, manifests, receipts e a
cadeia de captura de imagens. Screenshots de tela e históricos de jogo devem ser tratados como
dados potencialmente sensíveis.

## Reporte

Não abra uma issue pública contendo segredo, screenshot privado, token, cookie ou arquivo de
credencial. Envie o relato diretamente ao mantenedor do projeto, incluindo somente o caminho,
tipo de exposição e passos mínimos de reprodução; substitua valores por `[REDACTED_SECRET]`.

## Regras obrigatórias

- Segredos entram apenas por cofre/ambiente ou arquivo externo com ACL restritiva.
- Nunca imprimir, persistir em notebook, incorporar em URL Git ou transmitir em query string.
- Credencial encontrada na árvore é considerada comprometida: remover não basta; é obrigatório
  revogar/rotacionar e inspecionar artefatos/histórico.
- Captura local aceita somente uma janela explicitamente confirmada. Origem desconhecida,
  monitor ou guia do navegador falham fechado.
- Envio a VLM remoto exige TLS, host aprovado, redaction, autenticação e consentimento efêmero.
- F1 e VLM não calibrados nunca autorizam recomendação estratégica.
- Perfis competitivos são calculados somente em memória a partir da sessão local, não
  importam históricos de terceiros e não têm autoridade para recomendar ou alterar ações.
- A recomendação do Copiloto é destinada ao laboratório local, estudo e simulação. Não use
  captura, perfil ou conselho durante partidas de terceiros quando a plataforma proíba RTA.

## Dependências e releases

O release exige auditoria Python e npm, scan da raiz completa, lockfiles, hashes de artefatos,
tag imutável e ausência de arquivos gerados ou credenciais no conjunto publicado.

## Incidente de 2026-08-07

Arquivos de credencial foram detectados na raiz de trabalho e movidos para quarentena externa
sem leitura manual de seus valores. A publicação continua condicionada à confirmação humana de
revogação/rotação em cada provedor afetado.

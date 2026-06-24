# Documentação da API — Poker Arena

Tudo o que você precisa para entender e testar os serviços da solução. A API é um
**Texas Hold'em No-Limit 6-max** — você joga contra IAs ou assiste os bots se
enfrentarem no **Modo Laboratório**.

> Base local: **http://127.0.0.1:8000** (suba o backend pelo atalho **POKER** na Área
> de Trabalho, ou por `POKER.bat`).

## O que tem nesta pasta

| Arquivo | Para quê |
|---|---|
| **`swagger.html`** | Swagger (documentação interativa) **standalone** — abre por duplo-clique, sem precisar de servidor. |
| **`openapi.json`** | A especificação **OpenAPI 3.1** completa (importável em qualquer ferramenta). |
| **`insomnia.json`** | Projeto **Insomnia** com **todos os serviços** em pastas, exemplos prontos e um ambiente. |
| **`generate.py`** | Regenera os 3 arquivos a partir do código (fonte única da verdade). |

## 1) Swagger (3 formas de ver)

- **Ao vivo (recomendado):** com o backend rodando, abra **http://127.0.0.1:8000/docs**
  (Swagger UI) ou **/redoc**. Tem o botão **"Try it out"** para chamar de verdade.
- **Offline:** dê duplo-clique em **`swagger.html`** — a documentação abre no navegador
  com a spec embutida (o "Try it out" só chama de verdade se o backend estiver no ar).
- **Importar:** use o `openapi.json` em Postman/Insomnia/Stoplight, etc.

## 2) Insomnia (projeto pronto)

1. Abra o **Insomnia** → **Import** → selecione o arquivo **`insomnia.json`**.
2. No canto superior, selecione o ambiente **"Base local"** (já aponta para
   `http://127.0.0.1:8000`).
3. **Fluxo típico:**
   1. Rode **Mesa → Criar mesa**. Na resposta, **copie o `table_id`**.
   2. Abra o ambiente (Manage Environments) e cole o valor na variável **`table_id`**.
   3. Agora todas as chamadas (`Ler estado`, `Pagar`, `Aumentar`, `Próxima mão`,
      `Adicionar bot`…) já usam esse `table_id`.
   - Para auditoria, rode **Listar partidas**, copie um `id` para a variável `game_id`
     e rode **Replay de partida**.

> Dica: o `insomnia.json` usa variáveis no estilo `{{ _.base_url }}` (Insomnia atual).
> Se sua versão for antiga, importe o `openapi.json` em vez do projeto nativo.

## 3) Serviços (endpoints)

| Grupo | Método | Rota | O que faz |
|---|---|---|---|
| Mesa | `POST` | `/tables` | Cria a partida → devolve o `table_id`. |
| Mesa | `GET` | `/tables/{id}` | Lê o estado atual da mesa. |
| Jogada | `POST` | `/tables/{id}/actions` | Sua jogada (fold/check/call/raise/all_in). |
| Jogada | `POST` | `/tables/{id}/step` | Avança 1 jogada de bot (modo watch). |
| Jogada | `POST` | `/tables/{id}/next-hand` | Começa a próxima mão. |
| Jogadores | `POST` | `/tables/{id}/players` | Senta um novo bot (nível à escolha). |
| Jogadores | `DELETE` | `/tables/{id}/players/{seat}` | Remove um jogador. |
| Catálogo | `GET` | `/levels` | Níveis de IA disponíveis. |
| Auditoria | `GET` | `/games` | Lista as partidas gravadas. |
| Auditoria | `GET` | `/games/{id}` | Replay completo de uma partida. |
| Sistema | `GET` | `/health` | Saúde do serviço. |
| Tempo real | `WS` | `/tables/{id}/ws` | Jogar com push de estado (WebSocket). |

### O campo `phase` (o que fazer a seguir)
- `human_turn` → sua vez: chame `POST /actions` (veja `legal.actions`).
- `bot_turn` → vez de um bot: no modo watch, chame `POST /step`.
- `hand_over` → mão acabou: chame `POST /next-hand`.
- `game_over` → a partida terminou.

### Níveis de IA
`random` (Iniciante) · `heuristic` (Amador) · `montecarlo` (Intermediário) ·
`adaptive` (Adaptativo) · `expert` (Expert — só aparece em `/levels` se o modelo
treinado estiver instalado).

---

### Como regenerar
Os 3 arquivos saem do próprio código (assim nunca ficam desatualizados):

```bash
cd backend
uv run python ../api-docs/generate.py
```

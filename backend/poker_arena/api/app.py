"""FastAPI app — rotas REST sobre a aplicação.

CQRS na prática: POST cria/altera (comandos), GET lê (query). Erros do domínio/
aplicação são traduzidos em códigos HTTP no único ponto que conhece HTTP.
Dependência injetada via `Annotated[...]` (idioma moderno do FastAPI).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from ..application import (
    ExpertUnavailable,
    GameSession,
    InvalidActionError,
    SessionNotFound,
    SessionRepository,
    UnknownBotLevel,
    available_levels,
    build_session,
)
from ..engine.game import IllegalActionError
from .dependencies import get_repository
from .mappers import to_config, to_response
from .schemas import (
    ActionRequest,
    AddPlayerRequest,
    CreateTableRequest,
    TableStateResponse,
)

RepoDep = Annotated[SessionRepository, Depends(get_repository)]


def _get(repo: SessionRepository, table_id: str) -> GameSession:
    try:
        return repo.get(table_id)
    except SessionNotFound as e:
        raise HTTPException(404, f"mesa {table_id} não encontrada") from e


def _state(session: GameSession) -> dict[str, object]:
    return to_response(session.view()).model_dump()


API_DESCRIPTION = """
API do **Poker Arena** — um **Texas Hold'em No-Limit 6-max** em que um humano joga
contra bots de IA de níveis configuráveis, ou assiste os bots se enfrentarem no
**Modo Laboratório** (comparando os paradigmas de IA ao vivo, com as cartas abertas).

### Como funciona
1. **Crie uma mesa** com `POST /tables` (escolha os bots, blinds, formato e modo).
   A resposta traz o `table_id` — use-o em todas as próximas chamadas.
2. **Acompanhe o estado** pela `TableStateResponse`. O campo `phase` diz o que fazer:
   - `human_turn` → é a sua vez: envie uma jogada em `POST /tables/{id}/actions`
     (as jogadas válidas vêm em `legal.actions`).
   - `bot_turn` → vez de um bot. No modo `watch`, avance com `POST /tables/{id}/step`.
   - `hand_over` → a mão acabou: comece a próxima com `POST /tables/{id}/next-hand`.
   - `game_over` → a partida terminou (torneio/limite de mãos).
3. **Gerencie a mesa ao vivo**: sente novos bots (`POST .../players`) ou remova
   jogadores (`DELETE .../players/{seat}`) entre as mãos.
4. **Revise depois**: toda partida é gravada — liste em `GET /games` e veja o replay
   mão a mão em `GET /games/{id}`.

### Caixa de vidro (glass-box AI)
Cada bot expõe o **raciocínio real** da última jogada no campo `seats[].insight`
(ex.: *"Equity 37% (200 simulações)"*). No seu turno, o campo `analysis` traz uma
análise completa da sua mão (equity, outs, pot odds, EV, e o que cada IA faria).

### Níveis de IA
`random` (Iniciante), `heuristic` (Amador), `montecarlo` (Intermediário),
`adaptive` (Adaptativo) e `expert` (Expert — IA treinada, aparece em `GET /levels`
só quando o modelo está disponível).
"""

TAGS_METADATA = [
    {"name": "Mesa", "description": "Criar uma partida e ler o estado da mesa."},
    {"name": "Jogada", "description": "Avançar o jogo: sua jogada, jogada dos bots e próxima mão."},
    {"name": "Jogadores", "description": "Entrar/sair de jogadores na mesa ao vivo (como num cassino)."},
    {"name": "Catálogo", "description": "Dados de apoio (níveis de IA disponíveis)."},
    {"name": "Auditoria", "description": "Histórico das partidas gravadas e replay mão a mão."},
    {"name": "Tempo real", "description": "Canal WebSocket para jogar com push de estado."},
    {"name": "Sistema", "description": "Saúde do serviço."},
]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Poker Arena API",
        version="0.1.0",
        summary="Texas Hold'em No-Limit 6-max contra IAs de níveis configuráveis.",
        description=API_DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        contact={"name": "Poker Arena", "url": "http://localhost:5173"},
        license_info={"name": "Uso educacional (feira de ciências)"},
    )
    app.add_middleware(
        CORSMiddleware,
        # app local: libera qualquer porta de localhost/127.0.0.1 (dev em portas variadas)
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["Sistema"], summary="Saúde do serviço")
    def health() -> dict[str, str]:
        """Retorna `{"status": "ok"}` se a API está no ar. Útil para o launcher/monitor."""
        return {"status": "ok"}

    @app.get("/levels", tags=["Catálogo"], summary="Níveis de IA disponíveis")
    def levels() -> dict[str, list[str]]:
        """Lista os níveis de bot que podem ser usados ao criar uma mesa ou adicionar
        um jogador. O `expert` só aparece quando o modelo treinado está instalado."""
        return {"levels": list(available_levels())}

    @app.get("/games", tags=["Auditoria"], summary="Listar partidas gravadas")
    def games() -> dict[str, list[dict]]:
        """Histórico de todas as partidas (resumo: id, modo, nº de mãos, data).
        Toda partida é gravada automaticamente em disco para auditoria/replay."""
        from ..application.match_log import list_games

        return {"games": list_games()}

    @app.get(
        "/games/{game_id}",
        tags=["Auditoria"],
        summary="Replay completo de uma partida",
        responses={404: {"description": "Partida não encontrada."}},
    )
    def game(game_id: str) -> dict:
        """Devolve o log completo de uma partida: cada mão com as ações, o **raciocínio
        de cada bot** no momento (glass-box), o board, os vencedores e o saldo em fichas."""
        from ..application.match_log import read_game

        g = read_game(game_id)
        if g is None:
            raise HTTPException(404, "jogo não encontrado")
        return g

    @app.post(
        "/tables",
        response_model=TableStateResponse,
        status_code=201,
        tags=["Mesa"],
        summary="Criar uma mesa (nova partida)",
        response_description="Estado inicial da mesa, já com a 1ª mão distribuída.",
        responses={400: {"description": "Nível de bot inválido ou Expert indisponível."}},
    )
    def create_table(req: CreateTableRequest, repo: RepoDep) -> TableStateResponse:
        """Cria uma partida com os bots, blinds, formato (cash/torneio) e modo (play/watch)
        escolhidos. **Guarde o `table_id` da resposta** — ele identifica a mesa em todas
        as chamadas seguintes."""
        try:
            session = build_session(to_config(req), seed=req.seed)
        except (UnknownBotLevel, ExpertUnavailable) as e:
            raise HTTPException(400, str(e)) from e
        repo.add(session)
        return to_response(session.view())

    @app.get(
        "/tables/{table_id}",
        response_model=TableStateResponse,
        tags=["Mesa"],
        summary="Ler o estado atual da mesa",
        responses={404: {"description": "Mesa não encontrada."}},
    )
    def get_table(table_id: str, repo: RepoDep) -> TableStateResponse:
        """Devolve o estado completo e atual da mesa (fase, cartas, pote, cadeiras,
        jogadas válidas, análises). É o jeito de 'dar refresh' sem alterar nada."""
        return to_response(_get(repo, table_id).view())

    @app.post(
        "/tables/{table_id}/actions",
        response_model=TableStateResponse,
        tags=["Jogada"],
        summary="Fazer a sua jogada (turno do humano)",
        responses={
            400: {"description": "Jogada ilegal (não está em `legal.actions` ou valor fora do permitido)."},
            404: {"description": "Mesa não encontrada."},
        },
    )
    def act(
        table_id: str, action: ActionRequest, repo: RepoDep
    ) -> TableStateResponse:
        """Aplica a sua jogada quando `phase == human_turn`. Só valem as ações listadas
        em `legal.actions`; para `raise`, o `amount` é o valor TOTAL (entre `min_raise_to`
        e `max_raise_to`). Os bots jogam sozinhos em seguida, até voltar a ser a sua vez."""
        session = _get(repo, table_id)
        try:
            session.apply_human_action(action.type, action.amount)
        except (InvalidActionError, IllegalActionError) as e:
            raise HTTPException(400, str(e)) from e
        return to_response(session.view())

    @app.post(
        "/tables/{table_id}/next-hand",
        response_model=TableStateResponse,
        tags=["Jogada"],
        summary="Começar a próxima mão",
        responses={
            400: {"description": "A mão atual ainda não terminou (`phase` != `hand_over`)."},
            404: {"description": "Mesa não encontrada."},
        },
    )
    def next_hand(table_id: str, repo: RepoDep) -> TableStateResponse:
        """Distribui uma nova mão. Só é válido quando `phase == hand_over`."""
        session = _get(repo, table_id)
        try:
            session.next_hand()
        except InvalidActionError as e:
            raise HTTPException(400, str(e)) from e
        return to_response(session.view())

    @app.post(
        "/tables/{table_id}/step",
        response_model=TableStateResponse,
        tags=["Jogada"],
        summary="Avançar uma jogada de bot (Modo Laboratório)",
        responses={
            400: {"description": "Não há jogada de bot pendente (`phase` != `bot_turn`)."},
            404: {"description": "Mesa não encontrada."},
        },
    )
    def step(table_id: str, repo: RepoDep) -> TableStateResponse:
        """No modo `watch`, avança UMA jogada de bot por vez — é assim que você acompanha
        a partida lance a lance, vendo o raciocínio de cada IA. Válido só em `bot_turn`."""
        session = _get(repo, table_id)
        try:
            session.step()  # avança uma jogada de bot (modo assistir)
        except InvalidActionError as e:
            raise HTTPException(400, str(e)) from e
        return to_response(session.view())

    @app.post(
        "/tables/{table_id}/players",
        response_model=TableStateResponse,
        tags=["Jogadores"],
        summary="Sentar um novo bot na mesa",
        responses={
            400: {"description": "Mesa cheia (máx. 6) ou nível inválido."},
            404: {"description": "Mesa não encontrada."},
        },
    )
    def add_player(
        table_id: str, req: AddPlayerRequest, repo: RepoDep
    ) -> TableStateResponse:
        """Adiciona um bot do nível escolhido. A mudança vale **a partir da próxima mão**
        (a mão atual termina normalmente). Mesa 6-max."""
        session = _get(repo, table_id)
        try:
            session.add_bot(req.level, name=req.name, buy_in=req.buy_in)
        except InvalidActionError as e:
            raise HTTPException(400, str(e)) from e
        return to_response(session.view())

    @app.delete(
        "/tables/{table_id}/players/{seat}",
        response_model=TableStateResponse,
        tags=["Jogadores"],
        summary="Remover um jogador da mesa",
        responses={
            400: {"description": "Cadeira inválida, é o humano, ou restariam menos de 2 jogadores."},
            404: {"description": "Mesa não encontrada."},
        },
    )
    def remove_player(table_id: str, seat: int, repo: RepoDep) -> TableStateResponse:
        """Remove o jogador da cadeira indicada (índice em `roster`). Vale a partir da
        próxima mão. Não dá para remover o humano nem deixar a mesa com menos de 2."""
        session = _get(repo, table_id)
        try:
            session.remove_player(seat)
        except InvalidActionError as e:
            raise HTTPException(400, str(e)) from e
        return to_response(session.view())

    @app.websocket("/tables/{table_id}/ws")
    async def ws(websocket: WebSocket, table_id: str, repo: RepoDep) -> None:
        await websocket.accept()
        try:
            session = repo.get(table_id)
        except SessionNotFound:
            await websocket.close(code=4404)
            return
        await websocket.send_json(_state(session))  # estado inicial
        while True:
            try:
                msg = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            try:
                session.apply_human_action(
                    str(msg.get("type")), int(msg.get("amount", 0))
                )
            except (InvalidActionError, IllegalActionError) as e:
                await websocket.send_json({"error": str(e)})
                continue
            await websocket.send_json(_state(session))  # push do novo estado

    return app


app = create_app()

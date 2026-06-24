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
from .schemas import ActionRequest, CreateTableRequest, TableStateResponse

RepoDep = Annotated[SessionRepository, Depends(get_repository)]


def _get(repo: SessionRepository, table_id: str) -> GameSession:
    try:
        return repo.get(table_id)
    except SessionNotFound as e:
        raise HTTPException(404, f"mesa {table_id} não encontrada") from e


def _state(session: GameSession) -> dict[str, object]:
    return to_response(session.view()).model_dump()


def create_app() -> FastAPI:
    app = FastAPI(title="Poker Arena API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        # app local: libera qualquer porta de localhost/127.0.0.1 (dev em portas variadas)
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/levels")
    def levels() -> dict[str, list[str]]:
        # Expert só aparece quando o modelo treinado existe (ready-to-plug)
        return {"levels": list(available_levels())}

    @app.post("/tables", response_model=TableStateResponse, status_code=201)
    def create_table(req: CreateTableRequest, repo: RepoDep) -> TableStateResponse:
        try:
            session = build_session(to_config(req), seed=req.seed)
        except (UnknownBotLevel, ExpertUnavailable) as e:
            raise HTTPException(400, str(e)) from e
        repo.add(session)
        return to_response(session.view())

    @app.get("/tables/{table_id}", response_model=TableStateResponse)
    def get_table(table_id: str, repo: RepoDep) -> TableStateResponse:
        return to_response(_get(repo, table_id).view())

    @app.post("/tables/{table_id}/actions", response_model=TableStateResponse)
    def act(
        table_id: str, action: ActionRequest, repo: RepoDep
    ) -> TableStateResponse:
        session = _get(repo, table_id)
        try:
            session.apply_human_action(action.type, action.amount)
        except (InvalidActionError, IllegalActionError) as e:
            raise HTTPException(400, str(e)) from e
        return to_response(session.view())

    @app.post("/tables/{table_id}/next-hand", response_model=TableStateResponse)
    def next_hand(table_id: str, repo: RepoDep) -> TableStateResponse:
        session = _get(repo, table_id)
        try:
            session.next_hand()
        except InvalidActionError as e:
            raise HTTPException(400, str(e)) from e
        return to_response(session.view())

    @app.post("/tables/{table_id}/step", response_model=TableStateResponse)
    def step(table_id: str, repo: RepoDep) -> TableStateResponse:
        session = _get(repo, table_id)
        try:
            session.step()  # avança uma jogada de bot (modo assistir)
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

"""ACL (Anti-Corruption Layer): traduz entre o mundo da aplicação e o da web.

A aplicação fala em dataclasses (`TableStateView`); a web fala em Pydantic
(`TableStateResponse`). Aqui é o único ponto que conhece os dois — então mudar o
JSON não vaza para o domínio, e vice-versa.
"""

from __future__ import annotations

from dataclasses import asdict

from ..application import BotSpec, SessionConfig, TableStateView
from .schemas import (
    ActionSchema,
    CreateTableRequest,
    LegalSchema,
    OpponentReadSchema,
    SeatSchema,
    TableStateResponse,
)


def to_config(req: CreateTableRequest) -> SessionConfig:
    return SessionConfig(
        human_name=req.human_name,
        bots=[BotSpec(b.name, b.level) for b in req.bots],
        starting_stack=req.starting_stack,
        small_blind=req.small_blind,
        big_blind=req.big_blind,
        rebuy=req.rebuy,
        mode=req.mode,
        hand_limit=req.hand_limit,
    )


def to_response(view: TableStateView) -> TableStateResponse:
    return TableStateResponse(
        table_id=view.table_id,
        hand_number=view.hand_number,
        phase=view.phase,
        board=view.board,
        pot=view.pot,
        seats=[SeatSchema(**asdict(s)) for s in view.seats],
        legal=LegalSchema(**asdict(view.legal)) if view.legal else None,
        last_actions=[ActionSchema(**asdict(a)) for a in view.last_actions],
        winners=view.winners,
        opponent_read=(
            OpponentReadSchema(**asdict(view.opponent_read))
            if view.opponent_read
            else None
        ),
    )

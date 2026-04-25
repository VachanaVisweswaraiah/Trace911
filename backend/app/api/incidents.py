from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.pubsub import broker
from app.repository import calls as calls_repo
from app.repository import incident as incident_repo
from app.schemas import IncidentCard, IncidentPatchRequest

router = APIRouter()


@router.patch("/calls/{call_id}/incident", response_model=IncidentCard)
async def patch_incident(
    call_id: str,
    body: IncidentPatchRequest,
    db: AsyncSession = Depends(get_session),
) -> IncidentCard:
    call = await calls_repo.get(db, call_id)
    if call is None:
        raise HTTPException(404, "call not found")

    card = await incident_repo.patch(db, call_id, body, t_now=broker.t_for(call_id))
    await broker.publish(call_id, "incident", card.model_dump(mode="json"))
    return card

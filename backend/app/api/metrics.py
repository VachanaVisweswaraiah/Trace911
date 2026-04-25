from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.repository import calls as calls_repo
from app.schemas import MetricsSnapshot

router = APIRouter()


@router.get("/calls/{call_id}/metrics", response_model=MetricsSnapshot)
async def get_metrics(
    call_id: str, db: AsyncSession = Depends(get_session)
) -> MetricsSnapshot:
    call = await calls_repo.get(db, call_id)
    if call is None:
        raise HTTPException(404, "call not found")
    return MetricsSnapshot.model_validate(call.metrics_json or {})

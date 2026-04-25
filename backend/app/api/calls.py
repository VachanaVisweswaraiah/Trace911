from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.pubsub import broker
from app.repository import calls as calls_repo
from app.schemas import (
    CallCreateRequest,
    CallCreateResponse,
    CallSnapshot,
    CallSummary,
    IncidentCard,
)
from app.schemas.incident import FIELD_NAMES

router = APIRouter()


@router.post("/calls", response_model=CallCreateResponse, status_code=201)
async def create_call(
    body: CallCreateRequest, db: AsyncSession = Depends(get_session)
) -> CallCreateResponse:
    call = await calls_repo.create(db, body.source)
    broker.register_call(call.id, call.started_at)
    return CallCreateResponse(
        call_id=call.id,
        started_at=call.started_at,
        ws_url=f"/ws/calls/{call.id}",
    )


@router.get("/calls/{call_id}", response_model=CallSnapshot)
async def get_call(call_id: str, db: AsyncSession = Depends(get_session)) -> CallSnapshot:
    snap = await calls_repo.snapshot(db, call_id)
    if snap is None:
        raise HTTPException(404, "call not found")
    return snap


@router.post("/calls/{call_id}/audio", status_code=202)
async def upload_audio(
    call_id: str,
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    call = await calls_repo.get(db, call_id)
    if call is None:
        raise HTTPException(404, "call not found")
    data = await audio.read()
    # TODO: hand to services.audio_enhancement → stt → extraction pipeline
    return {"accepted_bytes": len(data)}


@router.post("/calls/{call_id}/end", response_model=CallSummary)
async def end_call(call_id: str, db: AsyncSession = Depends(get_session)) -> CallSummary:
    call = await calls_repo.end(db, call_id)
    if call is None:
        raise HTTPException(404, "call not found")
    summary = _summary_from_card(call_id, calls_repo.to_snapshot(call).incident)
    await broker.publish(
        call_id, "call_ended", {"summary_url": f"/api/calls/{call_id}/summary"}
    )
    return summary


@router.get("/calls/{call_id}/summary", response_model=CallSummary)
async def get_summary(call_id: str, db: AsyncSession = Depends(get_session)) -> CallSummary:
    snap = await calls_repo.snapshot(db, call_id)
    if snap is None:
        raise HTTPException(404, "call not found")
    return _summary_from_card(call_id, snap.incident)


def _summary_from_card(call_id: str, card: IncidentCard) -> CallSummary:
    unconfirmed = [
        name
        for name in FIELD_NAMES
        if getattr(card, name).status in ("missing", "heard", "uncertain")
    ]
    return CallSummary(call_id=call_id, narrative="", incident=card, unconfirmed=unconfirmed)

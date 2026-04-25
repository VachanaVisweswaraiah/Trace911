from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
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
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    call = await calls_repo.get(db, call_id)
    if call is None:
        raise HTTPException(404, "call not found")
    data = await audio.read()
    background_tasks.add_task(_run_pipeline, call_id, data)
    return {"accepted_bytes": len(data)}


async def _run_pipeline(call_id: str, wav_bytes: bytes) -> None:
    """Enhance → transcribe. Runs as a background task after the HTTP response returns."""
    from app.services import audio_enhancement, stt

    await broker.publish(
        call_id, "alert", {"message": "Pipeline started: enhancing audio…", "severity": "info"}
    )
    try:
        enhanced = await audio_enhancement.enhance_and_meter(call_id, wav_bytes)
    except Exception as exc:
        await broker.publish(
            call_id, "alert", {"message": f"Enhancement error: {exc}", "severity": "error"}
        )
        return

    await broker.publish(
        call_id, "alert", {"message": "Enhancement done — transcribing…", "severity": "info"}
    )
    try:
        await stt.stream_transcribe(call_id, enhanced)
    except Exception as exc:
        await broker.publish(
            call_id, "alert", {"message": f"Transcription error: {exc}", "severity": "error"}
        )
        return

    await broker.publish(
        call_id, "alert", {"message": "Transcription complete.", "severity": "info"}
    )


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

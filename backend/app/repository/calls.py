"""Call CRUD + snapshot assembly."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.orm import Call
from app.repository import incident as incident_repo
from app.schemas import (
    CallSnapshot,
    IncidentCard,
    MetricsSnapshot,
    OperatorAssist,
    TranscriptSegment,
)


async def create(db: AsyncSession, source: str) -> Call:
    call = Call(
        id=f"call_{uuid.uuid4().hex[:12]}",
        source=source,
        started_at=datetime.now(timezone.utc),
        metrics_json={},
        assist_json={},
    )
    db.add(call)
    await db.flush()
    await incident_repo.init_for_call(db, call.id)
    return call


async def get(db: AsyncSession, call_id: str) -> Call | None:
    stmt = (
        select(Call)
        .where(Call.id == call_id)
        .options(selectinload(Call.transcript), selectinload(Call.fields))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def end(db: AsyncSession, call_id: str) -> Call | None:
    call = await get(db, call_id)
    if call is None:
        return None
    call.ended_at = datetime.now(timezone.utc)
    return call


async def update_metrics(db: AsyncSession, call_id: str, metrics: MetricsSnapshot) -> None:
    call = await get(db, call_id)
    if call is None:
        return
    call.metrics_json = metrics.model_dump(mode="json")


async def update_assist(db: AsyncSession, call_id: str, assist: OperatorAssist) -> None:
    call = await get(db, call_id)
    if call is None:
        return
    call.assist_json = assist.model_dump(mode="json")


def to_snapshot(call: Call) -> CallSnapshot:
    """Pure transform: ORM Call (with relationships loaded) → CallSnapshot DTO."""
    transcript = [
        TranscriptSegment(
            id=s.id,
            t_start=s.t_start,
            t_end=s.t_end,
            speaker=s.speaker,  # type: ignore[arg-type]
            text=s.text,
            is_final=s.is_final,
            confidence=s.confidence,
            entities=s.entities_json or [],
        )
        for s in sorted(call.transcript, key=lambda x: x.t_start)
    ]
    incident_card = incident_repo.assemble_card(call.fields)
    metrics = MetricsSnapshot.model_validate(call.metrics_json or {})
    assist = OperatorAssist.model_validate(call.assist_json or {})
    return CallSnapshot(
        call_id=call.id,
        started_at=call.started_at,
        ended_at=call.ended_at,
        transcript=transcript,
        incident=incident_card,
        metrics=metrics,
        assist=assist,
    )


async def snapshot(db: AsyncSession, call_id: str) -> CallSnapshot | None:
    call = await get(db, call_id)
    if call is None:
        return None
    return to_snapshot(call)

"""Transcript segment CRUD. Partial→final updates upsert by segment id."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import TranscriptSegment as SegmentOrm
from app.schemas import TranscriptSegment


async def upsert(db: AsyncSession, call_id: str, seg: TranscriptSegment) -> SegmentOrm:
    stmt = select(SegmentOrm).where(SegmentOrm.id == seg.id, SegmentOrm.call_id == call_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = SegmentOrm(id=seg.id, call_id=call_id)
        db.add(row)
    row.t_start = seg.t_start
    row.t_end = seg.t_end
    row.speaker = seg.speaker
    row.text = seg.text
    row.is_final = seg.is_final
    row.confidence = seg.confidence
    row.entities_json = [e.model_dump() for e in seg.entities]
    await db.flush()
    return row


async def list_for_call(db: AsyncSession, call_id: str) -> list[SegmentOrm]:
    stmt = (
        select(SegmentOrm)
        .where(SegmentOrm.call_id == call_id)
        .order_by(SegmentOrm.t_start.asc())
    )
    return list((await db.execute(stmt)).scalars())

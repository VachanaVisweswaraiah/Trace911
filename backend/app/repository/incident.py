"""Incident-field CRUD + card assembly."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import IncidentField as IncidentFieldOrm
from app.schemas import IncidentCard
from app.schemas import IncidentField as IncidentFieldDto
from app.schemas.incident import FIELD_NAMES, IncidentPatchRequest


async def init_for_call(db: AsyncSession, call_id: str) -> None:
    """Seed an empty (`status='missing'`) row per tracked field."""
    for name in FIELD_NAMES:
        db.add(IncidentFieldOrm(call_id=call_id, field=name, status="missing"))
    await db.flush()


async def list_for_call(db: AsyncSession, call_id: str) -> list[IncidentFieldOrm]:
    stmt = select(IncidentFieldOrm).where(IncidentFieldOrm.call_id == call_id)
    return list((await db.execute(stmt)).scalars())


def assemble_card(rows: list[IncidentFieldOrm]) -> IncidentCard:
    by_field: dict[str, IncidentFieldOrm] = {r.field: r for r in rows}
    payload: dict[str, IncidentFieldDto] = {}
    for name in FIELD_NAMES:
        r = by_field.get(name)
        if r is None:
            payload[name] = IncidentFieldDto(field=name)  # type: ignore[arg-type]
        else:
            payload[name] = IncidentFieldDto(
                field=name,  # type: ignore[arg-type]
                value=r.value,
                status=r.status,  # type: ignore[arg-type]
                confidence=r.confidence,
                source_segment_ids=list(r.source_segment_ids_json or []),
                updated_at_t=r.updated_at_t,
            )

    populated = sum(1 for n in FIELD_NAMES if payload[n].status != "missing")
    confirmed = sum(1 for n in FIELD_NAMES if payload[n].status == "confirmed_by_operator")
    total = len(FIELD_NAMES)

    card = IncidentCard(**payload)
    card.field_coverage = round(populated / total, 3)
    card.confirmed_coverage = round(confirmed / total, 3)
    card.dispatch_readiness = round(0.5 * card.field_coverage + 0.5 * card.confirmed_coverage, 3)
    return card


async def patch(
    db: AsyncSession,
    call_id: str,
    body: IncidentPatchRequest,
    t_now: float,
) -> IncidentCard:
    rows = await list_for_call(db, call_id)
    by_field = {r.field: r for r in rows}
    for upd in body.updates:
        row = by_field.get(upd.field)
        if row is None:
            row = IncidentFieldOrm(call_id=call_id, field=upd.field)
            db.add(row)
            by_field[upd.field] = row
        if upd.value is not None:
            row.value = upd.value
        row.status = upd.status
        row.updated_at_t = t_now
        if upd.status == "confirmed_by_operator":
            row.confidence = 1.0
    await db.flush()
    return assemble_card(list(by_field.values()))


async def upsert_extracted(
    db: AsyncSession,
    call_id: str,
    field: str,
    value: str | None,
    status: str,
    confidence: float,
    source_segment_ids: list[str],
    t_now: float,
) -> None:
    """Used by the extraction service. Never sets confirmed_by_operator."""
    if status == "confirmed_by_operator":
        raise ValueError("extraction service must not set confirmed_by_operator")
    stmt = select(IncidentFieldOrm).where(
        IncidentFieldOrm.call_id == call_id, IncidentFieldOrm.field == field
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = IncidentFieldOrm(call_id=call_id, field=field)
        db.add(row)
    # Don't overwrite an operator confirmation.
    if row.status == "confirmed_by_operator":
        return
    row.value = value
    row.status = status
    row.confidence = confidence
    row.source_segment_ids_json = source_segment_ids
    row.updated_at_t = t_now

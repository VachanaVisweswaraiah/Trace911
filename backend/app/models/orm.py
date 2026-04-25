"""SQLAlchemy 2.0 ORM models. Pydantic API schemas live in app.schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), default="upload")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # Latest snapshots stored inline as JSON. Cheap, single-call demo.
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    assist_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    transcript: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="call",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.t_start",
    )
    fields: Mapped[list["IncidentField"]] = relationship(
        back_populates="call",
        cascade="all, delete-orphan",
    )

    def t_for(self, when: datetime) -> float:
        return (when - self.started_at).total_seconds()


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    call_id: Mapped[str] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    t_start: Mapped[float] = mapped_column(Float)
    t_end: Mapped[float] = mapped_column(Float)
    speaker: Mapped[str] = mapped_column(String(16), default="unknown")
    text: Mapped[str] = mapped_column(Text, default="")
    is_final: Mapped[bool] = mapped_column(default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    entities_json: Mapped[list[Any]] = mapped_column(JSON, default=list)

    call: Mapped[Call] = relationship(back_populates="transcript")


class IncidentField(Base):
    __tablename__ = "incident_fields"

    call_id: Mapped[str] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), primary_key=True
    )
    field: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(32), default="missing")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_segment_ids_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    updated_at_t: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)

    call: Mapped[Call] = relationship(back_populates="fields")

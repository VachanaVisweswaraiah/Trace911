from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.incident import IncidentCard
from app.schemas.metrics import MetricsSnapshot
from app.schemas.transcript import TranscriptSegment

CallSource = Literal["upload", "live"]


class CallCreateRequest(BaseModel):
    source: CallSource = "upload"


class CallCreateResponse(BaseModel):
    call_id: str
    started_at: datetime
    ws_url: str


class Call(BaseModel):
    call_id: str
    source: CallSource
    started_at: datetime
    ended_at: datetime | None = None


class OperatorAssistSuggestion(BaseModel):
    id: str
    text: str
    reason: str | None = None


class HighRiskUnconfirmed(BaseModel):
    field: str
    quote: str
    t: float


class OperatorAssist(BaseModel):
    next_question: OperatorAssistSuggestion | None = None
    critical_missing: list[str] = Field(default_factory=list)
    high_risk_unconfirmed: list[HighRiskUnconfirmed] = Field(default_factory=list)


class CallSnapshot(BaseModel):
    call_id: str
    started_at: datetime
    ended_at: datetime | None = None
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    incident: IncidentCard
    metrics: MetricsSnapshot = Field(default_factory=MetricsSnapshot)
    assist: OperatorAssist = Field(default_factory=OperatorAssist)


class CallSummary(BaseModel):
    call_id: str
    narrative: str
    incident: IncidentCard
    unconfirmed: list[str] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)

from typing import Literal

from pydantic import BaseModel, Field

NoiseSeverity = Literal["low", "medium", "high", "severe"]


class AudioMetrics(BaseModel):
    noise_severity: NoiseSeverity = "low"
    enhancement_lift_db: float = 0.0
    speech_preservation_pct: float = 100.0
    model: str = "QUAIL_VF_L"
    enhancement_level: float = 0.8


class VadMetrics(BaseModel):
    speech_activity_ratio: float = 0.0
    false_start_count: int = 0
    avg_end_of_turn_ms: float = 0.0
    turns: int = 0
    overlap_events: int = 0


class TranscriptMetrics(BaseModel):
    health_score: int = Field(ge=0, le=100, default=0)
    low_confidence_words: int = 0
    revisions: int = 0


class IncidentMetrics(BaseModel):
    field_coverage: float = 0.0
    confirmed_coverage: float = 0.0
    dispatch_readiness: float = 0.0
    time_to_first_location_s: float | None = None
    time_to_incident_type_s: float | None = None
    time_to_dispatch_ready_s: float | None = None
    contradiction_count: int = 0


class AssistMetrics(BaseModel):
    suggestions_shown: int = 0
    suggestions_used: int = 0
    suggestions_dismissed: int = 0
    operator_overrides: int = 0
    high_risk_unconfirmed_count: int = 0


class MetricsSnapshot(BaseModel):
    audio: AudioMetrics = Field(default_factory=AudioMetrics)
    vad: VadMetrics = Field(default_factory=VadMetrics)
    transcript: TranscriptMetrics = Field(default_factory=TranscriptMetrics)
    incident: IncidentMetrics = Field(default_factory=IncidentMetrics)
    assist: AssistMetrics = Field(default_factory=AssistMetrics)


class _AudioWindowSide(BaseModel):
    rms_dbfs: float
    noise_floor_dbfs: float
    clipping_pct: float = 0.0
    speech_active: bool | None = None


class _AudioWindowLift(BaseModel):
    noise_reduction_db: float
    speech_preservation_pct: float


class AudioWindow(BaseModel):
    window_ms: int
    raw: _AudioWindowSide
    enhanced: _AudioWindowSide
    lift: _AudioWindowLift

from typing import Literal

from pydantic import BaseModel, Field

IncidentFieldName = Literal[
    "incident_type",
    "location",
    "number_of_people",
    "injury_status",
    "consciousness",
    "breathing",
    "immediate_danger",
    "weapons",
    "fire_or_smoke",
    "caller_callback",
    "access_instructions",
]

FIELD_NAMES: tuple[IncidentFieldName, ...] = (
    "incident_type",
    "location",
    "number_of_people",
    "injury_status",
    "consciousness",
    "breathing",
    "immediate_danger",
    "weapons",
    "fire_or_smoke",
    "caller_callback",
    "access_instructions",
)

FieldStatus = Literal[
    "missing",
    "heard",
    "suggested",
    "confirmed_by_operator",
    "uncertain",
    "contradicted",
]


class IncidentField(BaseModel):
    field: IncidentFieldName
    value: str | None = None
    status: FieldStatus = "missing"
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    source_segment_ids: list[str] = Field(default_factory=list)
    updated_at_t: float | None = None


class IncidentCard(BaseModel):
    incident_type: IncidentField
    location: IncidentField
    number_of_people: IncidentField
    injury_status: IncidentField
    consciousness: IncidentField
    breathing: IncidentField
    immediate_danger: IncidentField
    weapons: IncidentField
    fire_or_smoke: IncidentField
    caller_callback: IncidentField
    access_instructions: IncidentField

    field_coverage: float = 0.0
    confirmed_coverage: float = 0.0
    dispatch_readiness: float = 0.0

    @classmethod
    def empty(cls) -> "IncidentCard":
        return cls(**{name: IncidentField(field=name) for name in FIELD_NAMES})


class IncidentUpdate(BaseModel):
    field: IncidentFieldName
    value: str | None = None
    status: FieldStatus


class IncidentPatchRequest(BaseModel):
    updates: list[IncidentUpdate]

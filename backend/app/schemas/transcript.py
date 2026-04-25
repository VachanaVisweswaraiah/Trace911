from typing import Literal

from pydantic import BaseModel, Field

Speaker = Literal["caller", "bystander", "operator", "unknown"]


class Entity(BaseModel):
    type: str
    text: str
    field: str | None = None


class TranscriptSegment(BaseModel):
    id: str
    t_start: float
    t_end: float
    speaker: Speaker = "unknown"
    text: str
    is_final: bool = False
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    entities: list[Entity] = Field(default_factory=list)
